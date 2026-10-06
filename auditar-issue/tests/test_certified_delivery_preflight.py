from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAD = "d" * 40
BASE = "e" * 40
MERGE = "f" * 40
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


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args: str):
    target_args = [
        "--repository", REPOSITORY,
        "--work-item-kind", WORK_ITEM_KIND,
        "--work-item-number", str(WORK_ITEM_NUMBER),
        "--issue-number", str(WORK_ITEM_NUMBER),
        "--pull-request-number", str(PULL_REQUEST),
        "--base-ref", BASE_REF,
        "--head-ref", HEAD_REF,
    ]
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_delivery_preflight.py"), *target_args, *args],
        text=True, stdout=subprocess.PIPE,
    )


def write_packet(base: Path) -> tuple[Path, Path, Path, Path]:
    spec = base / "specification-snapshot.json"; spec.write_text(
        json.dumps({"repository": REPOSITORY, "issue": WORK_ITEM_NUMBER}), encoding="utf-8"
    )
    closure = base / "requirement-closure.json"; closure.write_text(json.dumps({
        "structural_invariant_closures": {"status": "not-applicable", "applicability_reason": "No structural invariant is exercised by this synthetic packet."},
        "read_model_closures": {"status": "not-applicable", "applicability_reason": "No read-model contract is exercised by this synthetic packet."},
        "canonical_source_consistency": {"status": "not-applicable", "applicability_reason": "No canonical-source consistency contract is exercised by this synthetic packet."},
        "documentation_consistency": {"status": "not-applicable", "applicability_reason": "No documentation transition contract is exercised by this synthetic packet."},
        "scope_reduction_review": {"status": "passed"},
        "pass_c": {"status": "passed"},
    }), encoding="utf-8")
    matrix = base / "requirement-attack-matrix.json"
    matrix.write_text(json.dumps({
        "head_sha": HEAD,
        "requirements": [{
            "requirement_id": "REQ-1",
            "plausible_wrong_implementation": "The implementation preserves the happy path but violates a sibling path.",
            "positive_control": {"status": "passed", "head_sha": HEAD},
            "negative_controls": [{"status": "passed", "head_sha": HEAD}],
            "regression_controls": [{"status": "passed", "head_sha": HEAD}],
        }],
        "uncovered_requirements": [],
    }), encoding="utf-8")
    risk = base / "risk-saturation.json"
    risk.write_text(json.dumps({
        "head_sha": HEAD,
        "families": [{"family": family, "applicable": False, "status": "not-applicable", "control_ids": []} for family in CANONICAL],
        "material_families_missing_controls": [],
    }), encoding="utf-8")
    inherited = base / "inherited-controls.json"
    inherited.write_text(json.dumps({"head_sha": HEAD, "controls": [], "unresolved_controls": []}), encoding="utf-8")
    return matrix, risk, inherited, closure


def make_certificate(base: Path, matrix: Path, risk: Path, inherited: Path, closure: Path) -> Path:
    spec = base / "specification-snapshot.json"
    cert = base / "handoff-ready.json"
    artifacts = {
        "specification_snapshot": spec,
        "requirement_closure": closure,
        "requirement_attack_matrix": matrix,
        "risk_saturation": risk,
        "inherited_controls": inherited,
    }
    cert.write_text(json.dumps({
        "schema_version": 1,
        "status": "ready",
        "identity": {"head_sha": HEAD, "base_sha": BASE, "merge_preview_sha": MERGE},
        "contract_version": "2026-08-20.3",
        "producer": {"skill": "entregar-issue", "skill_sha256": "a" * 64},
        "validators": {},
        "artifacts": {key: {"name": path.name, "sha256": sha(path)} for key, path in artifacts.items()},
        "previous_independent_rejection": False,
    }), encoding="utf-8")
    return cert


