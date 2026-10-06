#!/usr/bin/env python3
"""Produce CODE-GROWTH-001 evidence for the issue-local delta of a candidate.

Exit codes: 0 passed, 2 blocked, 3 UNKNOWN (no usable checkout; never an approval).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from plan_execution import CODE_SUFFIXES, is_generated_path, is_test_path

POLICY_PATH = ".github/code-growth-policy.json"
DEFAULT_POLICY: dict[str, Any] = {
    "new_file_soft_limit": 300,
    "new_file_hard_limit": 500,
    "legacy_growth_allowance": 20,
    "exempt_path_markers": ["/vendor/", "/node_modules/", "/third_party/", "/migrations/"],
}
LIMIT_KEYS = ("new_file_soft_limit", "new_file_hard_limit", "legacy_growth_allowance")


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def line_count(repo: Path, sha: str, path: str) -> int | None:
    result = git(repo, "show", f"{sha}:{path}")
    return len(result.stdout.splitlines()) if result.returncode == 0 else None


def load_policy(repo: Path, base: str, policy_path: str) -> tuple[dict[str, Any], str]:
    """Read the policy from the trusted base only; the candidate cannot loosen its own limits."""
    result = git(repo, "show", f"{base}:{policy_path}")
    if result.returncode != 0:
        return dict(DEFAULT_POLICY), "default"
    override = json.loads(result.stdout)
    if not isinstance(override, dict) or set(override) - set(DEFAULT_POLICY):
        raise ValueError("policy must be an object with known keys only")
    policy = {**DEFAULT_POLICY, **override}
    if any(type(policy[key]) is not int or policy[key] < 0 for key in LIMIT_KEYS):
        raise ValueError("policy limits must be non-negative integers")
    if policy["new_file_soft_limit"] > policy["new_file_hard_limit"]:
        raise ValueError("new_file_soft_limit cannot exceed new_file_hard_limit")
    markers = policy["exempt_path_markers"]
    if not isinstance(markers, list) or not all(isinstance(item, str) and item for item in markers):
        raise ValueError("exempt_path_markers must be a list of non-empty strings")
    return policy, f"{base}:{policy_path}"


def is_measured(path: str, policy: dict[str, Any]) -> bool:
    normalized = "/" + path.replace("\\", "/").lower().lstrip("/")
    return (
        normalized.endswith(CODE_SUFFIXES)
        and not is_test_path(path)
        and not is_generated_path(path)
        and not any(marker.lower() in normalized for marker in policy["exempt_path_markers"])
    )


def evaluate(before: int | None, after: int, policy: dict[str, Any], justified: bool) -> str | None:
    """Return the blocking reason for one file, or None when it passes."""
    soft, hard, allowance = (policy[key] for key in LIMIT_KEYS)
    if before is None:
        if after > hard:
            return f"new file has {after} lines; hard limit is {hard}"
        if after > soft and not justified:
            return f"new file has {after} lines; above {soft} requires a recorded justification"
        return None
    if before <= hard < after:
        return f"file grew from {before} to {after} lines and crossed the hard limit of {hard}"
    if before > hard and after - before > allowance:
        return f"oversized file grew by {after - before} lines; allowance is {allowance}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base-sha", required=True, help="work_item_start_sha; also the trusted anchor of the policy")
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--justifications", help="JSON object: path -> reason, for new files above the soft limit")
    parser.add_argument("--policy-path", default=POLICY_PATH)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    for sha in (args.base_sha, args.head_sha):
        if git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            print(f"UNKNOWN: commit {sha} is not available in checkout {repo}")
            return 3
    try:
        policy, policy_source = load_policy(repo, args.base_sha, args.policy_path)
        justifications = json.loads(Path(args.justifications).read_text(encoding="utf-8")) if args.justifications else {}
        if not isinstance(justifications, dict):
            raise ValueError("justifications must be an object")
    except Exception as exc:
        print(f"BLOCK: invalid code-growth policy or justifications: {exc}")
        return 2
    diff = git(repo, "diff", "--name-only", "--no-renames", "--diff-filter=AM", args.base_sha, args.head_sha)
    if diff.returncode != 0:
        print(f"BLOCK: cannot compute issue-local delta: {diff.stderr.strip()}")
        return 2

    files: list[dict[str, Any]] = []
    blocking: list[dict[str, str]] = []
    for path in sorted(diff.stdout.splitlines()):
        if not is_measured(path, policy):
            continue
        before = line_count(repo, args.base_sha, path)
        after = line_count(repo, args.head_sha, path) or 0
        reason = str(justifications.get(path) or "").strip()
        entry: dict[str, Any] = {"path": path, "lines_before": before, "lines_after": after}
        if before is None and after > policy["new_file_soft_limit"] and reason:
            entry["justification"] = reason
        files.append(entry)
        problem = evaluate(before, after, policy, bool(reason))
        if problem:
            blocking.append({"path": path, "reason": problem})

    report = {
        "schema_version": 1,
        "control_id": "CODE-GROWTH-001",
        "status": "blocked" if blocking else "passed",
        "subject_sha": args.head_sha,
        "base_sha": args.base_sha,
        "policy": {**policy, "source": policy_source},
        "files": files,
        "blocking_files": blocking,
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for item in blocking:
        print(f"BLOCK: CODE-GROWTH-001: {item['path']}: {item['reason']}")
    if blocking:
        return 2
    print(f"READY: CODE-GROWTH-001 passed for {len(files)} measured file(s) at {args.head_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
