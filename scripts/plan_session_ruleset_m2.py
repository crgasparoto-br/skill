#!/usr/bin/env python3
"""Read-only plan for the post-acceptance M2 ruleset migration.

This tool never writes GitHub settings, confirms an independent review, or
certifies negative controls. An administrator must first verify live M2
acceptance and then apply the reviewed plan through the GitHub UI.
"""
from __future__ import annotations

import argparse
import copy
import fnmatch
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
    "main": (
        "Structure and tests",
        "Offline authorization tests",
        "collect / Require certified semantic handoff (exact SHA)",
        SESSION,
    ),
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
    require(isinstance(approvals.get("required_reviewers"), list),
            "required team reviewer inventory unavailable")
    require(approvals["required_reviewers"] == [],
            "required team reviewers still configured")
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


def _matches_ref(pattern: str, ref: str, default_ref: str) -> bool:
    if pattern == "~ALL":
        return True
    if pattern == "~DEFAULT_BRANCH":
        return ref == default_ref
    return fnmatch.fnmatchcase(ref, pattern)


def ruleset_applies_to_branch(ruleset: dict, branch: str, default_branch: str) -> bool:
    """Conservatively decide whether an active branch ruleset affects this branch."""
    if ruleset.get("target") != "branch":
        return False
    ref = f"refs/heads/{branch}"
    default_ref = f"refs/heads/{default_branch}"
    ref_name = (ruleset.get("conditions") or {}).get("ref_name")
    require(isinstance(ref_name, dict), "active ruleset ref conditions unavailable")
    include = ref_name.get("include")
    exclude = ref_name.get("exclude")
    require(isinstance(include, list) and isinstance(exclude, list),
            "active ruleset ref conditions malformed")
    require(all(isinstance(item, str) for item in include + exclude),
            "active ruleset ref pattern malformed")
    included = any(_matches_ref(pattern, ref, default_ref) for pattern in include)
    excluded = any(_matches_ref(pattern, ref, default_ref) for pattern in exclude)
    return included and not excluded


def verify_classic_protection(protection: dict | None, branch: str) -> None:
    """Reject classic protection that reintroduces M2 gates or weakens safety."""
    if protection is None:
        return
    require(isinstance(protection, dict), "classic branch protection response malformed")
    force = protection.get("allow_force_pushes")
    deletion = protection.get("allow_deletions")
    require(isinstance(force, dict) and force.get("enabled") is False,
            "classic protection permits force-push")
    require(isinstance(deletion, dict) and deletion.get("enabled") is False,
            "classic protection permits deletion")

    reviews = protection.get("required_pull_request_reviews")
    if reviews is not None:
        require(isinstance(reviews, dict), "classic PR review protection malformed")
        count = reviews.get("required_approving_review_count")
        require(type(count) is int and count == 0,
                "classic protection still requires human review or count is unavailable")
        require(reviews.get("require_code_owner_reviews") is False,
                "classic protection still requires code-owner review")
        require(reviews.get("require_last_push_approval") is False,
                "classic protection still requires last-push review")
        require("bypass_pull_request_allowances" in reviews,
                "classic review bypass inventory missing")
        bypass = reviews["bypass_pull_request_allowances"]
        require(isinstance(bypass, dict), "classic review bypass inventory malformed")
        for key in ("users", "teams", "apps"):
            require(key in bypass and isinstance(bypass[key], list),
                    f"classic {key} bypass inventory missing")
            require(not bypass[key], f"classic protection has {key} review bypasses")

    statuses = protection.get("required_status_checks")
    if statuses is not None:
        require(isinstance(statuses, dict) and statuses.get("strict") is True,
                "classic required checks are not strict")
        contexts = statuses.get("contexts")
        require(isinstance(contexts, list) and all(isinstance(x, str) for x in contexts),
                "classic required check contexts malformed")
        require(len(contexts) == len(set(contexts)),
                "duplicate classic required check contexts")
        require(LEGACY not in contexts, "classic protection still requires legacy audit gate")
        checks = statuses.get("checks")
        require(isinstance(checks, list), "classic required check origin inventory missing")
        check_names = [item.get("context") for item in checks if isinstance(item, dict)]
        require(len(check_names) == len(checks) and len(check_names) == len(set(check_names)),
                "duplicate or malformed classic required checks")
        require(LEGACY not in check_names,
                "classic protection still requires legacy audit gate")
        for check in checks:
            require(isinstance(check, dict) and isinstance(check.get("context"), str),
                    "classic required check malformed")
            if check["context"] in REQUIRED[branch]:
                require(check.get("app_id") == APP_ID,
                        f"classic protection has unexpected app origin for {check['context']}")


