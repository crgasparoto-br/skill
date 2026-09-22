#!/usr/bin/env python3
"""Fail closed when CI remediation would return success with a stale delivery handoff.

This is an outer safety latch for corrigir-ci whenever a governed handoff was
observed during the invocation. It does not replace entregar-issue's terminal handoff
validator. Instead, it verifies from freshly re-read remote commit metadata that the
final remote head is the direct result-only child of the exact material SHA that the
CI loop considers green, regardless of which actor published intervening commits.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
from pathlib import Path

from handoff_target_binding import classify_handoff_subject

SHA40 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
DEFAULT_CERT_REPO_PATH = ".audit/entregar-issue/handoff-ready.json"


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def normalize_repo_path(value: str) -> str:
    raw = value.replace("\\", "/").strip()
    normalized = posixpath.normpath(raw)
    if not raw or raw.startswith("/") or normalized in {".", ".."} or normalized.startswith("../"):
        raise ValueError(f"invalid repository-relative path: {value!r}")
    return normalized


def valid_sha(value: str) -> bool:
    return bool(SHA40.fullmatch(value))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--expected-material-head-sha", required=True)
    parser.add_argument("--current-head-sha", required=True)
    parser.add_argument("--current-parent-sha", required=True)
    parser.add_argument("--current-changed-path", action="append", default=[])
    parser.add_argument("--certificate-repo-path", default=DEFAULT_CERT_REPO_PATH)
    parser.add_argument("--contract-version")
    parser.add_argument("--repository")
    parser.add_argument("--work-item-kind", choices=("issue", "pr"))
    parser.add_argument("--work-item-number", type=int)
    parser.add_argument("--pull-request", type=int)
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    args = parser.parse_args()

    errors: list[str] = []
    recovery = "handoff-recertification"
    try:
        cert = load(Path(args.certificate))
    except Exception as exc:
        print(f"BLOCK: invalid handoff certificate: {exc}")
        return 2

    expected_material = str(args.expected_material_head_sha or "")
    current_head = str(args.current_head_sha or "")
    current_parent = str(args.current_parent_sha or "")
    for label, value in (
        ("expected material head", expected_material),
        ("current head", current_head),
        ("current parent", current_parent),
    ):
        if not valid_sha(value):
            errors.append(f"{label} is not a valid commit SHA")

    if cert.get("schema_version") != 2 or cert.get("status") != "ready":
        errors.append("handoff certificate is not ready schema v2")

    if args.contract_version and cert.get("contract_version") != args.contract_version:
        errors.append("handoff certificate contract_version differs from expected contract")

    if args.repository:
        target = classify_handoff_subject(
            cert,
            repository=args.repository,
            work_item_kind=args.work_item_kind,
            work_item_number=args.work_item_number,
            pull_request=args.pull_request,
            base_ref=args.base_ref,
            head_ref=args.head_ref,
        )
        if not target["applicable"]:
            errors.append("handoff certificate is not bound to the current CI target: " + "; ".join(target["reasons"]))
            recovery = "fresh-handoff-required"

    identity = cert.get("identity") or {}
    certified_material = str(identity.get("material_head_sha") or identity.get("head_sha") or "")
    if certified_material != expected_material:
        errors.append("handoff certificate material_head_sha differs from CI-fixed material head")
        recovery = "post-write-refreeze"

    policy = cert.get("certificate_commit_policy") or {}
    if policy.get("mode") != "result-only-child":
        errors.append("governed CI success requires result-only-child handoff policy")

    if current_head == expected_material:
        errors.append("current remote head is still the material head; terminal handoff child is missing")
        if certified_material == expected_material:
            recovery = "handoff-only"
    elif current_parent != expected_material:
        errors.append("current remote head is not a direct child of the CI-fixed material head")
        recovery = "post-write-refreeze"

    try:
        allowed = {normalize_repo_path(str(path)) for path in policy.get("allowed_paths") or []}
        changed = {normalize_repo_path(str(path)) for path in args.current_changed_path if str(path).strip()}
        certificate_repo_path = normalize_repo_path(args.certificate_repo_path)
    except ValueError as exc:
        errors.append(str(exc))
        allowed = set()
        changed = set()
        certificate_repo_path = DEFAULT_CERT_REPO_PATH

    if not allowed:
        errors.append("result-only-child policy lacks allowed_paths")
    if not changed:
        errors.append("current terminal commit changed paths were not supplied")
    if certificate_repo_path not in changed:
        errors.append("current terminal commit does not publish handoff-ready.json")
    disallowed = sorted(changed - allowed)
    if disallowed:
        errors.append("current terminal commit contains non-handoff paths: " + ", ".join(disallowed))
        recovery = "post-write-refreeze"

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        print(f"RECOVERY: {recovery}")
        return 2

    print(
        "READY: CI remediation terminal state is bound to material head "
        f"{expected_material} via result-only child {current_head}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
