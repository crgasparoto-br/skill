#!/usr/bin/env python3
"""Derive factual test-case candidates from JUnit without asserting requirement coverage."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

HEX_SHA = re.compile(r"[0-9a-f]{40}\Z")


def collect(junit: Path, head_sha: str) -> dict:
    if not HEX_SHA.fullmatch(head_sha):
        raise ValueError("exact 40-character material SHA is required")
    if not junit.is_file() or junit.is_symlink() or not junit.stat().st_size:
        raise ValueError("nonempty, regular JUnit source is required")
    raw = junit.read_bytes()
    xml = ET.fromstring(raw)
    if xml.tag not in {"testsuite", "testsuites"}:
        raise ValueError("JUnit root must be testsuite or testsuites")
    tests = []
    ids = set()
    for case in xml.iter("testcase"):
        name = case.get("name") or ""
        suite = case.get("classname") or ""
        if not name.strip() or not suite.strip():
            raise ValueError("JUnit testcase must carry name and classname")
        identity = f"{suite}::{name}"
        if identity in ids:
            raise ValueError("duplicate testcase identity; cannot prove unique control")
        ids.add(identity)
        statuses = [s.tag for s in case if s.tag in {"failure", "error", "skipped"}]
        status = statuses[0] if statuses else "passed"
        tests.append({"id": identity, "status": status})
    if not tests:
        raise ValueError("empty JUnit report cannot prove a test run")
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("JUnit input exceeds bounded index size")
    return {
        "schema_version": 1, "subject_sha": head_sha,
        "source": {"name": junit.name, "sha256": hashlib.sha256(raw).hexdigest()},
        "tests": sorted(tests, key=lambda x: x["id"]),
        "counts": {status: sum(item["status"] == status for item in tests)
                   for status in ("passed", "failure", "error", "skipped")},
        "requirement_mapping": "UNKNOWN",
        "certification": "NOT_ASSERTED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--junit", type=Path, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        output = collect(args.junit, args.head_sha)
    except (ValueError, ET.ParseError, OSError) as error:
        print(f"BLOCK: no trustworthy JUnit candidate index: {error}")
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(output['tests'])} exact-SHA test candidates; semantic mapping UNKNOWN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
