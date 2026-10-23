#!/usr/bin/env python3
"""Safely configure verified GitHub Actions checks on an existing branch ruleset.

Requires an independently authenticated GitHub CLI with Administration:write.
Preview is read-only; --apply requires explicit operator action.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import subprocess
import sys


def gh(endpoint: str, method: str = "GET", payload: dict | None = None) -> dict:
    cmd = ["gh", "api", endpoint, "-H", "Accept: application/vnd.github+json"]
    if method != "GET":
        cmd.extend(["--method", method, "--input", "-"])
    run = subprocess.run(cmd, input=json.dumps(payload) if payload is not None else None,
                         text=True, capture_output=True, check=False)
    if run.returncode:
        raise ValueError(f"GitHub {method} {endpoint} failed: {run.stderr[:600]}")
    result = json.loads(run.stdout)
    if not isinstance(result, dict):
        raise ValueError("GitHub response is not an object")
    return result


def verified_checks(repo: str, sha: str, names: list[str], app_id: int) -> dict:
    data = gh(f"/repos/{repo}/commits/{sha}/check-runs?per_page=100")
    runs = data.get("check_runs")
    if not isinstance(runs, list) or data.get("total_count", len(runs)) > len(runs):
        raise ValueError("check-run inventory is incomplete")
    found = {}
    for name in names:
        matches = [r for r in runs if r.get("name") == name
                   and (r.get("app") or {}).get("id") == app_id]
        if not matches:
            raise ValueError(f"missing GitHub Actions check on sample SHA: {name}")
        found[name] = [r.get("conclusion") for r in matches]
    return found


def plan(current: dict, branch: str, ruleset_id: int,
         names: list[str], app_id: int) -> dict:
    if (current.get("id") != ruleset_id or current.get("target") != "branch"
            or current.get("enforcement") != "active"):
        raise ValueError("ruleset identity or enforcement does not match")
    conditions = current.get("conditions") or {}
    expected = {"include": [f"refs/heads/{branch}"], "exclude": []}
    if conditions.get("ref_name") != expected:
        raise ValueError("branch targeting differs from exact requested branch")
    if not isinstance(current.get("bypass_actors"), list):
        raise ValueError("bypass actor visibility is required before changing rules")
    rules = copy.deepcopy(current.get("rules") or [])
    review_rules = [r for r in rules if r.get("type") == "pull_request"]
    if len(review_rules) != 1:
        raise ValueError("one existing PR review rule is required")
    review_parameters = review_rules[0].get("parameters")
    if not isinstance(review_parameters, dict):
        raise ValueError("PR review parameters unavailable")
    current_approvals = review_parameters.get("required_approving_review_count")
    if type(current_approvals) is not int or current_approvals < 0:
        raise ValueError("current PR approval count is invalid")
    review_parameters["required_approving_review_count"] = max(1, current_approvals)
    checks = [r for r in rules if r.get("type") == "required_status_checks"]
    if len(checks) != 1:
        raise ValueError("expected exactly one required-status-checks rule")
    params = checks[0]["parameters"]
    if params.get("strict_required_status_checks_policy") is not True:
        raise ValueError("existing strict required checks must remain enabled")
    # Never drop a status context which was already mandatory. Rollout only adds
    # checks; removal/replacement requires a separate explicitly audited migration.
    existing = params.get("required_status_checks")
    if not isinstance(existing, list):
        raise ValueError("current required check inventory unavailable")
    contexts = {}
    for item in existing:
        if not isinstance(item, dict) or not item.get("context"):
            raise ValueError("malformed existing required status check")
        if item["context"] in contexts:
            raise ValueError("duplicate existing required status check")
        contexts[item["context"]] = item
    for name in names:
        old = contexts.get(name)
        if old is not None and old.get("integration_id") != app_id:
            raise ValueError(f"existing check origin differs: {name}")
        if old is None:
            existing.append({"context": name, "integration_id": app_id})
    return {
        "name": current["name"], "target": current["target"],
        "enforcement": current["enforcement"], "conditions": copy.deepcopy(conditions),
        "bypass_actors": copy.deepcopy(current["bypass_actors"]), "rules": rules,
    }


def verify(before: dict, after: dict, payload: dict) -> None:
    if after.get("id") != before.get("id"):
        raise ValueError("ruleset identity drift after write")
    for field in ("name", "target", "enforcement", "conditions", "bypass_actors", "rules"):
        if after.get(field) != payload[field]:
            raise ValueError(f"ruleset read-back mismatch: {field}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--branch", required=True, choices=["develop", "main"])
    parser.add_argument("--ruleset-id", type=int, required=True)
    parser.add_argument("--sample-sha", required=True)
    parser.add_argument("--check", action="append", required=True)
    parser.add_argument("--app-id", type=int, default=15368)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("--repo must be owner/repository")
    if not re.fullmatch(r"[0-9a-f]{40}", args.sample_sha):
        parser.error("--sample-sha must be exact 40-char lowercase Git SHA")
    if args.ruleset_id <= 0 or args.app_id <= 0 or len(set(args.check)) != len(args.check):
        parser.error("invalid ruleset/app ID or repeated check")
    if args.branch == "main" and not any(
        "audit" in name.lower() or "release" in name.lower() for name in args.check
    ):
        parser.error("main needs a real independent audit/release check; technical CI is insufficient")

    if args.apply and (
        "Verify independent audit (exact SHA)" not in args.check
        or (args.branch == "develop" and
            "collect / Require certified semantic handoff (exact SHA)" not in args.check)
    ):
        parser.error("--apply requires independent audit gate (and certified handoff on develop)")
    names = verified_checks(args.repo, args.sample_sha, args.check, args.app_id)
    endpoint = f"/repos/{args.repo}/rulesets/{args.ruleset_id}"
    current = gh(endpoint)
    payload = plan(current, args.branch, args.ruleset_id, args.check, args.app_id)
    print(json.dumps({"ruleset_id": args.ruleset_id, "branch": args.branch,
                      "checks": names, "apply": args.apply}, indent=2))
    if not args.apply:
        print("DRY RUN: no ruleset settings were changed")
        return

    before = gh(endpoint)
    for field in ("updated_at", "rules", "bypass_actors", "conditions"):
        if before.get(field) != current.get(field):
            raise ValueError(f"ruleset changed after preview: {field}")
    gh(endpoint, method="PUT", payload=payload)
    verify(before, gh(endpoint), payload)
    print("APPLIED AND READ-BACK VERIFIED")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        sys.exit(2)
