#!/usr/bin/env python3
"""Validate a handoff certificate, including result-only child publication and target binding."""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
from pathlib import Path

from audit_artifact_io import artifact_metadata, load_json_artifact


# Must stay equal to plan_execution.CODE_SUFFIXES; the auditor copy of this file has no planner to import.
CODE_SUFFIXES = (
    '.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.java', '.kt',
    '.go', '.rs', '.rb', '.php', '.cs', '.c', '.cc', '.cpp', '.h', '.hpp',
    '.swift', '.scala', '.sh', '.bash', '.zsh', '.ps1', '.sql', '.vue', '.svelte',
)


def scope_touches_code(paths: list[str]) -> bool:
    return any(str(path).lower().endswith(CODE_SUFFIXES) for path in paths)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def issue_scope_digest(work_item_start_sha: str, material_head_sha: str, paths: list[str]) -> str:
    payload = {
        "work_item_start_sha": work_item_start_sha,
        "material_head_sha": material_head_sha,
        "issue_changed_paths": sorted(set(paths)),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def normalize_repo_path(value: str) -> str:
    raw = value.replace("\\", "/").strip()
    normalized = posixpath.normpath(raw)
    if not raw or raw.startswith("/") or normalized in {".", ".."} or normalized.startswith("../"):
        raise ValueError(f"invalid repository-relative path: {value!r}")
    return normalized


def compare_target(label: str, observed, expected, errors: list[str]) -> bool:
    if expected is None:
        return False
    if observed != expected:
        errors.append(f"{label} differs from audit target")
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--head-sha", required=True, help="Current published candidate head SHA")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--merge-preview-sha", help="Current published candidate merge preview")
    parser.add_argument("--candidate-parent-sha")
    parser.add_argument("--candidate-changed-path", action="append", default=[])
    parser.add_argument("--contract-version")
    parser.add_argument("--repository")
    parser.add_argument("--issue-number", type=int, help="Canonical issue delivered by the audited PR")
    parser.add_argument("--work-item-kind", choices=("issue", "pr"))
    parser.add_argument("--work-item-number", type=int)
    parser.add_argument("--pull-request", type=int, help="Legacy alias for --pull-request-number")
    parser.add_argument("--pull-request-number", type=int)
    parser.add_argument("--work-item-start-sha")
    parser.add_argument("--issue-changed-path", action="append", default=[])
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    args = parser.parse_args()
    errors: list[str] = []
    recovery = "handoff-only"
    target_mismatch = False

    target_core = (args.repository, args.work_item_kind, args.work_item_number)
    target_requested = any(value is not None for value in target_core)
    if target_requested and not all(value is not None for value in target_core):
        print("BLOCK: semantic target validation requires repository, work-item-kind and work-item-number together")
        print("RECOVERY: fresh-handoff-required")
        return 2

    try:
        cert = load(Path(args.certificate))
    except Exception as exc:
        print(f"BLOCK: invalid handoff certificate: {exc}")
        return 2

    schema_version = cert.get("schema_version")
    if schema_version not in {1, 2} or cert.get("status") != "ready":
        errors.append("handoff certificate is not ready schema v1/v2")

    identity = cert.get("identity") or {}
    material_head = identity.get("material_head_sha") or identity.get("head_sha")
    if not material_head:
        errors.append("certificate lacks material head identity")
    if identity.get("base_sha") != args.base_sha:
        errors.append("certificate base_sha differs from candidate")

    policy = cert.get("certificate_commit_policy") or {}
    mode = policy.get("mode")
    exact_head = args.head_sha == material_head

    if mode == "result-only-child":
        if exact_head:
            material_merge = identity.get("material_merge_preview_sha") or identity.get("merge_preview_sha")
            if args.merge_preview_sha is not None and material_merge != args.merge_preview_sha:
                errors.append("certificate material merge_preview_sha differs from candidate")
        else:
            if args.candidate_parent_sha != material_head:
                errors.append("result-only child parent differs from certified material_head_sha")
                recovery = "post-write-refreeze"
            try:
                allowed = {normalize_repo_path(str(p)) for p in policy.get("allowed_paths", [])}
                changed = {normalize_repo_path(str(p)) for p in args.candidate_changed_path}
            except ValueError as exc:
                errors.append(str(exc))
                allowed = set()
                changed = set()
            if not allowed:
                errors.append("result-only child policy lacks allowed_paths")
            if not changed:
                errors.append("result-only child validation requires candidate changed paths")
            disallowed = sorted(changed - allowed)
            if disallowed:
                errors.append("result-only child contains non-handoff paths: " + ", ".join(disallowed))
                recovery = "post-write-refreeze"
    else:
        if identity.get("head_sha") != args.head_sha:
            errors.append("certificate head_sha differs from candidate")
        if args.merge_preview_sha is not None and identity.get("merge_preview_sha") != args.merge_preview_sha:
            errors.append("certificate merge_preview_sha differs from candidate")

    if args.contract_version and cert.get("contract_version") != args.contract_version:
        errors.append("certificate contract_version differs from auditor contract")
    producer = cert.get("producer") or {}
    if producer.get("skill") != "entregar-issue" or len(str(producer.get("skill_sha256") or "")) != 64:
        errors.append("certificate lacks delivery skill provenance")

    artifacts_dir = Path(args.artifacts_dir).resolve()
    artifacts = cert.get("artifacts") or {}
    profile = str(cert.get("evidence_profile") or "critical")
    if profile not in {"light", "standard", "critical"}:
        errors.append("certificate evidence_profile is invalid")
        profile = "critical"
    required = {"specification_snapshot", "requirement_closure"}
    if profile == "standard":
        required.add("standard_evidence")
    elif profile == "critical":
        required.update({"requirement_attack_matrix", "risk_saturation", "inherited_controls"})
    if cert.get("previous_independent_rejection"):
        required.update({"audit_remediation", "audit_source_result"})
        remediation_mode=str(cert.get("remediation_mode") or "targeted-remediation")
        if remediation_mode in {"systemic-remediation", "mixed-remediation"}:
            if profile != "critical": errors.append("systemic audit remediation requires critical evidence profile")
            required.update({"audit_escape_closure", "learning_closure", "inherited_controls"})
    declared_optional = {"evidence_provenance", "code_growth", "codebase_grounding"} & set(artifacts)
    certified_scope = cert.get("scope") if isinstance(cert.get("scope"), dict) else {}
    code_scope = scope_touches_code(certified_scope.get("issue_changed_paths") or [])
    for key in ("codebase_grounding", "code_growth"):
        control = (cert.get("controls") or {}).get(key) or {}
        if code_scope and control.get("applicable") is not True:
            errors.append(f"certificate omits {key} control although issue-local scope touches code")
        if control.get("applicable") is True:
            required.add(key)
    artifact_paths: dict[str, Path] = {}
    for key in sorted(required | declared_optional):
        item = artifacts.get(key)
        if not isinstance(item, dict):
            errors.append(f"certificate lacks artifact {key}")
            continue
        path = artifacts_dir / str(item.get("name") or "")
        artifact_paths[key] = path
        if not path.is_file():
            errors.append(f"certified artifact {key} is missing")
            continue
        try:
            meta = artifact_metadata(path)
        except Exception as exc:
            errors.append(f"certified artifact {key} transport validation failed: {exc}")
            continue
        if meta.get("sha256") != item.get("sha256"):
            errors.append(f"certified artifact {key} hash mismatch")
        expected_logical = item.get("logical_sha256")
        if expected_logical and meta.get("logical_sha256") != expected_logical:
            errors.append(f"certified artifact {key} logical hash mismatch")
        declared_transport = item.get("artifact_transport")
        if isinstance(declared_transport, dict):
            actual_transport = meta.get("artifact_transport") or {}
            if declared_transport.get("format") != actual_transport.get("format"):
                errors.append(f"certified artifact {key} transport format mismatch")
            if declared_transport.get("format") == "base64-shards-v1":
                for field in ("compression", "encoded_size", "decoded_size", "decoded_sha256"):
                    if declared_transport.get(field) != actual_transport.get(field):
                        errors.append(f"certified artifact {key} transport {field} mismatch")

    if target_requested:
        expected_issue_number = args.issue_number if args.issue_number is not None else (args.work_item_number if args.work_item_kind == "issue" else None)
        expected_pull_request = args.pull_request_number if args.pull_request_number is not None else args.pull_request
        if args.work_item_kind == "pr" and expected_pull_request is None:
            expected_pull_request = args.work_item_number
        if args.work_item_kind == "pr" and expected_issue_number is None:
            errors.append("audit PR target requires canonical issue-number; PR number must not substitute for issue number")
            target_mismatch = True

        subject = cert.get("subject")
        if schema_version == 2:
            if not isinstance(subject, dict):
                errors.append("handoff certificate lacks semantic subject binding")
                target_mismatch = True
            else:
                target_mismatch |= compare_target("certificate subject repository", subject.get("repository"), args.repository, errors)
                target_mismatch |= compare_target("certificate subject work_item_kind", subject.get("work_item_kind"), args.work_item_kind, errors)
                target_mismatch |= compare_target("certificate subject work_item_number", subject.get("work_item_number"), args.work_item_number, errors)
                target_mismatch |= compare_target("certificate subject pull_request", subject.get("pull_request"), expected_pull_request, errors)
                if "issue_number" in subject:
                    target_mismatch |= compare_target("certificate subject issue_number", subject.get("issue_number"), expected_issue_number, errors)
                if "pull_request_number" in subject:
                    target_mismatch |= compare_target("certificate subject pull_request_number", subject.get("pull_request_number"), expected_pull_request, errors)
                if args.base_ref is not None:
                    target_mismatch |= compare_target("certificate subject base_ref", subject.get("base_ref"), args.base_ref, errors)
                if args.head_ref is not None:
                    target_mismatch |= compare_target("certificate subject head_ref", subject.get("head_ref"), args.head_ref, errors)
        elif isinstance(subject, dict):
            target_mismatch |= compare_target("certificate subject repository", subject.get("repository"), args.repository, errors)
            target_mismatch |= compare_target("certificate subject work_item_kind", subject.get("work_item_kind"), args.work_item_kind, errors)
            target_mismatch |= compare_target("certificate subject work_item_number", subject.get("work_item_number"), args.work_item_number, errors)

        snapshot_path = artifact_paths.get("specification_snapshot")
        if snapshot_path is None or not snapshot_path.is_file():
            errors.append("cannot validate delivery target without specification snapshot")
            target_mismatch = True
        else:
            try:
                snapshot = load(snapshot_path)
            except Exception as exc:
                errors.append(f"cannot read specification snapshot for target validation: {exc}")
                target_mismatch = True
            else:
                target_mismatch |= compare_target("specification snapshot repository", snapshot.get("repository"), args.repository, errors)
                if expected_issue_number is not None:
                    target_mismatch |= compare_target("specification snapshot issue", snapshot.get("issue"), expected_issue_number, errors)

    for key in ("codebase_grounding", "code_growth"):
        if key not in artifact_paths or not artifact_paths[key].is_file():
            continue
        label = key.replace("_", " ")
        try:
            report = load(artifact_paths[key])
        except Exception as exc:
            errors.append(f"cannot read certified {label}: {exc}")
            continue
        if report.get("subject_sha") != material_head:
            errors.append(f"certified {label} is stale for material head")
        if key == "code_growth" and (report.get("status") != "passed" or report.get("blocking_files")):
            errors.append("certified CODE-GROWTH-001 did not pass")

    scope = cert.get("scope")
    if isinstance(scope, dict):
        scope_start = str(scope.get("work_item_start_sha") or "")
        scope_head = str(scope.get("material_head_sha") or "")
        scope_paths = sorted({str(p) for p in scope.get("issue_changed_paths") or []})
        scope_digest = str(scope.get("issue_delta_sha256") or "")
        if scope_head != material_head:
            errors.append("certificate issue-local scope material head differs from certified material head")
        if scope_digest != issue_scope_digest(scope_start, scope_head, scope_paths):
            errors.append("certificate issue-local scope digest is invalid")
        if args.work_item_start_sha is not None and scope_start != args.work_item_start_sha:
            errors.append("certificate work_item_start_sha differs from observed issue-local scope")
        if args.issue_changed_path:
            try:
                observed_issue_paths = sorted({normalize_repo_path(str(p)) for p in args.issue_changed_path})
                certified_issue_paths = sorted({normalize_repo_path(str(p)) for p in scope_paths})
            except ValueError as exc:
                errors.append(str(exc))
            else:
                if observed_issue_paths != certified_issue_paths:
                    errors.append("certificate issue_changed_paths differ from observed work-item delta")
    elif args.work_item_start_sha is not None or args.issue_changed_path:
        errors.append("handoff certificate lacks issue-local scope binding")

    if target_mismatch:
        recovery = "fresh-handoff-required"

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        print(f"RECOVERY: {recovery}")
        return 2
    if mode == "result-only-child" and not exact_head:
        print(f"READY: result-only handoff child is bound to material head {material_head}")
    else:
        print("READY: handoff certificate matches candidate identity, target and artifact hashes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