def verify_effective_state(state: dict, branch: str, ruleset_id: int) -> dict:
    """Verify the selected rule and every observed effective protection source."""
    require(branch in REQUIRED, "unsupported protected branch")
    require(isinstance(state, dict), "effective state missing")
    default_branch = state.get("default_branch")
    require(isinstance(default_branch, str) and default_branch,
            "repository default branch unavailable")
    target = state.get("target_ruleset")
    require(isinstance(target, dict), "target ruleset unavailable")
    verified = verify_live_ruleset(target, branch, ruleset_id)

    inventory = state.get("rulesets")
    require(isinstance(inventory, list), "ruleset inventory unavailable")
    seen_ids = set()
    found_target = False
    competing = []
    for rule in inventory:
        require(isinstance(rule, dict) and type(rule.get("id")) is int,
                "ruleset inventory item malformed")
        rule_id = rule["id"]
        require(rule_id not in seen_ids, "duplicate ruleset id in effective inventory")
        seen_ids.add(rule_id)
        require(rule.get("target") in {"branch", "tag", "push"},
                "ruleset inventory target unavailable")
        require(rule.get("enforcement") in {"active", "disabled", "evaluate"},
                "ruleset inventory enforcement unavailable")
        require(isinstance(rule.get("bypass_actors"), list),
                "ruleset bypass inventory unavailable")
        if rule_id == ruleset_id:
            found_target = True
            require(rule == target, "target ruleset differs from inventory detail")
            require(rule["enforcement"] == "active",
                    "target ruleset is not active in inventory")
            continue
        if rule["enforcement"] == "active" and ruleset_applies_to_branch(
            rule, branch, default_branch
        ):
            competing.append(rule_id)
    require(found_target, "target ruleset missing from complete inventory")
    require(not competing, f"additional active ruleset applies to branch: {competing}")
    verify_classic_protection(state.get("classic_protection"), branch)
    return {
        **verified,
        "effective_sources_verified": True,
        "active_competing_rulesets": [],
        "classic_protection_checked": True,
    }

def verify_live_ruleset(current: dict, branch: str, ruleset_id: int) -> dict:
    """Check the target M2 ruleset structure; not proof of complete effective state."""
    require(current.get("enforcement") == "active", "ruleset is not enforced")
    expected = plan_m2(current, branch, ruleset_id)
    for field in ("name", "target", "enforcement", "conditions", "bypass_actors", "rules"):
        require(current.get(field) == expected[field],
                f"effective ruleset differs from required M2 policy: {field}")
    status = next(r for r in current["rules"] if r["type"] == "required_status_checks")
    return {
        "status": "ACTIVE_RULESET_STRUCTURE_VERIFIED_NOT_M2_APPROVAL",
        "branch": branch,
        "ruleset_id": ruleset_id,
        "required_checks": status["parameters"]["required_status_checks"],
        "session_review_or_negative_controls_verified": False,
    }


def gh_api(repository: str, path: str) -> object:
    result = subprocess.run(
        ["gh", "api", path],
        capture_output=True, text=True, check=False,
    )
    require(result.returncode == 0,
            f"authenticated GitHub GET failed for {path}; no changes were made")
    return json.loads(result.stdout)


