from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from risk_inference import derive_families_from_text, derive_surfaces, required_test_cases_from_texts
from validate_requirement_attack_matrix import validate_test_coverage_contract

HEAD = "a" * 40
EVIDENCE_SHA = hashlib.sha256(b"evidence").hexdigest()


def run(script: str, *args: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def negative(control_id: str, surface: str, dimension: str) -> dict:
    return {
        "id": control_id,
        "status": "passed",
        "head_sha": HEAD,
        "control_type": "test",
        "risk_family": "structural-contract",
        "surface": surface,
        "dimension": dimension,
        "failure_mode": "A maintenance path consumes a divergent definition while the ordinary path remains green.",
        "plausible_wrong_implementation": "Keep a separate maintenance definition that happens to match the canonical source in the happy-path fixture.",
        "procedure": "Run the canonical and maintenance paths with deliberately divergent definitions and inspect the consumed source.",
        "expected": "Both paths consume the same canonical definition and reject or expose the divergent copy.",
        "observed": "The exact-head scenario consumed one canonical definition and detected the divergent maintenance copy.",
        "evidence": "evidence.json",
        "evidence_sha256": EVIDENCE_SHA,
        "sibling_cases": [
            {"id": f"{control_id}-s1", "surface": surface, "dimension": f"{dimension}-seed", "status": "passed"}
        ],
    }


def test_complete_product_wording_does_not_create_reporting_coverage_risk() -> None:
    text = "A instalação completa somente padrões ausentes e mantém os tipos intermediate e complete."
    families = derive_families_from_text(text)
    surfaces = {(item["risk_family"], item["surface"]) for item in derive_surfaces([text])}
    assert "temporal-consistency" not in families
    assert ("temporal-consistency", "reporting-availability-window") not in surfaces


def test_authenticated_target_and_body_override_create_boundary_attacks() -> None:
    text = "O contrato alvo usa o contractId da sessão autenticada; o body não pode escolher nem sobrescrever o alvo."
    families = derive_families_from_text(text)
    surfaces = {(item["risk_family"], item["surface"]) for item in derive_surfaces([text])}
    assert {"authorization", "public-boundary"} <= families
    assert ("authorization", "session-target-binding") in surfaces
    assert ("public-boundary", "request-target-override") in surfaces


def test_canonical_catalog_language_creates_structural_consistency_attack() -> None:
    text = "Runtime e seed usam o mesmo catálogo canônico; não manter uma segunda lista independente."
    families = derive_families_from_text(text)
    surfaces = {(item["risk_family"], item["surface"]) for item in derive_surfaces([text])}
    assert "structural-contract" in families
    assert ("structural-contract", "canonical-source-consistency") in surfaces
    assert "concurrency-atomicity" not in families


def test_explicit_test_clause_extracts_every_named_case() -> None:
    text = "Testes cobrem contrato vazio, ausência de vazamento cross-tenant, idempotência e feedback da interface."
    assert required_test_cases_from_texts([text]) == [
        "contrato vazio",
        "ausência de vazamento cross-tenant",
        "idempotência",
        "feedback da interface",
    ]
    matrix_item = {
        "source_texts": [text],
        "test_coverage_contract": {
            "cases": [
                {"case": "contrato vazio", "control_id": "T1", "status": "passed", "evidence": "tests.log"},
            ]
        },
    }
    errors: list[str] = []
    validate_test_coverage_contract(
        matrix_item,
        rid="REQ-TESTS",
        negative_controls=[],
        errors=errors,
    )
    assert any("omits specified cases" in error for error in errors)


def test_equivalent_obligations_can_share_one_primary_control() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        obligations = [
            {
                "id": "OBL-001",
                "disposition": "covered",
                "source_text": "Parâmetros usam uma fonte canônica compartilhada entre runtime e seed.",
                "flags": [],
                "requirement_ids": ["REQ-OMNIBUS"],
            },
            {
                "id": "OBL-002",
                "disposition": "covered",
                "source_text": "Avaliações usam uma definição canônica compartilhada entre runtime e seed.",
                "flags": [],
                "requirement_ids": ["REQ-OMNIBUS"],
            },
        ]
        closure.write_text(json.dumps({"obligations": obligations}), encoding="utf-8")

        source_texts = [item["source_text"] for item in obligations]
        source_surfaces = derive_surfaces(source_texts)
        surfaces = {(item["risk_family"], item["surface"]): item for item in source_surfaces}
        negatives = [
            negative("CANON", "canonical-source-consistency", "runtime-seed-divergence"),
            negative("CANON2", "canonical-source-consistency", "alternate-runtime-divergence"),
            negative("REL", "relational-semantic-integrity", "linked-definition-divergence"),
        ]
        negatives[2].update({
            "procedure": "Create linked source and consumer records with deliberately incompatible definitions through the canonical producer entrypoint, then read back the stored relation.",
            "expected": "The canonical producer rejects the incompatible linked definitions without a write or performs an explicit transformation before downstream consumption.",
            "observed": "The canonical producer rejected the mismatched linked records, persisted no invalid relation, and downstream readback contained only compatible definitions.",
            "sibling_cases": [
                {"id": "REL-s1", "surface": "relational-semantic-integrity", "dimension": "update-linked-definition", "status": "passed"},
                {"id": "REL-s2", "surface": "relational-semantic-integrity", "dimension": "alternate-producer-definition", "status": "passed"},
            ],
        })
        matrix = base / "matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-OMNIBUS",
                "obligation_ids": ["OBL-001", "OBL-002"],
                "source_texts": source_texts,
                "risk_families": ["structural-contract"],
                "risk_surfaces": list(surfaces.values()),
                "plausible_wrong_implementation": "Maintain two copies that coincide in the happy path but drift independently after maintenance.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.json"},
                "negative_controls": negatives,
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.json"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--attack-matrix", str(matrix),
        )
        assert proc.returncode == 2, proc.stdout
        assert "requires obligation_control_map" in proc.stdout

        payload = json.loads(matrix.read_text(encoding="utf-8"))
        payload["requirements"][0]["obligation_control_map"] = [
            {"obligation_id": "OBL-001", "primary_negative_control_id": "CANON"},
            {"obligation_id": "OBL-002", "primary_negative_control_id": "CANON"},
        ]
        matrix.write_text(json.dumps(payload), encoding="utf-8")
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--attack-matrix", str(matrix),
        )
        assert proc.returncode == 0, proc.stdout


