from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAD = "b" * 40
CANONICAL = [
    "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
    "temporal-consistency", "temporal-destination", "concurrency-atomicity",
    "idempotency", "rollback", "historical-immutability", "structural-contract", "documentation",
]


def run(*args: str):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "check_delivery_saturation.py"), *args], text=True, stdout=subprocess.PIPE)


def test_preflight_rejects_unsaturated_material_family() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp)
        matrix=base/"matrix.json"; risk=base/"risk.json"; inherited=base/"inherited.json"
        matrix.write_text(json.dumps({"head_sha":HEAD,"requirements":[{"requirement_id":"REQ-1","plausible_wrong_implementation":"Accept a past target because the date parses as ISO.","positive_control":{"status":"passed","head_sha":HEAD},"negative_controls":[{"status":"passed","head_sha":HEAD}],"regression_controls":[{"status":"passed","head_sha":HEAD}]}],"uncovered_requirements":[]}),encoding="utf-8")
        risk.write_text(json.dumps({"head_sha":HEAD,"families":[{"family":f,"applicable":f=="temporal-destination","status":"pending" if f=="temporal-destination" else "not-applicable","control_ids":[] if f=="temporal-destination" else []} for f in CANONICAL],"material_families_missing_controls":[]}),encoding="utf-8")
        inherited.write_text(json.dumps({"head_sha":HEAD,"controls":[],"unresolved_controls":[]}),encoding="utf-8")
        proc=run("--attack-matrix",str(matrix),"--risk-saturation",str(risk),"--inherited-controls",str(inherited),"--head-sha",HEAD)
        assert proc.returncode==2
        assert "temporal-destination" in proc.stdout


def test_blocker_harvest_contract_requires_all_atomic_requirements() -> None:
    text=(ROOT/"references"/"blocker-harvest.md").read_text(encoding="utf-8")
    skill=(ROOT/"SKILL.md").read_text(encoding="utf-8")
    assert "todos os requisitos atomicos" in text
    assert "causas diferentes" in skill
    assert "reference-liveness" in text
    assert "passado/atual/futuro" in text


def _saturated_risk():
    return {"head_sha": HEAD, "families": [
        {"family": f, "applicable": False, "status": "not-applicable", "control_ids": []}
        for f in CANONICAL
    ], "material_families_missing_controls": []}


def _quantitative_matrix(evidence_sha: str):
    return {"head_sha": HEAD, "requirements": [{
        "requirement_id": "REQ-PERF",
        "plausible_wrong_implementation": "Relabel an ancestor benchmark as evidence for the final candidate without rerunning it.",
        "positive_control": {
            "id": "PERF-POS", "status": "passed", "head_sha": HEAD,
            "evidence": "docs/benchmark.json", "evidence_sha256": evidence_sha,
            "evidence_kind": "quantitative", "evidence_id": "PERF-001",
        },
        "negative_controls": [{"status": "passed", "head_sha": HEAD}],
        "regression_controls": [{"status": "passed", "head_sha": HEAD}],
    }], "uncovered_requirements": []}


def test_preflight_rejects_quantitative_evidence_measured_on_ancestor_sha() -> None:
    import hashlib
    evidence_sha = hashlib.sha256(b"benchmark").hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix = base / "matrix.json"; risk = base / "risk.json"; inherited = base / "inherited.json"; provenance = base / "provenance.json"
        matrix.write_text(json.dumps(_quantitative_matrix(evidence_sha)), encoding="utf-8")
        risk.write_text(json.dumps(_saturated_risk()), encoding="utf-8")
        inherited.write_text(json.dumps({"head_sha": HEAD, "controls": [], "unresolved_controls": []}), encoding="utf-8")
        provenance.write_text(json.dumps({
            "schema_version": 1, "material_head_sha": HEAD,
            "evidence": [{
                "evidence_id": "PERF-001", "kind": "quantitative", "path": "docs/benchmark.json",
                "sha256": evidence_sha, "subject_sha": "a" * 40,
                "freshness_policy": "exact-material-head", "producer": "synthetic-runner", "status": "passed",
            }],
        }), encoding="utf-8")
        proc = run("--attack-matrix", str(matrix), "--risk-saturation", str(risk), "--inherited-controls", str(inherited), "--head-sha", HEAD, "--evidence-provenance", str(provenance))
        assert proc.returncode == 2
        assert "measured subject_sha differs from candidate" in proc.stdout


