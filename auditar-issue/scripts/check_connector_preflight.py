#!/usr/bin/env python3
"""Connector-native preflight for immutable GitHub snapshots when raw bytes cannot be mounted.

This is a fallback, not a replacement for check_delivery_preflight.py. It validates that
connector-derived semantic observations are bound to immutable Git object identities and
to the same result-only delivery snapshot described by the handoff certificate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact
from handoff_origin import connector_origin_is_same_base_blob, subject_matches_target

SHA40 = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
REQUIRED_ARTIFACTS = {"specification_snapshot", "requirement_closure"}
CANONICAL_RISKS = {
    "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
    "temporal-consistency", "temporal-destination", "concurrency-atomicity",
    "idempotency", "rollback", "historical-immutability", "structural-contract", "documentation",
}


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
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


def require_bool(semantic: dict, key: str, label: str, errors: list[str]) -> None:
    if semantic.get(key) is not True:
        errors.append(f"{label} semantic proof lacks {key}=true")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--connector-manifest", required=True)
    parser.add_argument("--contract-version", required=True)
    args = parser.parse_args()

    try:
        cert = load(Path(args.certificate))
        manifest = load(Path(args.connector_manifest))
    except Exception as exc:
        print(f"BLOCK: invalid connector preflight input: {exc}")
        return 2

    errors: list[str] = []
    recovery = "handoff-only"
    target_mismatch = False
    limitations: list[str] = []
    semantic_by_key: dict[str, dict] = {}

    if cert.get("schema_version") not in {1, 2} or cert.get("status") != "ready":
        errors.append("handoff certificate is not ready schema v1/v2")
    if cert.get("contract_version") != args.contract_version:
        errors.append("certificate contract_version differs from auditor contract")
    producer = cert.get("producer") or {}
    if producer.get("skill") != "entregar-issue" or len(str(producer.get("skill_sha256") or "")) != 64:
        errors.append("certificate lacks delivery skill provenance")

    identity = cert.get("identity") or {}
    material_head = identity.get("material_head_sha") or identity.get("head_sha")
    if not material_head or not SHA40.fullmatch(str(material_head)):
        errors.append("certificate lacks valid material head identity")

    published_head = str(manifest.get("published_head_sha") or "")
    base_sha = str(manifest.get("base_sha") or "")
    candidate_parent = str(manifest.get("candidate_parent_sha") or "")
    published_tree = str(manifest.get("published_tree_sha") or "")
    if not SHA40.fullmatch(published_head):
        errors.append("connector manifest lacks valid published_head_sha")
    if not SHA40.fullmatch(base_sha):
        errors.append("connector manifest lacks valid base_sha")
    if not SHA40.fullmatch(published_tree):
        errors.append("connector manifest lacks valid published_tree_sha")
    if identity.get("base_sha") != base_sha:
        errors.append("certificate base_sha differs from connector snapshot")

    target = manifest.get("target")
    if not isinstance(target, dict):
        errors.append("connector manifest lacks semantic delivery target")
        target = {}
        target_mismatch = True
    repository = target.get("repository")
    work_item_kind = target.get("work_item_kind")
    work_item_number = target.get("work_item_number")
    issue_number = target.get("issue_number")
    pull_request_number = target.get("pull_request_number", target.get("pull_request"))
    if not isinstance(repository, str) or not repository.strip():
        errors.append("connector target lacks repository")
        target_mismatch = True
    if work_item_kind not in {"issue", "pr"}:
        errors.append("connector target lacks valid work_item_kind")
        target_mismatch = True
    if not isinstance(work_item_number, int):
        errors.append("connector target lacks integer work_item_number")
        target_mismatch = True

    subject = cert.get("subject")
    if (
        isinstance(repository, str)
        and work_item_kind in {"issue", "pr"}
        and isinstance(work_item_number, int)
        and connector_origin_is_same_base_blob(manifest)
        and not subject_matches_target(
            cert,
            repository=repository,
            work_item_kind=work_item_kind,
            work_item_number=work_item_number,
            issue_number=issue_number if isinstance(issue_number, int) else None,
            pull_request_number=pull_request_number if isinstance(pull_request_number, int) else None,
            base_ref=target.get("base_ref"),
            head_ref=target.get("head_ref"),
        )
    ):
        print(
            "BLOCK: inherited-base-artifact: handoff-ready.json has the same immutable Git blob as the base "
            "and belongs to another delivery; the current target handoff was not produced"
        )
        print("REASON: handoff-not-produced")
        print("RECOVERY: handoff-only")
        return 2
    if cert.get("schema_version") == 2:
        if not isinstance(subject, dict):
            errors.append("handoff certificate lacks semantic subject binding")
            target_mismatch = True
        else:
            expected_pull_request = pull_request_number
            if work_item_kind == "pr" and expected_pull_request is None:
                expected_pull_request = work_item_number
            expected_issue = issue_number if isinstance(issue_number, int) else (work_item_number if work_item_kind == "issue" else None)
            if work_item_kind == "pr" and expected_issue is None:
                errors.append("connector PR target lacks canonical issue_number")
                target_mismatch = True
            for field, expected in (
                ("repository", repository),
                ("work_item_kind", work_item_kind),
                ("work_item_number", work_item_number),
                ("pull_request", expected_pull_request),
            ):
                if subject.get(field) != expected:
                    errors.append(f"certificate subject {field} differs from connector target")
                    target_mismatch = True
            if "issue_number" in subject and subject.get("issue_number") != expected_issue:
                errors.append("certificate subject issue_number differs from connector target")
                target_mismatch = True
            if "pull_request_number" in subject and subject.get("pull_request_number") != expected_pull_request:
                errors.append("certificate subject pull_request_number differs from connector target")
                target_mismatch = True
            for field in ("base_ref", "head_ref"):
                expected = target.get(field)
                if expected is not None and subject.get(field) != expected:
                    errors.append(f"certificate subject {field} differs from connector target")
                    target_mismatch = True

    scope = cert.get("scope")
    manifest_scope = manifest.get("issue_scope")
    if isinstance(scope, dict):
        scope_start = str(scope.get("work_item_start_sha") or "")
        scope_head = str(scope.get("material_head_sha") or "")
        certified_paths = sorted(str(p) for p in scope.get("issue_changed_paths") or [])
        if scope_head != material_head:
            errors.append("certificate issue-local scope material head differs from certified material head")
        if scope.get("issue_delta_sha256") != issue_scope_digest(scope_start, scope_head, certified_paths):
            errors.append("certificate issue-local scope digest is invalid")
        if isinstance(manifest_scope, dict):
            if scope_start != manifest_scope.get("work_item_start_sha"):
                errors.append("certificate work_item_start_sha differs from connector issue scope")
            observed_paths = sorted(str(p) for p in manifest_scope.get("issue_changed_paths") or [])
            if certified_paths != observed_paths:
                errors.append("certificate issue_changed_paths differ from connector issue scope")
        elif manifest_scope is not None:
            errors.append("connector issue_scope must be an object")
    elif manifest_scope is not None:
        errors.append("handoff certificate lacks issue-local scope binding")

    policy = cert.get("certificate_commit_policy") or {}
    mode = policy.get("mode")
    exact_head = published_head == material_head
    changed_paths: set[str] = set()
    try:
        changed_paths = {normalize_repo_path(str(p)) for p in manifest.get("candidate_changed_paths") or []}
    except ValueError as exc:
        errors.append(str(exc))

    if mode == "result-only-child" and not exact_head:
        if candidate_parent != material_head:
            errors.append("result-only child parent differs from certified material_head_sha")
            recovery = "post-write-refreeze"
        try:
            allowed = {normalize_repo_path(str(p)) for p in policy.get("allowed_paths") or []}
        except ValueError as exc:
            errors.append(str(exc))
            allowed = set()
        if not allowed:
            errors.append("result-only child policy lacks allowed_paths")
        if not changed_paths:
            errors.append("connector manifest requires candidate changed paths")
        disallowed = sorted(changed_paths - allowed)
        if disallowed:
            errors.append("result-only child contains non-handoff paths: " + ", ".join(disallowed))
            recovery = "post-write-refreeze"
    elif mode != "result-only-child":
        if identity.get("head_sha") != published_head:
            errors.append("certificate head_sha differs from connector snapshot")

    artifacts = cert.get("artifacts") or {}
    profile = str(cert.get("evidence_profile") or "critical")
    if profile not in {"light", "standard", "critical"}:
        errors.append("certificate evidence_profile is invalid")
        profile = "critical"
    required = set(REQUIRED_ARTIFACTS)
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

    manifest_artifacts = manifest.get("artifacts") or {}
    if not isinstance(manifest_artifacts, dict):
        errors.append("connector manifest artifacts must be an object")
        manifest_artifacts = {}

    for key in sorted(required):
        cert_item = artifacts.get(key)
        remote_item = manifest_artifacts.get(key)
        if not isinstance(cert_item, dict):
            errors.append(f"certificate lacks artifact {key}")
            continue
        if not isinstance(remote_item, dict):
            errors.append(f"connector manifest lacks artifact {key}")
            continue
        expected_name = str(cert_item.get("name") or "")
        remote_path = str(remote_item.get("path") or "")
        if not remote_path.endswith("/" + expected_name) and remote_path != expected_name:
            errors.append(f"connector artifact {key} path does not match certificate name")
        blob_sha = str(remote_item.get("git_blob_sha") or "")
        size = remote_item.get("size")
        if not SHA40.fullmatch(blob_sha):
            errors.append(f"connector artifact {key} lacks immutable git_blob_sha")
        if not isinstance(size, int) or size < 0:
            errors.append(f"connector artifact {key} lacks valid byte size")
        if remote_item.get("object_type") != "blob":
            errors.append(f"connector artifact {key} is not a Git blob")
        if remote_item.get("read_scope") != "complete-searchable-object":
            limitations.append(f"connector artifact {key} was not read/searchable as a complete object")
        semantic = remote_item.get("semantic")
        if not isinstance(semantic, dict):
            errors.append(f"connector artifact {key} lacks semantic proof")
            continue
        semantic_by_key[key] = semantic

        if key in {"standard_evidence", "requirement_attack_matrix", "risk_saturation", "inherited_controls"}:
            if semantic.get("head_sha") != material_head:
                errors.append(f"connector artifact {key} head_sha differs from material head")

        if key == "standard_evidence":
            require_bool(semantic, "all_requirements_have_positive_evidence", key, errors)
            require_bool(semantic, "all_requirements_have_primary_negative_control", key, errors)
            require_bool(semantic, "all_requirements_have_regression_evidence", key, errors)
            require_bool(semantic, "critical_flags_absent", key, errors)
        elif key == "requirement_attack_matrix":
            require_bool(semantic, "uncovered_requirements_empty", key, errors)
            require_bool(semantic, "all_requirements_have_plausible_wrong_implementation", key, errors)
            require_bool(semantic, "all_positive_controls_passed_on_material_head", key, errors)
            require_bool(semantic, "all_negative_controls_passed_on_material_head", key, errors)
            require_bool(semantic, "all_regression_controls_passed_on_material_head", key, errors)
        elif key == "risk_saturation":
            require_bool(semantic, "all_canonical_families_present", key, errors)
            require_bool(semantic, "all_applicable_families_passed_with_controls", key, errors)
            require_bool(semantic, "material_families_missing_controls_empty", key, errors)
            families = set(semantic.get("canonical_families") or [])
            if families != CANONICAL_RISKS:
                errors.append("risk_saturation semantic proof canonical family set differs from auditor contract")
        elif key == "inherited_controls":
            require_bool(semantic, "unresolved_controls_empty", key, errors)
            require_bool(semantic, "all_controls_passed_on_material_head", key, errors)
            require_bool(semantic, "all_control_subject_sha_match_material_head", key, errors)
            require_bool(semantic, "all_control_narrative_sha_claims_match_material_head", key, errors)
        elif key == "audit_remediation":
            if semantic.get("candidate_head_sha") != material_head:
                errors.append("audit_remediation semantic candidate_head_sha differs from material head")
            if semantic.get("resolution_policy") != "all-actionable-items":
                errors.append("audit_remediation semantic resolution_policy is not all-actionable-items")
            require_bool(semantic, "all_actionable_items_closed", key, errors)
        elif key == "audit_source_result":
            if not str(semantic.get("rejection_id") or "").strip():
                errors.append("audit_source_result semantic rejection_id is missing")
        elif key == "audit_escape_closure":
            require_bool(semantic, "all_escapes_passed", key, errors)
            require_bool(semantic, "all_escapes_have_class", key, errors)
            require_bool(semantic, "all_escapes_have_plausible_wrong_implementation", key, errors)
            require_bool(semantic, "all_escapes_have_two_passed_siblings", key, errors)
            require_bool(semantic, "all_escapes_have_prevention_and_detection_evidence", key, errors)
            require_bool(semantic, "all_escape_revalidation_sha_claims_match_material_head", key, errors)
        elif key == "learning_closure":
            require_bool(semantic, "learning_closed", key, errors)
        elif key == "specification_snapshot":
            require_bool(semantic, "issue_and_identity_match", key, errors)
            if semantic.get("repository") != repository:
                errors.append("specification_snapshot semantic repository differs from connector target")
                target_mismatch = True
            expected_issue = issue_number if isinstance(issue_number, int) else (work_item_number if work_item_kind == "issue" else None)
            if expected_issue is not None and semantic.get("issue") != expected_issue:
                errors.append("specification_snapshot semantic issue differs from connector target")
                target_mismatch = True
        elif key == "requirement_closure":
            require_bool(semantic, "all_required_requirements_closed", key, errors)
            require_bool(semantic, "all_terminal_closure_gates_closed", key, errors)
            require_bool(semantic, "terminal_closure_gate_applicability_valid", key, errors)
            require_bool(semantic, "scope_reduction_review_passed", key, errors)
            require_bool(semantic, "pass_c_passed", key, errors)

    if cert.get("previous_independent_rejection"):
        remediation_mode = str(cert.get("remediation_mode") or "targeted-remediation")
        if remediation_mode in {"systemic-remediation", "mixed-remediation"}:
            learning_semantic = semantic_by_key.get("learning_closure") or {}
            escape_semantic = semantic_by_key.get("audit_escape_closure") or {}
            rejection_id = str(learning_semantic.get("independent_rejection_id") or "").strip()
            if not rejection_id:
                errors.append("learning_closure semantic proof lacks independent_rejection_id")
            closed_rejections = {str(item).strip() for item in escape_semantic.get("closed_independent_rejection_ids") or [] if str(item).strip()}
            if rejection_id and rejection_id not in closed_rejections:
                errors.append(f"independent rejection {rejection_id} is not represented in audit_escape_closure semantic proof")
            expected_findings = {str(item).strip() for item in learning_semantic.get("independent_rejection_finding_ids") or [] if str(item).strip()}
            closed_by_rejection = escape_semantic.get("closed_finding_ids_by_rejection") or {}
            if not isinstance(closed_by_rejection, dict):
                errors.append("audit_escape_closure semantic proof closed_finding_ids_by_rejection must be an object")
                closed_by_rejection = {}
            represented_findings = {str(item).strip() for item in closed_by_rejection.get(rejection_id, []) if str(item).strip()} if rejection_id else set()
            missing_findings = sorted(expected_findings - represented_findings)
            if missing_findings:
                errors.append(
                    f"independent rejection {rejection_id} lacks connector semantic closure for finding ids: "
                    + ", ".join(missing_findings)
                )

    if target_mismatch:
        recovery = "fresh-handoff-required"

    if limitations:
        for limitation in limitations:
            print(f"LIMITATION: {limitation}")
        return 3
    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        print(f"RECOVERY: {recovery}")
        return 2

    print(
        "READY: connector-native immutable Git snapshot and semantic delivery preflight are valid; "
        f"material head {material_head}, published head {published_head}, tree {published_tree}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