def test_initializer_materializes_obligation_and_test_coverage_contracts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        closure.write_text(json.dumps({
            "obligations": [
                {
                    "id": "OBL-A",
                    "disposition": "covered",
                    "source_text": "Runtime e seed usam o mesmo catálogo canônico.",
                    "flags": [],
                    "requirement_ids": ["REQ-A"],
                },
                {
                    "id": "OBL-B",
                    "disposition": "covered",
                    "source_text": "Testes cobrem estado vazio, replay idempotente e feedback da interface.",
                    "flags": [],
                    "requirement_ids": ["REQ-A"],
                },
            ]
        }), encoding="utf-8")
        out = base / "matrix.json"
        proc = run(
            "init_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--head-sha", HEAD,
            "--out", str(out),
        )
        assert proc.returncode == 0, proc.stdout
        item = json.loads(out.read_text(encoding="utf-8"))["requirements"][0]
        assert item["obligation_control_map"] == [
            {"obligation_id": "OBL-A", "primary_negative_control_id": ""},
            {"obligation_id": "OBL-B", "primary_negative_control_id": ""},
        ]
        assert [case["case"] for case in item["test_coverage_contract"]["cases"]] == [
            "estado vazio",
            "replay idempotente",
            "feedback da interface",
        ]
        surfaces = {(entry["risk_family"], entry["surface"]) for entry in item["risk_surfaces"]}
        assert ("structural-contract", "specified-test-matrix") in surfaces
