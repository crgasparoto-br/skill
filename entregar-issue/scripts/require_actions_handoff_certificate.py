#!/usr/bin/env python3
"""Independently enforce that a collected Actions artifact is *certified*.

A successful technical collection is never interpreted as certified handoff.
The privileged publisher performs a separate trusted revalidation before writing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")


def load(directory: Path, name: str) -> dict:
    path = directory / name
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError(f"missing or unsafe certified artifact: {name}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"certified artifact must be a JSON object: {name}")
    return result


def verify(evidence: Path, event_path: Path, base_ref: str) -> None:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    head = (pr.get("head") or {}).get("sha")
    if (not SHA.fullmatch(str(head)) or (pr.get("base") or {}).get("ref") != base_ref
            or (pr.get("head") or {}).get("repo", {}).get("full_name")
            != (event.get("repository") or {}).get("full_name")):
        raise ValueError("event does not identify a same-repository exact-SHA PR")
    identity = load(evidence, "handoff-preflight.json").get("identity") or {}
    if (identity.get("material_head_sha") != head
            or identity.get("pull_request_number") != pr.get("number")
            or identity.get("repository") != event["repository"]["full_name"]):
        raise ValueError("evidence identity is not bound to this PR and SHA")
    status = load(evidence, "handoff-certification-status.json")
    if status.get("material_head_sha") != head:
        raise ValueError("certificate receipt belongs to a different material SHA")
    if status.get("status") != "certificate-generated":
        raise ValueError(f"semantic certification BLOCKED: {status.get('reason', 'unverified')}")
    if status.get("terminal_ready") is not False or status.get("certificate_published") is not False:
        raise ValueError("certificate receipt falsely claims final publication")
    cert = load(evidence, ".audit/entregar-issue/handoff-ready.json")
    subject = cert.get("subject") or {}
    if (cert.get("schema_version") != 2 or cert.get("status") != "ready"
            or (cert.get("identity") or {}).get("material_head_sha") != head
            or subject.get("repository") != identity["repository"]
            or subject.get("issue_number") != identity["issue_number"]
            or subject.get("pull_request_number") != identity["pull_request_number"]
            or subject.get("base_ref") != base_ref):
        raise ValueError("certificate body does not bind the canonical issue and material SHA")
    if (cert.get("certificate_commit_policy") or {}).get("mode") != "result-only-child":
        raise ValueError("certificate does not require result-only publication")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--base-ref", default="develop")
    args = parser.parse_args()
    try:
        verify(args.evidence_dir.resolve(), args.event, args.base_ref)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2
    print("CERTIFICATE VERIFIED: candidate prepared; trusted publication and independent audit still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
