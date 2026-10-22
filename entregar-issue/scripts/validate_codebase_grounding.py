#!/usr/bin/env python3
"""Validate codebase-grounding.json against the exact Git contents of the candidate.

Exit codes: 0 READY, 2 BLOCK, 3 UNKNOWN (no usable checkout; never an approval).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from plan_execution import CODE_SUFFIXES, is_generated_path, is_test_path
from schema_validation import validate_against_schema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "codebase-grounding.schema.json"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True, text=True)


def read_at(repo: Path, sha: str, path: str) -> str | None:
    result = git(repo, "show", f"{sha}:{path}")
    return result.stdout if result.returncode == 0 else None


def mentions(text: str, token: str, *, package: bool = False) -> bool:
    """Whole-token match, so a prefix of a longer name is not accepted as proof."""
    boundary = "A-Za-z0-9_-" if package else "A-Za-z0-9_"
    return re.search(rf"(?<![{boundary}]){re.escape(token)}(?![{boundary}])", text) is not None


def requires_search_record(path: str) -> bool:
    return path.lower().endswith(CODE_SUFFIXES) and not is_test_path(path) and not is_generated_path(path)


def check_creations(report: dict[str, Any], repo: Path, base: str, head: str, errors: list[str]) -> None:
    diff = git(repo, "diff", "--name-only", "--diff-filter=A", base, head)
    if diff.returncode != 0:
        errors.append(f"cannot compute added files {base}..{head}: {diff.stderr.strip()}")
        return
    recorded = {item["path"]: item for item in report["creations"]}
    for path in sorted(filter(requires_search_record, diff.stdout.splitlines())):
        if path not in recorded:
            errors.append(f"GROUND-REUSE-001: added code file without search record: {path}")
        elif recorded[path]["decision"] != "create":
            errors.append(f"GROUND-REUSE-001: {path} was added but decision is {recorded[path]['decision']}")
    for item in report["creations"]:
        for candidate in item["search"]["candidates"]:
            if read_at(repo, head, candidate["path"]) is None:
                errors.append(f"GROUND-REUSE-001: candidate does not exist at head: {candidate['path']}")


def changed_tests(repo: Path, base: str, head: str, errors: list[str]) -> dict[str, tuple[str, str | None]]:
    """Git name-status covers additions, modifications, deletions and detected renames."""
    diff = git(repo, "diff", "--name-status", "--find-renames", "--no-ext-diff", base, head, "--")
    if diff.returncode != 0:
        errors.append(f"cannot inspect test diff {base}..{head}: {diff.stderr.strip()}")
        return {}
    changes: dict[str, tuple[str, str | None]] = {}
    for line in diff.stdout.splitlines():
        columns = line.split("\t")
        if len(columns) < 2:
            errors.append(f"invalid git name-status record: {line}")
            continue
        status = columns[0][:1]
        path = columns[-1]
        previous = columns[1] if status in {"R", "C"} and len(columns) == 3 else None
        if not (is_test_path(path) or (previous and is_test_path(previous))):
            continue
        operation = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "renamed"}.get(status)
        if operation is None:
            errors.append(f"unhandled test diff operation {columns[0]} for {path}")
            continue
        changes[path] = (operation, previous)
    return changes


def check_test_decisions(
    report: dict[str, Any], repo: Path, base: str, head: str,
    errors: list[str], unknown: list[str],
) -> None:
    changes = changed_tests(repo, base, head, errors)
    if not changes:
        if report.get("test_decisions"):
            errors.append("GROUND-TEST-001: test_decisions without test changes in issue-local diff")
        return
    if report["schema_version"] == 1:
        errors.append("GROUND-TEST-001: test diff needs schema_version 2 and test_decisions; legacy v1 accepted only without test changes")
        return
    records: dict[str, list[dict[str, Any]]] = {}
    for item in report["test_decisions"]:
        records.setdefault(item["path"], []).append(item)
    for path, (operation, previous) in changes.items():
        if path not in records:
            errors.append(f"GROUND-TEST-001: test diff lacks decision: {path}")
        for item in records.get(path, []):
            if item["operation"] != operation or item.get("prior_path") != previous:
                errors.append(f"GROUND-TEST-001: test operation/prior_path mismatch: {path}")
            if operation == "deleted":
                if read_at(repo, base, path) is None:
                    errors.append(f"GROUND-TEST-001: deleted test absent at base: {path}")
                if not item.get("coverage_before") or not item.get("coverage_after"):
                    errors.append(f"GROUND-TEST-001: deletion requires before/after controls: {path}")
                if item["disposition"] not in {"refactor/consolidate", "remove-candidate"}:
                    errors.append(f"GROUND-TEST-001: deletion requires reasoned removal disposition: {path}")
                if item["verification"]["status"] != "passed":
                    errors.append(f"GROUND-TEST-001: deletion lacks passed replacement control: {path}")
                before, after = set(item.get("coverage_before") or []), set(item.get("coverage_after") or [])
                if before - after:
                    errors.append(f"GROUND-TEST-001: deleted test loses documented control IDs: {path}")
                replacements = item.get("replacement_tests") or []
                if not replacements:
                    errors.append(f"GROUND-TEST-001: deletion has no surviving replacement test: {path}")
                for replacement in replacements:
                    if replacement == path or not is_test_path(replacement) or read_at(repo, head, replacement) is None:
                        errors.append(f"GROUND-TEST-001: replacement not found as test at head: {replacement}")
                evidence = item["verification"]
                if evidence.get("subject_sha") != head:
                    errors.append(f"GROUND-TEST-001: replacement execution not bound to head: {path}")
                reached = evidence.get("reached_tests") or []
                if not replacements or not set(replacements).issubset(set(reached)):
                    errors.append(f"GROUND-TEST-001: replacement tests not recorded as reached: {path}")
                command = evidence.get("command") or ""
                if path in command and not any(replacement in command for replacement in replacements):
                    errors.append(f"GROUND-TEST-001: command targets only deleted test: {path}")
                proof_path = evidence.get("evidence_path")
                proof_sha = evidence.get("evidence_sha256")
                if not proof_path or not proof_sha:
                    errors.append(f"GROUND-TEST-001: deletion lacks raw execution evidence: {path}")
                else:
                    location = (repo / proof_path).resolve()
                    if not location.is_relative_to(repo.resolve()) or not location.is_file():
                        errors.append(f"GROUND-TEST-001: execution evidence file unavailable: {path}")
                    else:
                        raw = location.read_bytes()
                        if hashlib.sha256(raw).hexdigest() != proof_sha:
                            errors.append(f"GROUND-TEST-001: execution evidence hash mismatch: {path}")
                        elif not all(replacement.encode() in raw for replacement in replacements):
                            errors.append(f"GROUND-TEST-001: raw evidence does not identify replacement: {path}")
            elif read_at(repo, head, path) is None:
                errors.append(f"GROUND-TEST-001: test absent at head: {path}")
            if previous and read_at(repo, base, previous) is None:
                errors.append(f"GROUND-TEST-001: renamed source absent at base: {previous}")
            for candidate in item["search"]["candidates"]:
                if read_at(repo, head, candidate["path"]) is None and read_at(repo, base, candidate["path"]) is None:
                    errors.append(f"GROUND-TEST-001: candidate absent in both revisions: {candidate['path']}")
            check = item["verification"]
            if check["status"] == "passed" and (not check.get("command") or check.get("exit_code") != 0):
                errors.append(f"GROUND-TEST-001: passed check lacks command/exit_code=0: {path}")
            if check["status"] != "passed":
                if not check.get("reason"):
                    errors.append(f"GROUND-TEST-001: {check['status']} lacks reason: {path}")
                else:
                    unknown.append(f"GROUND-TEST-001: {path} {check['status']}: {check['reason']}")
            if item["decision"] == "not-testable/blocked" and check["status"] == "passed":
                errors.append(f"GROUND-TEST-001: blocked scenario cannot claim passed: {path}")
            if item["decision"] == "not-testable/blocked" and not check.get("reason"):
                errors.append(f"GROUND-TEST-001: blocked scenario needs alternative/limitation: {path}")
    for path in records.keys() - changes.keys():
        errors.append(f"GROUND-TEST-001: decision path not changed in test diff: {path}")


def check_references(report: dict[str, Any], repo: Path, head: str, errors: list[str]) -> None:
    for item in report["references"]:
        symbol = item["symbol"]
        consumer = read_at(repo, head, item["used_in"])
        if consumer is None:
            errors.append(f"GROUND-EXIST-001: consumer does not exist at head: {item['used_in']}")
        elif not mentions(consumer, symbol):
            errors.append(f"GROUND-EXIST-001: {item['used_in']} does not reference {symbol}")
        if item["kind"] == "local":
            where = item["defined_at"]
            source = read_at(repo, head, where["path"])
            lines = source.splitlines() if source is not None else []
            if source is None:
                errors.append(f"GROUND-EXIST-001: definition file does not exist at head: {where['path']}")
            elif where["line"] > len(lines) or not mentions(lines[where["line"] - 1], symbol):
                errors.append(f"GROUND-EXIST-001: {symbol} is not defined at {where['path']}:{where['line']}")
        else:
            manifest = item["manifest"]
            source = read_at(repo, head, manifest["path"])
            if source is None:
                errors.append(f"GROUND-EXIST-001: manifest does not exist at head: {manifest['path']}")
            elif not mentions(source, manifest["name"], package=True):
                errors.append(f"GROUND-EXIST-001: {manifest['name']} is not declared in {manifest['path']}")


def check_replacements(report: dict[str, Any], repo: Path, head: str, errors: list[str]) -> None:
    for item in report["replacements"]:
        old = read_at(repo, head, item["old_path"])
        symbol = item.get("old_symbol")
        if item["disposition"] == "removed":
            if old is not None and (symbol is None or mentions(old, symbol)):
                errors.append(f"GROUND-DEAD-001: declared removed but still present: {item['old_path']} {symbol or ''}".rstrip())
            continue
        consumer = read_at(repo, head, item["consumer"])
        if old is None or not mentions(old, symbol):
            errors.append(f"GROUND-DEAD-001: declared kept but absent at head: {item['old_path']} {symbol}")
        if consumer is None or not mentions(consumer, symbol) or item["consumer"] == item["old_path"]:
            errors.append(f"GROUND-DEAD-001: kept symbol has no real consumer: {symbol} in {item['consumer']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    for sha in (args.base_sha, args.head_sha):
        if git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            print(f"UNKNOWN: commit {sha} is not available in checkout {repo}")
            return 3
    try:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"BLOCK: invalid codebase-grounding report: {exc}")
        return 2

    errors: list[str] = []
    unknown: list[str] = []
    validate_against_schema(report, SCHEMA, "codebase-grounding", errors)
    if not errors:
        if report["subject_sha"] != args.head_sha:
            errors.append("codebase-grounding evidence is stale for material head")
        if report["base_sha"] != args.base_sha:
            errors.append("codebase-grounding base does not match work item start")
        check_creations(report, repo, args.base_sha, args.head_sha, errors)
        check_test_decisions(report, repo, args.base_sha, args.head_sha, errors, unknown)
        check_references(report, repo, args.head_sha, errors)
        check_replacements(report, repo, args.head_sha, errors)
    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    if unknown:
        for item in unknown:
            print(f"UNKNOWN: {item}")
        return 3
    print(f"READY: codebase grounding verified at {args.head_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
