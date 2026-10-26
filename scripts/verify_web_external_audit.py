#!/usr/bin/env python3
"""Fail-closed exact-target guard for external signed audits on GitHub-hosted runners.

This is a component, NOT a substitute for a segregated audit producer or the
trusted workflow. Existing Ed25519 verification must succeed before acceptance.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SHA = re.compile(r"[a-f0-9]{40}\Z")


def check_binding(report: dict, *, repository: str, issue: int, base_ref: str,
                  base_sha: str, head_sha: str, merge_preview_sha: str | None = None,
                  audit_context_id: str | None = None) -> list[str]:
    errors = []
    expected = {
        "repository": repository,
        "issue": issue,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "base_sha_after": base_sha,
        "head_sha": head_sha,
        "head_sha_after": head_sha,
    }
    for key, value in expected.items():
        if report.get(key) != value:
            errors.append(f"{key} does not match exact target")
    if merge_preview_sha is not None and (
        report.get("merge_preview_sha") != merge_preview_sha
        or report.get("merge_preview_sha_after") != merge_preview_sha
    ):
        errors.append("merge preview does not match exact target")
    if audit_context_id is not None and report.get("audit_context_id") != audit_context_id:
        errors.append("signed audit context does not match authenticated workflow run")
    if report.get("verdict") != "approved":
        errors.append("auditor verdict is not approved")
    for key in ("findings", "recommendations", "limitations"):
        if report.get(key) != []:
            errors.append(f"{key} must be empty for release approval")
    if report.get("independent") is not True or report.get("same_conversation") is not False:
        errors.append("independent context is not attested")
    if not report.get("audit_context_id") or (
        report.get("audit_context_id") == report.get("implementation_context_id")
    ):
        errors.append("audit and implementation contexts are not distinct")
    neutral = report.get("neutral_packet")
    if not isinstance(neutral, dict) or neutral.get("implementation_conclusions_included") is not False or neutral.get("implementation_narrative_included") is not False:
        errors.append("neutral audit packet not established")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--trusted-auditors", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--base-ref", required=True, choices=["develop", "main"])
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--merge-preview-sha")
    parser.add_argument("--audit-context-id")
    args = parser.parse_args()
    if (args.issue < 1 or not SHA.fullmatch(args.head_sha) or not SHA.fullmatch(args.base_sha)
            or (args.merge_preview_sha is not None and not SHA.fullmatch(args.merge_preview_sha))):
        parser.error("invalid issue or exact SHA")
    verifier = (Path(__file__).resolve().parents[1] / "auditar-issue" / "scripts"
                / "validate_external_audit_report.py")
    # No signature verification, no approval: never rely only on report JSON.
    verified = subprocess.run(
        [sys.executable, str(verifier), str(args.report),
         "--trusted-auditors", str(args.trusted_auditors)],
        capture_output=True, text=True, check=False,
    )
    if verified.returncode != 0:
        print("BLOCK: signed external audit verification failed", file=sys.stderr)
        return 2
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"BLOCK: unreadable report: {exc}", file=sys.stderr)
        return 2
    errors = check_binding(
        report, repository=args.repository, issue=args.issue,
        base_ref=args.base_ref, base_sha=args.base_sha, head_sha=args.head_sha,
        merge_preview_sha=args.merge_preview_sha,
        audit_context_id=args.audit_context_id,
    )
    for error in errors:
        print(f"BLOCK: {error}", file=sys.stderr)
    if errors:
        return 2
    print("READY: independent signed audit matches exact target")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
