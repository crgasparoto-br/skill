from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_RESULT_CHILD = "c" * 40
EVIDENCE_BYTES = b"synthetic benchmark result"
EVIDENCE_SHA = hashlib.sha256(EVIDENCE_BYTES).hexdigest()


def run(script: str, *args: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def provenance(material_head: str, subject_sha: str) -> dict:
    return {
        "schema_version": 1,
        "material_head_sha": material_head,
        "base_sha": "d" * 40,
        "evidence": [{
            "evidence_id": "PERF-MEASURE-001",
            "kind": "quantitative",
            "path": "docs/benchmarks/result.json",
            "sha256": EVIDENCE_SHA,
            "subject_sha": subject_sha,
            "freshness_policy": "exact-material-head",
            "producer": "synthetic-benchmark-runner",
            "status": "passed",
        }],
    }


def quantitative_matrix(head_sha: str) -> dict:
    return {
        "schema_version": 1,
        "head_sha": head_sha,
        "requirements": [{
            "requirement_id": "REQ-PERF",
            "obligation_ids": ["OBL-PERF"],
            "risk_families": ["semantic-effect"],
            "risk_surfaces": [{
                "risk_family": "semantic-effect",
                "surface": "critical-path-latency",
                "reason": "The acceptance criterion depends on measured latency percentiles.",
            }],
            "plausible_wrong_implementation": "Reuse a benchmark from an ancestor SHA and relabel it as final-head evidence.",
            "positive_control": {
                "id": "PERF-POS",
                "status": "passed",
                "head_sha": head_sha,
                "evidence": "docs/benchmarks/result.json",
                "evidence_sha256": EVIDENCE_SHA,
                "evidence_kind": "quantitative",
                "evidence_id": "PERF-MEASURE-001",
            },
            "negative_controls": [{
                "id": "PERF-NEG",
                "status": "passed",
                "head_sha": head_sha,
                "evidence_path": "negative.log",
                "evidence_sha256": hashlib.sha256(b"negative").hexdigest(),
                "risk_family": "semantic-effect",
                "surface": "critical-path-latency",
                "dimension": "stale-measurement",
                "failure_mode": "A benchmark measured on an ancestor SHA is accepted for the final material candidate.",
                "plausible_wrong_implementation": "Copy the new head SHA into the control without rerunning the quantitative measurement.",
                "control_type": "scenario",
                "procedure": "Validate a stale exact-SHA measurement against a newer material candidate.",
                "expected": "The stale measurement is rejected before freeze and handoff.",
                "observed": "The stale measurement was rejected by the provenance gate.",
                "sibling_cases": [{
                    "id": "PERF-SIBLING",
                    "surface": "critical-path-latency",
                    "dimension": "fresh-measurement",
                    "status": "passed",
                }],
            }],
            "regression_controls": [{
                "id": "PERF-REG",
                "status": "passed",
                "head_sha": head_sha,
                "evidence": "regression.log",
            }],
        }],
        "uncovered_requirements": [],
    }


def closure() -> dict:
    return {
        "obligations": [{
            "id": "OBL-PERF",
            "disposition": "covered",
            "requirement_ids": ["REQ-PERF"],
        }],
    }


def test_quantitative_evidence_blocks_after_material_head_changes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "evidence-provenance.json"
        write_json(path, provenance(SHA_B, SHA_A))
        proc = run(
            "validate_evidence_freshness.py",
            "--evidence-provenance", str(path),
            "--material-head-sha", SHA_B,
        )
        assert proc.returncode == 2
        assert "quantitative evidence was not measured on the material head" in proc.stdout


def test_result_only_child_does_not_invalidate_measurement_of_material_head() -> None:
    # SHA_RESULT_CHILD intentionally does not replace material_head_sha. A result-only
    # child may publish the packet while the empirical subject remains SHA_B.
    assert SHA_RESULT_CHILD != SHA_B
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "evidence-provenance.json"
        write_json(path, provenance(SHA_B, SHA_B))
        proc = run(
            "validate_evidence_freshness.py",
            "--evidence-provenance", str(path),
            "--material-head-sha", SHA_B,
        )
        assert proc.returncode == 0, proc.stdout


def test_rerun_on_new_material_head_restores_freshness() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "evidence-provenance.json"
        write_json(path, provenance(SHA_B, SHA_B))
        proc = run(
            "validate_evidence_freshness.py",
            "--evidence-provenance", str(path),
            "--material-head-sha", SHA_B,
        )
        assert proc.returncode == 0, proc.stdout


def test_attack_matrix_cannot_reanchor_quantitative_result_from_ancestor_sha() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure_path = base / "requirement-closure.json"
        matrix_path = base / "requirement-attack-matrix.json"
        provenance_path = base / "evidence-provenance.json"
        write_json(closure_path, closure())
        write_json(matrix_path, quantitative_matrix(SHA_B))
        write_json(provenance_path, provenance(SHA_B, SHA_A))
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure", str(closure_path),
            "--attack-matrix", str(matrix_path),
            "--evidence-provenance", str(provenance_path),
        )
        assert proc.returncode == 2
        assert "quantitative evidence is stale for the attack matrix head" in proc.stdout


def test_attack_matrix_accepts_quantitative_result_rerun_on_final_material_head() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure_path = base / "requirement-closure.json"
        matrix_path = base / "requirement-attack-matrix.json"
        provenance_path = base / "evidence-provenance.json"
        write_json(closure_path, closure())
        write_json(matrix_path, quantitative_matrix(SHA_B))
        write_json(provenance_path, provenance(SHA_B, SHA_B))
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure", str(closure_path),
            "--attack-matrix", str(matrix_path),
            "--evidence-provenance", str(provenance_path),
        )
        assert proc.returncode == 0, proc.stdout


def test_invalidation_contract_tracks_quantitative_evidence_and_post_measurement_head_changes() -> None:
    payload = json.loads((ROOT / "contracts" / "stage-dependencies.json").read_text(encoding="utf-8"))
    rules = payload["invalidation_rules"]
    assert rules["quantitative_evidence_changed"] == ["final-gate", "internal-adversarial-gate", "freeze", "remote-gate", "decision"]
    assert rules["material_head_changed_after_measurement"] == ["final-gate", "internal-adversarial-gate", "freeze", "remote-gate", "decision"]
