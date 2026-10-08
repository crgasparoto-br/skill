from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_connector_preflight.py"
MATERIAL = "a" * 40
PUBLISHED = "b" * 40
BASE = "c" * 40
TREE = "d" * 40
REPOSITORY = "example/repo"
WORK_ITEM_KIND = "issue"
WORK_ITEM_NUMBER = 123
PULL_REQUEST = 456
BASE_REF = "develop"
HEAD_REF = "feature/123"
CANONICAL = [
    "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
    "temporal-consistency", "temporal-destination", "concurrency-atomicity",
    "idempotency", "rollback", "historical-immutability", "structural-contract", "documentation",
]


def run(cert: Path, manifest: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--certificate", str(cert), "--connector-manifest", str(manifest),
         "--contract-version", "2026-08-20.3"],
        check=False, text=True, stdout=subprocess.PIPE,
    )


def artifact(path: str, semantic: dict):
    return {
        "path": path,
        "git_blob_sha": "e" * 40,
        "size": 123,
        "object_type": "blob",
        "read_scope": "complete-searchable-object",
        "semantic": semantic,
    }


def make(tmp: Path):
    artifacts = {
        "specification_snapshot": {"name": "specification-snapshot.json", "sha256": "1" * 64},
        "requirement_closure": {"name": "requirement-closure.json", "sha256": "2" * 64},
        "requirement_attack_matrix": {"name": "requirement-attack-matrix.json", "sha256": "3" * 64},
        "risk_saturation": {"name": "risk-saturation.json", "sha256": "4" * 64},
        "inherited_controls": {"name": "inherited-controls.json", "sha256": "5" * 64},
    }
    allowed = [f".audit/entregar-issue/{item['name']}" for item in artifacts.values()] + [".audit/entregar-issue/handoff-ready.json"]
    cert = tmp / "handoff-ready.json"
    cert.write_text(json.dumps({
        "schema_version": 2,
        "status": "ready",
        "identity": {"head_sha": MATERIAL, "material_head_sha": MATERIAL, "base_sha": BASE},
        "subject": {
            "repository": REPOSITORY,
            "issue_number": WORK_ITEM_NUMBER,
            "pull_request_number": PULL_REQUEST,
            "work_item_kind": WORK_ITEM_KIND,
            "work_item_number": WORK_ITEM_NUMBER,
            "pull_request": PULL_REQUEST,
            "base_ref": BASE_REF,
            "head_ref": HEAD_REF,
        },
        "certificate_commit_policy": {"mode": "result-only-child", "allowed_paths": allowed},
        "contract_version": "2026-08-20.3",
        "producer": {"skill": "entregar-issue", "skill_sha256": "f" * 64},
        "artifacts": artifacts,
        "previous_independent_rejection": False,
    }), encoding="utf-8")

    apath = lambda name: f".audit/entregar-issue/{name}"
    manifest = tmp / "connector-preflight-manifest.json"
    manifest.write_text(json.dumps({
        "published_head_sha": PUBLISHED,
        "published_tree_sha": TREE,
        "base_sha": BASE,
        "candidate_parent_sha": MATERIAL,
        "candidate_changed_paths": allowed,
        "target": {
            "repository": REPOSITORY,
            "issue_number": WORK_ITEM_NUMBER,
            "pull_request_number": PULL_REQUEST,
            "work_item_kind": WORK_ITEM_KIND,
            "work_item_number": WORK_ITEM_NUMBER,
            "pull_request": PULL_REQUEST,
            "base_ref": BASE_REF,
            "head_ref": HEAD_REF,
        },
        "artifacts": {
            "specification_snapshot": artifact(apath("specification-snapshot.json"), {
                "issue_and_identity_match": True,
                "repository": REPOSITORY,
                "issue": WORK_ITEM_NUMBER,
            }),
            "requirement_closure": artifact(apath("requirement-closure.json"), {"all_required_requirements_closed": True, "all_terminal_closure_gates_closed": True, "terminal_closure_gate_applicability_valid": True, "scope_reduction_review_passed": True, "pass_c_passed": True}),
            "requirement_attack_matrix": artifact(apath("requirement-attack-matrix.json"), {
                "head_sha": MATERIAL,
                "uncovered_requirements_empty": True,
                "all_requirements_have_plausible_wrong_implementation": True,
                "all_positive_controls_passed_on_material_head": True,
                "all_negative_controls_passed_on_material_head": True,
                "all_regression_controls_passed_on_material_head": True,
            }),
            "risk_saturation": artifact(apath("risk-saturation.json"), {
                "head_sha": MATERIAL,
                "all_canonical_families_present": True,
                "canonical_families": CANONICAL,
                "all_applicable_families_passed_with_controls": True,
                "material_families_missing_controls_empty": True,
            }),
            "inherited_controls": artifact(apath("inherited-controls.json"), {
                "head_sha": MATERIAL,
                "unresolved_controls_empty": True,
                "all_controls_passed_on_material_head": True,
                "all_control_subject_sha_match_material_head": True,
                "all_control_narrative_sha_claims_match_material_head": True,
            }),
        },
    }), encoding="utf-8")
    return cert, manifest


