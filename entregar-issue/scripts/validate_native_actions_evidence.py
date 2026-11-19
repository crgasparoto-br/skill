#!/usr/bin/env python3
"""Trusted native evidence gate: test facts, Git identities, issue and JUnit, not approval."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from build_test_candidate_index import collect
from handoff_merge_preview import require_equivalent_merge_previews, require_event_merge_preview
from prepare_actions_handoff import issue_body, read_event
from resolve_trusted_audit_transport import resolve

SHA = re.compile(r"[0-9a-f]{40}\Z")


def record(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError(f"required native evidence is missing: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"required native evidence must be JSON object: {path.name}")
    return value


def verify(root: Path, evidence: Path, event: Path, base_ref: str) -> dict:
    repository, number, issue, head, base = read_event(event, base_ref)
    actual = resolve(root, repository, base_ref, base, head)
    if actual["mode"] != "native-github-audit":
        raise ValueError("native evidence cannot replace required legacy certification")
    if record(evidence / "audit-transport.json") != actual:
        raise ValueError("native transport claim differs from authenticated base contract")

    body = issue_body(repository, issue, os.environ.get("GITHUB_TOKEN", ""))
    raw_body = body.encode("utf-8")
    source = evidence / "issue-body.md"
    if source.is_symlink() or not source.is_file() or source.read_bytes() != raw_body:
        raise ValueError("canonical GitHub issue body differs from technical snapshot")
    preflight = record(evidence / "handoff-preflight.json")
    identity = preflight.get("identity")
    expected = {"repository": repository, "issue_number": issue, "pull_request_number": number,
                "material_head_sha": head, "base_sha": base}
    if (not isinstance(identity, dict)
            or any(identity.get(key) != value for key, value in expected.items())
            or preflight.get("base_ref") != base_ref
            or preflight.get("source", {}).get("issue_body_sha256")
            != hashlib.sha256(raw_body).hexdigest()):
        raise ValueError("technical preflight identity or issue source differs from GitHub")

    recorded_event = record(evidence / "certification-event.json")
    recorded_pr = recorded_event.get("pull_request")
    original_event = record(event)
    event_pr = original_event.get("pull_request")
    if not isinstance(recorded_pr, dict) or not isinstance(event_pr, dict):
        raise ValueError("technical event identity is malformed")
    if recorded_event.get("repository") != {"full_name": repository}:
        raise ValueError("technical event repository differs from GitHub")
    expected_pr = {
        "number": number, "title": event_pr.get("title") or "",
        "body": event_pr.get("body") or "",
        "head": {"sha": head, "repo": {"full_name": repository}},
        "base": {"ref": base_ref, "sha": base},
    }
    if any(recorded_pr.get(key) != value for key, value in expected_pr.items()):
        raise ValueError("technical event differs from authenticated PR inputs")
    recorded_preview = recorded_pr.get("merge_commit_sha")
    if (not isinstance(recorded_preview, str) or SHA.fullmatch(recorded_preview) is None
            or identity.get("merge_preview_sha") != recorded_preview):
        raise ValueError("pre-test merge preview identity differs from GitHub")
    live_preview = require_event_merge_preview(event, repository, number, head, base)
    require_equivalent_merge_previews(repository, base, head, (recorded_preview, live_preview))

    facts = record(evidence / "test-execution-facts.json")
    execution = facts.get("execution")
    log = evidence / "pytest-exact-head.log"
    if (not isinstance(execution, dict) or facts.get("subject_sha") != head
            or facts.get("verification") != "passed"
            or execution.get("exit_code") != 0
            or not isinstance(execution.get("command"), str)
            or not execution["command"].strip()
            or execution.get("log_path") != log.name
            or log.is_symlink() or not log.is_file() or not log.stat().st_size
            or hashlib.sha256(log.read_bytes()).hexdigest() != execution.get("log_sha256")):
        raise ValueError("test execution did not pass on the exact material SHA")

    junit = evidence / "pytest-exact-head.xml"
    if junit.is_symlink() or not junit.is_file() or not junit.stat().st_size:
        raise ValueError("exact-SHA JUnit file is missing")
    xml = junit.read_bytes()
    if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
        raise ValueError("unsafe JUnit XML with document type or entity")
    index = collect(junit, head)
    if (index["counts"]["failure"] or index["counts"]["error"]
            or index["counts"]["skipped"]):
        raise ValueError("JUnit contains failed, errored or skipped controls")
    if record(evidence / "test-candidate-index.json") != index:
        raise ValueError("test candidate index differs from authentic JUnit bytes")
    return {
        "schema_version": 1,
        "status": "verified-technical-evidence",
        "audit_transport": "native-github-audit",
        "repository": repository,
        "pull_request_number": number,
        "issue_number": issue,
        "material_head_sha": head,
        "base_sha": base,
        "issue_body_sha256": hashlib.sha256(raw_body).hexdigest(),
        "test_count": index["counts"]["passed"],
        "semantic_certification": "NOT_ASSERTED",
        "independent_review": "NOT_ASSERTED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--base-ref", default="develop")
    args = parser.parse_args()
    try:
        value = verify(args.root.resolve(), args.evidence_dir.resolve(),
                       args.event, args.base_ref)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
