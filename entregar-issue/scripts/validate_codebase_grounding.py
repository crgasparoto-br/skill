#!/usr/bin/env python3
"""Validate codebase-grounding.json against the exact Git contents of the candidate.

Exit codes: 0 READY, 2 BLOCK, 3 UNKNOWN (no usable checkout; never an approval).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from orchestrator_gate.schema_validation import validate_against_schema
from plan_execution import CODE_SUFFIXES, is_generated_path, is_test_path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "codebase-grounding.schema.json"


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


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
    validate_against_schema(report, SCHEMA, "codebase-grounding", errors)
    if not errors:
        if report["subject_sha"] != args.head_sha:
            errors.append("codebase-grounding evidence is stale for material head")
        if report["base_sha"] != args.base_sha:
            errors.append("codebase-grounding base does not match work item start")
        check_creations(report, repo, args.base_sha, args.head_sha, errors)
        check_references(report, repo, args.head_sha, errors)
        check_replacements(report, repo, args.head_sha, errors)
    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print(f"READY: codebase grounding verified at {args.head_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