def test_connector_preflight_accepts_immutable_snapshot():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        proc = run(cert, manifest)
        assert proc.returncode == 0, proc.stdout
        assert "connector-native immutable Git snapshot" in proc.stdout


def test_connector_preflight_rejects_product_path_in_result_only_child():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["candidate_changed_paths"].append("apps/api/src/product.ts")
        manifest.write_text(json.dumps(data), encoding="utf-8")
        proc = run(cert, manifest)
        assert proc.returncode == 2
        assert "non-handoff paths" in proc.stdout


def test_connector_preflight_returns_limitation_when_object_is_not_complete_searchable():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["artifacts"]["requirement_attack_matrix"]["read_scope"] = "truncated-snippet"
        manifest.write_text(json.dumps(data), encoding="utf-8")
        proc = run(cert, manifest)
        assert proc.returncode == 3
        assert "LIMITATION:" in proc.stdout


def enable_previous_rejection(cert: Path, manifest: Path, *, rejection_id: str, closed_rejection_id: str | None = None) -> None:
    cert_data = json.loads(cert.read_text(encoding="utf-8"))
    cert_data["previous_independent_rejection"] = True
    cert_data["remediation_mode"] = "systemic-remediation"
    cert_data["artifacts"]["audit_escape_closure"] = {"name": "audit-escape-closure.json", "sha256": "6" * 64}
    cert_data["artifacts"]["learning_closure"] = {"name": "learning-closure.json", "sha256": "7" * 64}
    cert_data["artifacts"]["audit_remediation"] = {"name": "audit-remediation.json", "sha256": "8" * 64}
    cert_data["artifacts"]["audit_source_result"] = {"name": "audit-source-result.json", "sha256": "9" * 64}
    for name in ("audit-escape-closure.json", "learning-closure.json", "audit-remediation.json", "audit-source-result.json"):
        path = f".audit/entregar-issue/{name}"
        if path not in cert_data["certificate_commit_policy"]["allowed_paths"]:
            cert_data["certificate_commit_policy"]["allowed_paths"].append(path)
    cert.write_text(json.dumps(cert_data), encoding="utf-8")

    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["candidate_changed_paths"] = cert_data["certificate_commit_policy"]["allowed_paths"]
    closed = closed_rejection_id or rejection_id
    manifest_data["artifacts"]["learning_closure"] = artifact(
        ".audit/entregar-issue/learning-closure.json",
        {
            "learning_closed": True,
            "independent_rejection_id": rejection_id,
            "independent_rejection_finding_ids": ["F-001", "F-002"],
        },
    )
    manifest_data["artifacts"]["audit_escape_closure"] = artifact(
        ".audit/entregar-issue/audit-escape-closure.json",
        {
            "all_escapes_passed": True,
            "all_escapes_have_class": True,
            "all_escapes_have_plausible_wrong_implementation": True,
            "all_escapes_have_two_passed_siblings": True,
            "all_escapes_have_prevention_and_detection_evidence": True,
            "all_escape_revalidation_sha_claims_match_material_head": True,
            "closed_independent_rejection_ids": [closed],
            "closed_finding_ids_by_rejection": {closed: ["F-001", "F-002"]},
        },
    )
    manifest_data["artifacts"]["audit_remediation"] = artifact(
        ".audit/entregar-issue/audit-remediation.json",
        {
            "candidate_head_sha": MATERIAL,
            "resolution_policy": "all-actionable-items",
            "all_actionable_items_closed": True,
        },
    )
    manifest_data["artifacts"]["audit_source_result"] = artifact(
        ".audit/entregar-issue/audit-source-result.json",
        {"rejection_id": rejection_id},
    )
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")