def test_preflight_rejects_missing_certificate_before_broad_audit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, _ = write_packet(base)
        proc = run(
            "--certificate", str(base / "missing.json"), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", HEAD, "--base-sha", BASE,
            "--merge-preview-sha", MERGE, "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "invalid handoff certificate" in proc.stdout


def test_preflight_accepts_certified_saturated_packet() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        cert = make_certificate(base, matrix, risk, inherited, closure)
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", HEAD, "--base-sha", BASE,
            "--merge-preview-sha", MERGE, "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 0, proc.stdout


def test_preflight_accepts_result_only_child_and_validates_material_head() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        spec = base / "specification-snapshot.json"
        cert = base / "handoff-ready.json"
        artifacts = {
            "specification_snapshot": spec,
            "requirement_closure": closure,
            "requirement_attack_matrix": matrix,
            "risk_saturation": risk,
            "inherited_controls": inherited,
        }
        allowed = [f".audit/entregar-issue/{path.name}" for path in artifacts.values()]
        allowed.append(".audit/entregar-issue/handoff-ready.json")
        cert.write_text(json.dumps({
            "schema_version": 2,
            "status": "ready",
            "identity": {
                "head_sha": HEAD,
                "material_head_sha": HEAD,
                "base_sha": BASE,
                "merge_preview_sha": MERGE,
                "material_merge_preview_sha": MERGE,
            },
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
            "producer": {"skill": "entregar-issue", "skill_sha256": "a" * 64},
            "validators": {},
            "artifacts": {key: {"name": path.name, "sha256": sha(path)} for key, path in artifacts.items()},
            "previous_independent_rejection": False,
        }), encoding="utf-8")
        published = "1" * 40
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", published, "--base-sha", BASE,
            "--merge-preview-sha", "2" * 40, "--candidate-parent-sha", HEAD,
            "--candidate-changed-path", ".audit/entregar-issue/handoff-ready.json",
            "--candidate-changed-path", ".audit/entregar-issue/requirement-attack-matrix.json",
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 0, proc.stdout
        assert "preserves material head" in proc.stdout


def test_preflight_rejects_result_only_child_with_product_change() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        spec = base / "specification-snapshot.json"
        cert = base / "handoff-ready.json"
        artifacts = {
            "specification_snapshot": spec,
            "requirement_closure": closure,
            "requirement_attack_matrix": matrix,
            "risk_saturation": risk,
            "inherited_controls": inherited,
        }
        cert.write_text(json.dumps({
            "schema_version": 2,
            "status": "ready",
            "identity": {"head_sha": HEAD, "material_head_sha": HEAD, "base_sha": BASE},
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
            "certificate_commit_policy": {
                "mode": "result-only-child",
                "allowed_paths": [".audit/entregar-issue/handoff-ready.json"],
            },
            "contract_version": "2026-08-20.3",
            "producer": {"skill": "entregar-issue", "skill_sha256": "a" * 64},
            "validators": {},
            "artifacts": {key: {"name": path.name, "sha256": sha(path)} for key, path in artifacts.items()},
            "previous_independent_rejection": False,
        }), encoding="utf-8")
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", "1" * 40, "--base-sha", BASE,
            "--candidate-parent-sha", HEAD,
            "--candidate-changed-path", "server/product.ts",
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "non-handoff paths" in proc.stdout


def test_preflight_forwards_certified_quantitative_provenance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        evidence_sha = hashlib.sha256(b"quantitative-evidence").hexdigest()
        matrix.write_text(json.dumps({
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-QUANT",
                "plausible_wrong_implementation": "Reuse a measurement from an ancestor while claiming it belongs to the candidate.",
                "positive_control": {
                    "id": "QUANT-001",
                    "status": "passed",
                    "head_sha": HEAD,
                    "evidence": "evidence/quantitative.json",
                    "evidence_sha256": evidence_sha,
                    "evidence_kind": "quantitative",
                    "evidence_id": "QUANT-EVIDENCE-001",
                },
                "negative_controls": [{"status": "passed", "head_sha": HEAD}],
                "regression_controls": [{"status": "passed", "head_sha": HEAD}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        provenance = base / "evidence-provenance.json"
        provenance.write_text(json.dumps({
            "schema_version": 1,
            "material_head_sha": HEAD,
            "evidence": [{
                "evidence_id": "QUANT-EVIDENCE-001",
                "kind": "quantitative",
                "path": "evidence/quantitative.json",
                "sha256": evidence_sha,
                "subject_sha": HEAD,
                "freshness_policy": "exact-material-head",
                "producer": "exact-head quantitative harness",
                "status": "passed",
            }],
        }), encoding="utf-8")
        spec = base / "specification-snapshot.json"
        cert = base / "handoff-ready.json"
        artifacts = {
            "specification_snapshot": spec,
            "requirement_closure": closure,
            "requirement_attack_matrix": matrix,
            "risk_saturation": risk,
            "inherited_controls": inherited,
            "evidence_provenance": provenance,
        }
        cert.write_text(json.dumps({
            "schema_version": 1,
            "status": "ready",
            "identity": {"head_sha": HEAD, "base_sha": BASE, "merge_preview_sha": MERGE},
            "contract_version": "2026-08-20.3",
            "producer": {"skill": "entregar-issue", "skill_sha256": "a" * 64},
            "validators": {},
            "artifacts": {key: {"name": path.name, "sha256": sha(path)} for key, path in artifacts.items()},
            "previous_independent_rejection": False,
        }), encoding="utf-8")
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", HEAD, "--base-sha", BASE,
            "--merge-preview-sha", MERGE, "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 0, proc.stdout


def test_preflight_forwards_learning_and_previous_snapshots_for_reaudit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        evidence_sha = hashlib.sha256(b"reaudit-evidence").hexdigest()
        current_control = {
            "id": "INHERITED-001",
            "status": "passed",
            "head_sha": HEAD,
            "subject_sha": HEAD,
            "control_type": "scenario",
            "procedure": "Execute the inherited discriminant scenario on the frozen candidate.",
            "expected": "The prior escaped behavior remains rejected.",
            "observed": "The candidate rejected the prior escaped behavior.",
            "evidence": "evidence/inherited.log",
            "evidence_sha256": evidence_sha,
        }
        inherited.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "source_audits": ["audit-a", "audit-b"],
            "controls": [current_control],
            "unresolved_controls": [],
        }), encoding="utf-8")
        previous_inherited = base / "previous-inherited-controls.json"
        previous_head = "c" * 40
        previous_control = dict(current_control, head_sha=previous_head, subject_sha=previous_head)
        previous_inherited.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": previous_head,
            "source_audits": ["audit-a"],
            "controls": [previous_control],
            "unresolved_controls": [],
        }), encoding="utf-8")
        escape = base / "audit-escape-closure.json"
        rejection_id = "audit-rejection:0f5d7c2e-5b1a-4c7e-9d3f-a00100000001"
        escape_payload = {
            "schema_version": 1,
            "escapes": [{
                "escape_id": "A-001",
                "escape_class": "aggregate-preflight-argument-loss",
                "source_audit": {"rejection_id": rejection_id, "finding_id": "A-001"},
                "plausible_wrong_implementation": "The aggregate preflight omits required evidence when delegating to a stricter validator.",
                "status": "passed",
                "sibling_cases": [
                    {"id": "quantitative-provenance", "status": "passed"},
                    {"id": "reaudit-lineage", "status": "passed"},
                ],
                "prevention_change": {"evidence": "aggregate delegation contract"},
                "detection_change": {"evidence": "integration regression test"},
                "revalidated_head_sha": HEAD,
            }],
        }
        escape.write_text(json.dumps(escape_payload), encoding="utf-8")
        previous_escape = base / "previous-audit-escape-closure.json"
        previous_escape.write_text(json.dumps(escape_payload), encoding="utf-8")
        learning = base / "learning-closure.json"
        learning.write_text(json.dumps({
            "schema_version": 1,
            "classification": "implementation-only",
            "source_event": {
                "kind": "independent-audit-rejection",
                "rejection_id": rejection_id,
                "finding_ids": ["A-001"],
            },
            "generalized_learning": {
                "promotion_status": "not-required",
                "reason": "The existing aggregate validator contract only needed correct argument propagation.",
            },
        }), encoding="utf-8")
        audit_source = base / "audit-source-result.json"
        audit_source.write_text(json.dumps({
            "rejection_id": rejection_id,
            "head_sha": previous_head,
            "findings": [],
            "recommendations": [],
        }), encoding="utf-8")
        audit_remediation = base / "audit-remediation.json"
        audit_remediation.write_text(json.dumps({
            "schema_version": 1,
            "contract_version": "2026-08-20.3",
            "resolution_policy": "all-actionable-items",
            "source": {
                "rejection_id": rejection_id,
                "audit_report_sha256": sha(audit_source),
                "audited_head_sha": previous_head,
            },
            "candidate_head_sha": HEAD,
            "remediation_mode": "targeted-remediation",
            "items": [],
            "status": "closed",
        }), encoding="utf-8")
        spec = base / "specification-snapshot.json"
        cert = base / "handoff-ready.json"
        artifacts = {
            "specification_snapshot": spec,
            "requirement_closure": closure,
            "requirement_attack_matrix": matrix,
            "risk_saturation": risk,
            "inherited_controls": inherited,
            "audit_escape_closure": escape,
            "learning_closure": learning,
            "audit_remediation": audit_remediation,
            "audit_source_result": audit_source,
        }
        cert.write_text(json.dumps({
            "schema_version": 1,
            "status": "ready",
            "identity": {"head_sha": HEAD, "base_sha": BASE, "merge_preview_sha": MERGE},
            "contract_version": "2026-08-20.3",
            "producer": {"skill": "entregar-issue", "skill_sha256": "a" * 64},
            "validators": {},
            "artifacts": {key: {"name": path.name, "sha256": sha(path)} for key, path in artifacts.items()},
            "previous_independent_rejection": True,
        }), encoding="utf-8")
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", HEAD, "--base-sha", BASE,
            "--merge-preview-sha", MERGE,
            "--previous-closure", str(previous_escape),
            "--previous-inherited-controls", str(previous_inherited),
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 0, proc.stdout