def test_preflight_accepts_quantitative_evidence_measured_on_material_head() -> None:
    import hashlib
    evidence_sha = hashlib.sha256(b"benchmark").hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix = base / "matrix.json"; risk = base / "risk.json"; inherited = base / "inherited.json"; provenance = base / "provenance.json"
        matrix.write_text(json.dumps(_quantitative_matrix(evidence_sha)), encoding="utf-8")
        risk.write_text(json.dumps(_saturated_risk()), encoding="utf-8")
        inherited.write_text(json.dumps({"head_sha": HEAD, "controls": [], "unresolved_controls": []}), encoding="utf-8")
        provenance.write_text(json.dumps({
            "schema_version": 1, "material_head_sha": HEAD,
            "evidence": [{
                "evidence_id": "PERF-001", "kind": "quantitative", "path": "docs/benchmark.json",
                "sha256": evidence_sha, "subject_sha": HEAD,
                "freshness_policy": "exact-material-head", "producer": "synthetic-runner", "status": "passed",
            }],
        }), encoding="utf-8")
        proc = run("--attack-matrix", str(matrix), "--risk-saturation", str(risk), "--inherited-controls", str(inherited), "--head-sha", HEAD, "--evidence-provenance", str(provenance))
        assert proc.returncode == 0, proc.stdout


def test_preflight_rejects_active_inherited_family_hidden_by_current_saturation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix = base / "matrix.json"; risk = base / "risk.json"; inherited = base / "inherited.json"
        matrix.write_text(json.dumps({
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-1",
                "plausible_wrong_implementation": "Keep only the current-state path and silently drop a previously proven rollback boundary.",
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{"risk_family": "structural-contract", "surface": "material-composition"}],
                "positive_control": {"status": "passed", "head_sha": HEAD},
                "negative_controls": [{"status": "passed", "head_sha": HEAD}],
                "regression_controls": [{"status": "passed", "head_sha": HEAD}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        payload = _saturated_risk()
        for item in payload["families"]:
            if item["family"] == "structural-contract":
                item.update(applicable=True, status="passed", control_ids=["STRUCT"])
        risk.write_text(json.dumps(payload), encoding="utf-8")
        inherited.write_text(json.dumps({
            "head_sha": HEAD,
            "controls": [{
                "id": "ROLLBACK-INHERITED", "status": "passed", "head_sha": HEAD,
                "risk_family": "rollback", "surface": "future-charge-rollback", "dimension": "reversible-activation",
            }],
            "unresolved_controls": [],
        }), encoding="utf-8")
        proc = run("--attack-matrix", str(matrix), "--risk-saturation", str(risk), "--inherited-controls", str(inherited), "--head-sha", HEAD)
        assert proc.returncode == 2
        assert "requires risk family rollback" in proc.stdout
        assert "marks it not applicable" in proc.stdout


def test_preflight_rejects_inherited_control_subject_sha_from_ancestor() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix = base / "matrix.json"
        matrix.write_text(json.dumps({
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-1",
                "plausible_wrong_implementation": "A stale inherited control is reused while the happy path remains green.",
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{"risk_family": "structural-contract", "surface": "evidence-freshness"}],
                "positive_control": {"status": "passed", "head_sha": HEAD},
                "negative_controls": [{"status": "passed", "head_sha": HEAD}],
                "regression_controls": [{"status": "passed", "head_sha": HEAD}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        risk = base / "risk.json"
        risk.write_text(json.dumps({
            "head_sha": HEAD,
            "families": [
                {"family": family, "applicable": family == "structural-contract", "status": "passed" if family == "structural-contract" else "not-applicable", "control_ids": ["IC-1"] if family == "structural-contract" else []}
                for family in CANONICAL
            ],
            "material_families_missing_controls": [],
        }), encoding="utf-8")
        inherited = base / "inherited.json"
        inherited.write_text(json.dumps({
            "head_sha": HEAD,
            "controls": [{
                "id": "IC-1",
                "status": "passed",
                "head_sha": HEAD,
                "subject_sha": "a" * 40,
                "risk_family": "structural-contract",
                "surface": "evidence-freshness",
                "observed": f"Active exact-head evidence equals {HEAD}.",
            }],
            "unresolved_controls": [],
        }), encoding="utf-8")
        proc = run(
            "--attack-matrix", str(matrix),
            "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited),
            "--head-sha", HEAD,
        )
        assert proc.returncode == 2
        assert "subject_sha differs from candidate" in proc.stdout
