#!/usr/bin/env python3
"""Read-only plan for the post-acceptance M2 ruleset migration.

This tool never writes GitHub settings, confirms an independent review, or
certifies negative controls. An administrator must first verify live M2
acceptance and then apply the reviewed plan through the GitHub UI.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess

APP_ID = 15368
LEGACY = "Verify independent audit (exact SHA)"
SESSION = "Verify session review (exact SHA)"
REQUIRED = {
    "develop": (
        "Structure and tests",
        "Offline authorization tests",
        "collect / Require certified semantic handoff (exact SHA)",
        SESSION,
    ),
    "main": ("Structure and tests", SESSION),
}


def require(ok: bool, why: str) -> None:
    if not ok:
        raise ValueError(why)


def exactly_one(rules: list[dict], kind: str) -> dict:
    found = [r for r in rules if r.get("type") == kind]
    require(len(found) == 1, f"exactly one {kind} rule is required")
    return found[0]


def plan_m2(current: dict, branch: str, ruleset_id: int) -> dict:
    """Produce an administrative proposal, refusing hidden or weaker rules."""
    require(branch in REQUIRED, "unsupported protected branch")
    require(current.get("id") == ruleset_id and current.get("target") == "branch",
            "ruleset identity mismatch")
    require(current.get("enforcement") in {"active", "disabled"},
            "unknown ruleset enforcement")
    require(current.get("conditions", {}).get("ref_name") == {
        "include": [f"refs/heads/{branch}"], "exclude": []},
        "ruleset does not target only the requested branch")
    require(isinstance(current.get("bypass_actors"), list),
            "bypass actors are not visible: authenticated admin read required")
    require(current["bypass_actors"] == [],
            "nonempty bypass actors require administrative exception review")
    original = current.get("rules")
    require(isinstance(original, list), "ruleset rules unavailable")
    rules = copy.deepcopy(original)
    exactly_one(rules, "deletion")
    exactly_one(rules, "non_fast_forward")
    approvals = exactly_one(rules, "pull_request").get("parameters")
    require(isinstance(approvals, dict), "PR protection parameters unavailable")
    old_count = approvals.get("required_approving_review_count")
    require(type(old_count) is int and 0 <= old_count <= 10, "invalid previous review count")
    # A review count of zero must not silently preserve other human-review gates.
    require(approvals.get("required_reviewers", []) == [], "required team reviewers still configured")
    require(approvals.get("require_code_owner_review") is False,
            "code-owner review requirement must be evaluated separately")
    require(approvals.get("require_last_push_approval") is False,
            "last-push review requirement must be evaluated separately")
    approvals["required_approving_review_count"] = 0

    statuses = exactly_one(rules, "required_status_checks").get("parameters")
    require(isinstance(statuses, dict) and statuses.get("strict_required_status_checks_policy") is True,
            "strict required checks missing")
    require(statuses.get("do_not_enforce_on_create") is False,
            "required checks must apply to branch creation")
    checks = statuses.get("required_status_checks")
    require(isinstance(checks, list), "required check inventory missing")
    indexed = {}
    for item in checks:
        require(isinstance(item, dict) and isinstance(item.get("context"), str),
                "malformed required check")
        name = item["context"]
        require(name not in indexed, f"duplicate required check: {name}")
        indexed[name] = copy.deepcopy(item)
    # Do not remove, loosen or change the origin of any technical/custom check.
    for name in REQUIRED[branch]:
        if name in indexed:
            require(indexed[name].get("integration_id") == APP_ID,
                    f"unexpected app origin for {name}")
        else:
            indexed[name] = {"context": name, "integration_id": APP_ID}
    require("Structure and tests" in indexed, "technical check was lost")
    if LEGACY in indexed:
        require(indexed[LEGACY].get("integration_id") == APP_ID,
                "legacy check has unexpected app origin")
        indexed.pop(LEGACY)
    else:
        require(old_count == 0 and SESSION in indexed,
                "legacy audit gate absent before migration")
    statuses["required_status_checks"] = list(indexed.values())
    planned = {
        "name": current["name"], "target": "branch", "enforcement": "active",
        "conditions": copy.deepcopy(current["conditions"]),
        "bypass_actors": copy.deepcopy(current["bypass_actors"]),
        "rules": rules,
    }
    original_unrelated = [r for r in original
                          if r.get("type") not in {"pull_request", "required_status_checks"}]
    proposed_unrelated = [r for r in rules
                          if r.get("type") not in {"pull_request", "required_status_checks"}]
    require(original_unrelated == proposed_unrelated, "unrelated rules changed")
    return planned


def read_ruleset(repository: str, ruleset_id: int) -> dict:
    result = subprocess.run(
        ["gh", "api", f"/repos/{repository}/rulesets/{ruleset_id}"],
        capture_output=True, text=True, check=False,
    )
    require(result.returncode == 0, "authenticated ruleset GET failed; no changes were made")
    data = json.loads(result.stdout)
    require(isinstance(data, dict), "GitHub ruleset response is not an object")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True, choices=list(REQUIRED))
    parser.add_argument("--ruleset-id", type=int, required=True)
    options = parser.parse_args()
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", options.repo) is not None,
            "repository must be owner/name")
    require(options.ruleset_id > 0, "invalid ruleset ID")
    current = read_ruleset(options.repo, options.ruleset_id)
    planned = plan_m2(current, options.branch, options.ruleset_id)
    print(json.dumps({
        "status": "READ_ONLY_PROPOSAL_NOT_M2_APPROVAL",
        "repository": options.repo, "branch": options.branch,
        "ruleset_id": options.ruleset_id,
        "before_enforcement": current["enforcement"],
        "requires_prior_real_positive_and_negative_M2_acceptance": True,
        "requires_administrator_read_back_after_change": True,
        "proposed_ruleset": planned,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        raise SystemExit(f"BLOCK: {exc}") from exc
