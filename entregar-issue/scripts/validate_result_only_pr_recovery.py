#!/usr/bin/env python3
"""Validate whether a stale result-only handoff can be replaced in the same PR.

This guard deliberately authorizes only ref replacement between sibling
result-only children of the same immutable material head. It never authorizes
rewriting material history.
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact

SHA40 = re.compile(r"^[0-9a-f]{40}$", re.I)
CERT_PATH = ".audit/entregar-issue/handoff-ready.json"
SUBJECT_KEYS = (
    "repository",
    "issue_number",
    "pull_request_number",
    "work_item_kind",
    "work_item_number",
    "pull_request",
    "base_ref",
    "head_ref",
)


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def norm(value: str) -> str:
    raw = value.replace("\\", "/").strip()
    normalized = posixpath.normpath(raw)
    if not raw or raw.startswith("/") or normalized in {".", ".."} or normalized.startswith("../"):
        raise ValueError(f"invalid repository-relative path: {value!r}")
    return normalized


def policy(cert: dict) -> tuple[str, set[str]]:
    raw = cert.get("certificate_commit_policy") or {}
    mode = str(raw.get("mode") or "")
    allowed = {norm(str(path)) for path in raw.get("allowed_paths") or []}
    return mode, allowed


def material(cert: dict) -> str:
    identity = cert.get("identity") or {}
    return str(identity.get("material_head_sha") or identity.get("head_sha") or "")


def emit(status: str, strategy: str, reason: str, **extra: object) -> int:
    payload = {"status": status, "strategy": strategy, "reason": reason, **extra}
    print(json.dumps(payload, sort_keys=True))
    return 0 if status == "ready" else 3 if status == "replacement-required" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-certificate", required=True)
    parser.add_argument("--candidate-certificate", required=True)
    parser.add_argument("--current-head-sha", required=True)
    parser.add_argument("--current-parent-sha", required=True)
    parser.add_argument("--current-changed-path", action="append", default=[])
    parser.add_argument("--candidate-parent-sha", required=True)
    parser.add_argument("--candidate-changed-path", action="append", default=[])
    parser.add_argument("--pr-state", choices=("open", "closed", "merged"), required=True)
    parser.add_argument("--certificate-repo-path", default=CERT_PATH)
    args = parser.parse_args()

    try:
        current_cert = load(Path(args.current_certificate))
        candidate_cert = load(Path(args.candidate_certificate))
        cert_path = norm(args.certificate_repo_path)
        current_paths = {norm(str(path)) for path in args.current_changed_path if str(path).strip()}
        candidate_paths = {norm(str(path)) for path in args.candidate_changed_path if str(path).strip()}
    except Exception as exc:
        print(f"BLOCK: invalid result-only recovery input: {exc}")
        return 2

    if args.pr_state != "open":
        return emit(
            "replacement-required",
            "replacement-pr-last-resort",
            f"original-pr-{args.pr_state}",
            replacement_pr_budget=1,
        )

    values = (args.current_head_sha, args.current_parent_sha, args.candidate_parent_sha)
    if not all(SHA40.fullmatch(value) for value in values):
        print("BLOCK: invalid current/candidate SHA")
        return 2

    current_material = material(current_cert)
    candidate_material = material(candidate_cert)
    if not SHA40.fullmatch(current_material) or not SHA40.fullmatch(candidate_material):
        print("BLOCK: invalid material SHA in certificate")
        return 2
    if current_material != candidate_material:
        return emit(
            "blocked",
            "same-pr-normal-recovery",
            "candidate-material-differs-from-current-certificate",
        )

    current_mode, current_allowed = policy(current_cert)
    candidate_mode, candidate_allowed = policy(candidate_cert)
    if current_mode != "result-only-child" or candidate_mode != "result-only-child":
        return emit("blocked", "same-pr-normal-recovery", "non-result-only-certificate")

    current_subject = current_cert.get("subject") or {}
    candidate_subject = candidate_cert.get("subject") or {}
    for key in SUBJECT_KEYS:
        if current_subject.get(key) != candidate_subject.get(key):
            return emit("blocked", "same-pr-normal-recovery", f"subject-drift:{key}")

    if args.current_head_sha == current_material:
        if args.candidate_parent_sha != current_material:
            return emit("blocked", "same-pr-normal-recovery", "candidate-parent-differs-from-material")
        if not candidate_paths or cert_path not in candidate_paths:
            return emit("blocked", "same-pr-normal-recovery", "candidate-missing-certificate-change")
        material_paths = sorted(candidate_paths - candidate_allowed)
        if material_paths:
            return emit(
                "blocked",
                "same-pr-normal-recovery",
                "candidate-contains-material-paths",
                material_paths=material_paths,
            )
        return emit(
            "ready",
            "publish-in-original-pr",
            "original-branch-still-at-material-head",
            material_head_sha=current_material,
            requires_force_ref_update=False,
            requires_prepublication_terminal_simulation=True,
        )

    if args.current_parent_sha != current_material:
        return emit(
            "blocked",
            "same-pr-normal-recovery",
            "current-head-is-not-direct-result-only-child",
        )
    if not current_paths or cert_path not in current_paths:
        return emit(
            "blocked",
            "same-pr-normal-recovery",
            "current-child-incomplete-or-missing-certificate",
        )
    current_material_paths = sorted(current_paths - current_allowed)
    if current_material_paths:
        return emit(
            "blocked",
            "same-pr-normal-recovery",
            "current-child-contains-material-paths",
            material_paths=current_material_paths,
        )

    if args.candidate_parent_sha != current_material:
        return emit("blocked", "same-pr-normal-recovery", "candidate-parent-differs-from-material")
    if not candidate_paths or cert_path not in candidate_paths:
        return emit("blocked", "same-pr-normal-recovery", "candidate-missing-certificate-change")
    candidate_material_paths = sorted(candidate_paths - candidate_allowed)
    if candidate_material_paths:
        return emit(
            "blocked",
            "same-pr-normal-recovery",
            "candidate-contains-material-paths",
            material_paths=candidate_material_paths,
        )

    return emit(
        "ready",
        "replace-result-only-child-in-original-pr",
        "sibling-result-only-children-share-material-parent",
        material_head_sha=current_material,
        expected_remote_head_sha=args.current_head_sha,
        requires_force_ref_update=True,
        force_scope="branch-ref-only",
        requires_prepublication_terminal_simulation=True,
        replacement_pr_budget=0,
    )


if __name__ == "__main__":
    raise SystemExit(main())