def test_preflight_rejects_certified_packet_with_pending_terminal_closure_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        data = json.loads(closure.read_text(encoding="utf-8"))
        data["read_model_closures"]["status"] = "pending"
        closure.write_text(json.dumps(data), encoding="utf-8")
        cert = make_certificate(base, matrix, risk, inherited, closure)
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", HEAD, "--base-sha", BASE,
            "--merge-preview-sha", MERGE, "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "read_model_closures gate is still pending" in proc.stdout


def test_preflight_rejects_inherited_control_narrative_that_claims_ancestor_as_current() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        stale = "a" * 40
        inherited.write_text(json.dumps({
            "head_sha": HEAD,
            "controls": [{
                "id": "STALE-NARRATIVE",
                "status": "passed",
                "head_sha": HEAD,
                "subject_sha": HEAD,
                "risk_family": "structural-contract",
                "surface": "evidence-freshness",
                "observed": f"Active exact-head evidence now equals frozen material head {stale}.",
            }],
            "unresolved_controls": [],
        }), encoding="utf-8")
        # Make the material family/surface present so the narrative mismatch is the discriminant blocker.
        m = json.loads(matrix.read_text(encoding="utf-8"))
        m["requirements"][0]["risk_families"] = ["structural-contract"]
        m["requirements"][0]["risk_surfaces"] = [{"risk_family": "structural-contract", "surface": "evidence-freshness"}]
        matrix.write_text(json.dumps(m), encoding="utf-8")
        r = json.loads(risk.read_text(encoding="utf-8"))
        for family in r["families"]:
            if family["family"] == "structural-contract":
                family.update({"applicable": True, "status": "passed", "control_ids": ["STALE-NARRATIVE"]})
        risk.write_text(json.dumps(r), encoding="utf-8")
        cert = make_certificate(base, matrix, risk, inherited, closure)
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", HEAD, "--base-sha", BASE,
            "--merge-preview-sha", MERGE, "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "observed narrative asserts non-current SHA(s) as current/exact-head" in proc.stdout


