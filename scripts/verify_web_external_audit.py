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
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
SOLO_ASSURANCE_MODE = "single-operator-separate-context"


def check_binding(report: dict, *, repository: str, issue: int, base_ref: str,
                  base_sha: str, head_sha: str, merge_preview_sha: str | None = None,
                  audit_context_id: str | None = None,
                  context_proof_issuer: str | None = None,
                  solo_only: bool = False,
                  expected_pull_request: int | None = None,
                  expected_issue_body_sha256: str | None = None,
                  configured_operator_id: int | None = None,
                  configured_key_id: str | None = None,
                  authenticated_comment_author_id: int | None = None) -> list[str]:
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
    if solo_only:
        if merge_preview_sha is None:
            errors.append("solo exact target requires an expected merge preview SHA")
        if report.get("assurance_mode") != SOLO_ASSURANCE_MODE:
            errors.append("solo assurance mode is not attested")
        if report.get("independent") is not False:
            errors.append("solo assurance mode must set independent=false")
        if report.get("same_conversation") is not False:
            errors.append("solo assurance mode must set same_conversation=false")
        if type(expected_pull_request) is not int or expected_pull_request < 1:
            errors.append("expected pull-request ID is not a positive integer")
        else:
            report_pull_request = report.get("pull_request")
            if type(report_pull_request) is not int or report_pull_request != expected_pull_request:
                errors.append("pull request does not match exact target")
        if not isinstance(expected_issue_body_sha256, str) or not SHA256.fullmatch(expected_issue_body_sha256):
            errors.append("expected issue-body SHA-256 is not lowercase hexadecimal")
        elif report.get("issue_body_sha256") != expected_issue_body_sha256:
            errors.append("issue body hash does not match exact target")
        if type(configured_operator_id) is not int or configured_operator_id < 1:
            errors.append("configured operator ID is not a positive integer")
        else:
            report_operator_id = report.get("operator_github_id")
            if type(report_operator_id) is not int or report_operator_id != configured_operator_id:
                errors.append("report operator ID does not match configured operator")
            if (type(authenticated_comment_author_id) is not int
                    or authenticated_comment_author_id < 1
                    or authenticated_comment_author_id != configured_operator_id):
                errors.append("authenticated comment author does not match configured operator")
        if not isinstance(configured_key_id, str) or not configured_key_id:
            errors.append("configured signing key ID is missing")
        else:
            signature = report.get("signature")
            if not isinstance(signature, dict) or signature.get("key_id") != configured_key_id:
                errors.append("signed report key ID does not match configured key")
    if audit_context_id is not None and report.get("audit_context_id") != audit_context_id:
        errors.append("signed audit context does not match authenticated workflow run")
    proof = report.get("source_context_proof")
    if not isinstance(proof, dict):
        errors.append("source context proof is missing")
    else:
        if proof.get("value") != report.get("audit_context_id"):
            errors.append("source context proof does not bind the audit context")
        if context_proof_issuer is not None and proof.get("issuer") != context_proof_issuer:
            errors.append("source context proof issuer is not independently authenticated")
    if report.get("verdict") != "approved":
        errors.append("auditor verdict is not approved")
    for key in ("findings", "recommendations", "limitations"):
        if report.get(key) != []:
            errors.append(f"{key} must be empty for release approval")
    if solo_only:
        if not report.get("audit_context_id") or report.get("audit_context_id") == report.get("implementation_context_id"):
            errors.append("solo audit and implementation contexts are not distinct")
    else:
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
    parser.add_argument("--context-proof-issuer")
    parser.add_argument(
        "--solo-only", "--require-solo", "--solo",
        dest="solo_only", action="store_true",
    )
    parser.add_argument("--expected-pull-request", "--pull-request", dest="expected_pull_request", type=int)
    parser.add_argument(
        "--expected-issue-body-sha256", "--issue-body-sha256",
        dest="expected_issue_body_sha256",
    )
    parser.add_argument(
        "--configured-operator-id", "--operator-github-id", "--solo-operator-id",
        dest="configured_operator_id", type=int,
    )
    parser.add_argument(
        "--configured-key-id", "--key-id", "--solo-key-id",
        dest="configured_key_id",
    )
    parser.add_argument(
        "--authenticated-comment-author-id", "--comment-author-id",
        dest="authenticated_comment_author_id", type=int,
    )
    args = parser.parse_args()
    solo_inputs = (
        args.expected_pull_request, args.expected_issue_body_sha256,
        args.configured_operator_id, args.configured_key_id,
        args.authenticated_comment_author_id,
    )
    if args.solo_only:
        if any(value is None for value in solo_inputs):
            parser.error("--solo-only requires all expected pull-request, issue-body hash, operator, key, and comment-author inputs")
    elif any(value is not None for value in solo_inputs):
        parser.error("solo binding inputs require --solo-only")
    if (args.issue < 1 or not SHA.fullmatch(args.head_sha) or not SHA.fullmatch(args.base_sha)
            or (args.merge_preview_sha is not None and not SHA.fullmatch(args.merge_preview_sha))):
        parser.error("invalid issue or exact SHA")
    if args.solo_only and (
        args.merge_preview_sha is None
        or
        args.expected_pull_request < 1
        or args.configured_operator_id < 1
        or not isinstance(args.expected_issue_body_sha256, str)
        or not SHA256.fullmatch(args.expected_issue_body_sha256)
    ):
        parser.error("invalid solo pull-request, operator ID, or issue-body SHA-256")
    verifier = (Path(__file__).resolve().parents[1] / "auditar-issue" / "scripts"
                / "validate_external_audit_report.py")
    # No signature verification, no approval: never rely only on report JSON.
    verified = subprocess.run(
        [sys.executable, str(verifier), str(args.report),
         "--trusted-auditors", str(args.trusted_auditors)]
        + (["--exact-repository-only"] if args.solo_only else []),
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
        context_proof_issuer=args.context_proof_issuer,
        solo_only=args.solo_only,
        expected_pull_request=args.expected_pull_request,
        expected_issue_body_sha256=args.expected_issue_body_sha256,
        configured_operator_id=args.configured_operator_id,
        configured_key_id=args.configured_key_id,
        authenticated_comment_author_id=args.authenticated_comment_author_id,
    )
    for error in errors:
        print(f"BLOCK: {error}", file=sys.stderr)
    if errors:
        return 2
    if args.solo_only:
        print("READY: solo-context signed attestation matches exact target — no third-party human approval claimed")
    else:
        print("READY: independent signed audit matches exact target")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