def test_connector_preflight_cross_checks_latest_independent_rejection_semantics():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        enable_previous_rejection(cert, manifest, rejection_id="audit-rejection:synthetic-001")
        proc = run(cert, manifest)
        assert proc.returncode == 0, proc.stdout


def test_connector_preflight_rejects_learning_rejection_missing_from_escape_semantics():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        enable_previous_rejection(
            cert,
            manifest,
            rejection_id="audit-rejection:synthetic-002",
            closed_rejection_id="audit-rejection:older-001",
        )
        proc = run(cert, manifest)
        assert proc.returncode == 2
        assert "is not represented in audit_escape_closure semantic proof" in proc.stdout


def test_connector_preflight_rejects_pending_terminal_requirement_closure_semantics():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["artifacts"]["requirement_closure"]["semantic"]["all_terminal_closure_gates_closed"] = False
        manifest.write_text(json.dumps(data), encoding="utf-8")
        proc = run(cert, manifest)
        assert proc.returncode == 2
        assert "all_terminal_closure_gates_closed=true" in proc.stdout


def test_connector_preflight_rejects_stale_inherited_control_narrative_semantics():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["artifacts"]["inherited_controls"]["semantic"]["all_control_narrative_sha_claims_match_material_head"] = False
        manifest.write_text(json.dumps(data), encoding="utf-8")
        proc = run(cert, manifest)
        assert proc.returncode == 2
        assert "all_control_narrative_sha_claims_match_material_head=true" in proc.stdout


def test_connector_preflight_rejects_unjustified_terminal_gate_applicability_semantics():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["artifacts"]["requirement_closure"]["semantic"]["terminal_closure_gate_applicability_valid"] = False
        manifest.write_text(json.dumps(data), encoding="utf-8")
        proc = run(cert, manifest)
        assert proc.returncode == 2
        assert "terminal_closure_gate_applicability_valid=true" in proc.stdout


def test_connector_preflight_rejects_inherited_control_subject_sha_mismatch_semantics():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["artifacts"]["inherited_controls"]["semantic"]["all_control_subject_sha_match_material_head"] = False
        manifest.write_text(json.dumps(data), encoding="utf-8")
        proc = run(cert, manifest)
        assert proc.returncode == 2
        assert "all_control_subject_sha_match_material_head=true" in proc.stdout


def test_connector_preflight_rejects_foreign_target_subject_before_audit():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        data = json.loads(cert.read_text(encoding="utf-8"))
        data["subject"]["work_item_number"] = WORK_ITEM_NUMBER + 1
        cert.write_text(json.dumps(data), encoding="utf-8")
        proc = run(cert, manifest)
        assert proc.returncode == 2
        assert "certificate subject work_item_number differs from connector target" in proc.stdout
        assert "RECOVERY: fresh-handoff-required" in proc.stdout


def test_connector_preflight_rejects_foreign_specification_snapshot_semantics():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["artifacts"]["specification_snapshot"]["semantic"]["issue"] = WORK_ITEM_NUMBER + 1
        manifest.write_text(json.dumps(data), encoding="utf-8")
        proc = run(cert, manifest)
        assert proc.returncode == 2
        assert "specification_snapshot semantic issue differs from connector target" in proc.stdout
        assert "RECOVERY: fresh-handoff-required" in proc.stdout


def test_connector_preflight_classifies_foreign_same_base_blob_as_not_produced():
    with tempfile.TemporaryDirectory() as d:
        cert, manifest = make(Path(d))
        cert_data = json.loads(cert.read_text(encoding="utf-8"))
        cert_data["subject"]["work_item_number"] = WORK_ITEM_NUMBER + 1
        cert_data["subject"]["issue_number"] = WORK_ITEM_NUMBER + 1
        cert.write_text(json.dumps(cert_data), encoding="utf-8")

        manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        inherited_blob = "9" * 40
        manifest_data["handoff_origin"] = {
            "candidate_git_blob_sha": inherited_blob,
            "base_git_blob_sha": inherited_blob,
            "same_blob_as_base": True,
        }
        manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

        proc = run(cert, manifest)
        assert proc.returncode == 2
        assert "inherited-base-artifact" in proc.stdout
        assert "REASON: handoff-not-produced" in proc.stdout
        assert "RECOVERY: handoff-only" in proc.stdout
        assert "fresh-handoff-required" not in proc.stdout