def test_preflight_rejects_foreign_target_subject_before_broad_audit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        spec = base / "specification-snapshot.json"
        cert = base / "handoff-ready.json"
        artifacts = {
            "specification_snapshot": spec,
            "requirement_closure": closure,
            "requirement_attack_matrix": matrix,
            "risk_saturation": risk,
            "inherited_controls": inherited,
        }
        allowed = [f".audit/entregar-issue/{path.name}" for path in artifacts.values()] + [".audit/entregar-issue/handoff-ready.json"]
        cert.write_text(json.dumps({
            "schema_version": 2,
            "status": "ready",
            "identity": {"head_sha": HEAD, "material_head_sha": HEAD, "base_sha": BASE},
            "subject": {
                "repository": REPOSITORY,
                "issue_number": WORK_ITEM_NUMBER,
                "pull_request_number": PULL_REQUEST,
                "work_item_kind": WORK_ITEM_KIND,
                "work_item_number": WORK_ITEM_NUMBER + 1,
                "pull_request": PULL_REQUEST,
                "base_ref": BASE_REF,
                "head_ref": HEAD_REF,
            },
            "certificate_commit_policy": {"mode": "result-only-child", "allowed_paths": allowed},
            "contract_version": "2026-08-20.3",
            "producer": {"skill": "entregar-issue", "skill_sha256": "a" * 64},
            "artifacts": {key: {"name": path.name, "sha256": sha(path)} for key, path in artifacts.items()},
            "previous_independent_rejection": False,
        }), encoding="utf-8")
        published = "1" * 40
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", published, "--base-sha", BASE,
            "--candidate-parent-sha", HEAD,
            "--candidate-changed-path", ".audit/entregar-issue/handoff-ready.json",
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "certificate subject work_item_number differs from audit target" in proc.stdout
        assert "RECOVERY: fresh-handoff-required" in proc.stdout


def test_preflight_rejects_foreign_specification_snapshot_before_broad_audit() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        spec = base / "specification-snapshot.json"
        spec.write_text(json.dumps({"repository": REPOSITORY, "issue": WORK_ITEM_NUMBER + 1}), encoding="utf-8")
        cert = make_certificate(base, matrix, risk, inherited, closure)
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", HEAD, "--base-sha", BASE,
            "--merge-preview-sha", MERGE, "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "specification snapshot issue differs from audit target" in proc.stdout
        assert "RECOVERY: fresh-handoff-required" in proc.stdout