def read_all_rulesets(repository: str) -> list[dict]:
    """Require full GitHub pagination; a partial ruleset list is not a snapshot."""
    path = f"/repos/{repository}/rulesets?includes_parents=true&per_page=100"
    result = subprocess.run(
        ["gh", "api", "--paginate", "--slurp", path],
        capture_output=True, text=True, check=False,
    )
    require(result.returncode == 0,
            "authenticated paginated ruleset GET failed; no changes were made")
    pages = json.loads(result.stdout)
    require(isinstance(pages, list) and all(isinstance(page, list) for page in pages),
            "paginated ruleset inventory shape is incomplete or malformed")
    return [rule for page in pages for rule in page]


def read_ruleset(repository: str, ruleset_id: int) -> dict:
    data = gh_api(repository, f"/repos/{repository}/rulesets/{ruleset_id}")
    require(isinstance(data, dict), "GitHub ruleset response is not an object")
    return data


def read_classic_protection(
    repository: str, branch: str, *, admin_confirmed: bool = False
) -> dict | None:
    result = subprocess.run(
        ["gh", "api", f"/repos/{repository}/branches/{branch}/protection"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        data = json.loads(result.stdout)
        require(isinstance(data, dict), "classic branch protection response is not an object")
        return data
    if "HTTP 404" in result.stderr or "Branch not protected" in result.stderr:
        require(admin_confirmed,
                "classic protection HTTP 404 is ambiguous without authenticated admin rights")
        return None
    raise ValueError("authenticated classic branch protection GET failed; no changes were made")


def read_effective_state(repository: str, branch: str, ruleset_id: int) -> dict:
    repo_meta = gh_api(repository, f"/repos/{repository}")
    require(isinstance(repo_meta, dict), "repository metadata response is not an object")
    default_branch = repo_meta.get("default_branch")
    require(isinstance(default_branch, str) and default_branch,
            "repository default branch unavailable")

    summaries = read_all_rulesets(repository)
    seen_ids = set()
    details = []
    for item in summaries:
        require(isinstance(item, dict) and type(item.get("id")) is int,
                "ruleset inventory item lacks numeric id")
        rule_id = item["id"]
        require(rule_id > 0 and rule_id not in seen_ids,
                "duplicate or invalid ruleset id in paginated inventory")
        seen_ids.add(rule_id)
        require(item.get("target") in {"branch", "tag", "push"},
                "ruleset summary target unavailable")
        require(item.get("enforcement") in {"active", "disabled", "evaluate"},
                "ruleset summary enforcement unavailable")
        detail = gh_api(repository, f"/repos/{repository}/rulesets/{rule_id}")
        require(isinstance(detail, dict), "GitHub ruleset detail is not an object")
        require(detail.get("id") == rule_id and detail.get("target") == item["target"],
                "ruleset identity changed between summary and detail")
        require(detail.get("enforcement") == item["enforcement"],
                "ruleset enforcement changed during inventory collection")
        require(isinstance(detail.get("bypass_actors"), list),
                "bypass actors are not visible for an inventoried ruleset")
        details.append(detail)

    target = next((item for item in details if item.get("id") == ruleset_id), None)
    require(target is not None, "target ruleset not found in complete inventory")
    permissions = repo_meta.get("permissions")
    admin_confirmed = isinstance(permissions, dict) and permissions.get("admin") is True
    return {
        "default_branch": default_branch,
        "target_ruleset": target,
        "rulesets": details,
        "classic_protection": read_classic_protection(
            repository, branch, admin_confirmed=admin_confirmed
        ),
    }

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True, choices=list(REQUIRED))
    parser.add_argument("--ruleset-id", type=int, required=True)
    parser.add_argument("--readback", action="store_true",
                        help="verify complete effective M2 protection state without mutating settings")
    options = parser.parse_args()
    require(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", options.repo) is not None,
            "repository must be owner/name")
    require(options.ruleset_id > 0, "invalid ruleset ID")
    if options.readback:
        state = read_effective_state(options.repo, options.branch, options.ruleset_id)
        print(json.dumps(verify_effective_state(state, options.branch, options.ruleset_id),
                         ensure_ascii=False, indent=2))
        return
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
