from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
EVIDENCE_SHA = hashlib.sha256(b"evidence").hexdigest()


def run(script: str, *args: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def negative(control_id: str, family: str, surface: str, dimension: str, *, source_fields: bool = False) -> dict:
    procedure = "Execute the discriminant scenario at the frozen persistence boundary."
    observed = "The invalid state was rejected and the persisted record preserved the expected mapping."
    wrong = "Accept a happy-path record while skipping the discriminant boundary behavior."
    if source_fields:
        procedure = "Persist deliberately distinct plan, product and version values through the producer entrypoint and inspect the repository payload."
        observed = "The persisted payload kept distinct plan, product and version fields without mapping one identity into another."
        wrong = "Map product or version from the adjacent plan field while the happy path still writes a valid-looking record."
    return {
        "id": control_id,
        "status": "passed",
        "head_sha": HEAD,
        "evidence_path": "negative.log",
        "evidence_sha256": EVIDENCE_SHA,
        "risk_family": family,
        "surface": surface,
        "dimension": dimension,
        "failure_mode": "A plausible wrong implementation survives the happy path and crosses the protected boundary.",
        "plausible_wrong_implementation": wrong,
        "control_type": "scenario",
        "procedure": procedure,
        "expected": "The discriminant case must expose the wrong implementation before handoff.",
        "observed": observed,
        "sibling_cases": [
            {"id": "S1", "surface": surface, "dimension": "sibling-a", "status": "passed"},
            {"id": "S2", "surface": surface, "dimension": "sibling-b", "status": "passed"},
        ],
    }


def test_init_matrix_derives_idempotency_identity_and_quantitative_requirements() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        write_json(closure, {
            "obligations": [{
                "id": "OBL-1",
                "disposition": "covered",
                "source_text": (
                    "Retry, callback duplicado e reprocessamento não podem duplicar consumo. "
                    "Plan, product, version and subscription identities must remain distinct. "
                    "The report exposes average cost and percentile distribution."
                ),
                "flags": [],
                "requirement_ids": ["REQ-1"],
            }]
        })
        proc = run(
            "init_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--head-sha", HEAD,
            "--out", str(matrix),
        )
        assert proc.returncode == 0, proc.stdout
        item = json.loads(matrix.read_text(encoding="utf-8"))["requirements"][0]
        assert "idempotency" in item["risk_families"]
        assert "structural-contract" in item["risk_families"]
        surfaces = {(entry["risk_family"], entry["surface"]) for entry in item["risk_surfaces"]}
        assert ("idempotency", "duplicate-processing") in surfaces
        assert ("structural-contract", "semantic-identity-propagation") in surfaces
        assert item["quantitative_evidence_required"] is True




def test_init_matrix_derives_reporting_coverage_temporal_surface() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        write_json(closure, {
            "obligations": [{
                "id": "OBL-COVERAGE",
                "disposition": "covered",
                "source_text": (
                    "Consultas informam qualidade e cobertura dos dados e escalam proporcionalmente ao periodo. "
                    "A retencao limita o historico disponivel e a resposta informa availableFrom e complete/partial."
                ),
                "flags": [],
                "requirement_ids": ["REQ-COVERAGE"],
            }]
        })
        proc = run(
            "init_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--head-sha", HEAD,
            "--out", str(matrix),
        )
        assert proc.returncode == 0, proc.stdout
        item = json.loads(matrix.read_text(encoding="utf-8"))["requirements"][0]
        assert "temporal-consistency" in item["risk_families"]
        surfaces = {(entry["risk_family"], entry["surface"]) for entry in item["risk_surfaces"]}
        assert ("temporal-consistency", "reporting-availability-window") in surfaces


def test_attack_matrix_rederives_coverage_surface_from_requirement_closure_not_matrix_summary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        write_json(closure, {
            "obligations": [{
                "id": "OBL-COVERAGE",
                "disposition": "covered",
                "source_text": "Consultas informam qualidade e cobertura dos dados; a retencao limita a janela disponivel.",
                "requirement_ids": ["REQ-COVERAGE"],
            }]
        })
        write_json(matrix, {
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-COVERAGE",
                "source_texts": ["Return an analytics report."],
                "risk_families": ["temporal-consistency"],
                "risk_surfaces": [{
                    "risk_family": "temporal-consistency",
                    "surface": "economic-competence",
                    "reason": "Economic rows are grouped by competence month.",
                }],
                "plausible_wrong_implementation": "Return a plausible analytics payload while silently overstating the observable historical window.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [negative("TEMP-OTHER", "temporal-consistency", "economic-competence", "service-month")],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        })
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "temporal-consistency:reporting-availability-window" in proc.stdout


def test_risk_saturation_rederives_coverage_surface_from_requirement_closure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        risk = base / "risk.json"
        write_json(closure, {
            "obligations": [{
                "id": "OBL-COVERAGE",
                "disposition": "covered",
                "source_text": "Coverage and retention define the available historical window and complete or partial data quality.",
                "requirement_ids": ["REQ-COVERAGE"],
            }]
        })
        control = negative("TEMP-OTHER", "temporal-consistency", "economic-competence", "service-month")
        write_json(matrix, {
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-COVERAGE",
                "risk_families": ["temporal-consistency"],
                "risk_surfaces": [{
                    "risk_family": "temporal-consistency",
                    "surface": "economic-competence",
                    "reason": "Economic rows are grouped by competence month.",
                }],
                "negative_controls": [control],
            }],
            "uncovered_requirements": [],
        })
        canonical = [
            "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
            "temporal-consistency", "temporal-destination", "concurrency-atomicity", "idempotency",
            "rollback", "historical-immutability", "structural-contract", "documentation",
        ]
        write_json(risk, {
            "schema_version": 1,
            "head_sha": HEAD,
            "families": [{
                "family": family,
                "applicable": family == "temporal-consistency",
                "reason": "Temporal analytics coverage is material." if family == "temporal-consistency" else "Not applicable to the declared contract.",
                "control_ids": ["TEMP-OTHER"] if family == "temporal-consistency" else [],
                "dimensions": [{
                    "surface": "economic-competence",
                    "reason": "Economic rows are grouped by competence month.",
                    "control_ids": ["TEMP-OTHER"],
                    "status": "passed",
                }] if family == "temporal-consistency" else [],
                "status": "passed" if family == "temporal-consistency" else "not-applicable",
            } for family in canonical],
            "material_families_missing_controls": [],
        })
        proc = run(
            "validate_risk_saturation.py",
            "--attack-matrix", str(matrix),
            "--risk-saturation", str(risk),
            "--requirement-closure", str(closure),
        )
        assert proc.returncode == 2
        assert "attack matrix omits risk surfaces rederived from requirement closure" in proc.stdout
        assert "temporal-consistency:reporting-availability-window" in proc.stdout


def test_attack_matrix_rejects_idempotency_omitted_from_source_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        write_json(closure, {"obligations": [{"id": "OBL-1", "disposition": "covered", "requirement_ids": ["REQ-1"]}]})
        write_json(matrix, {
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-1",
                "source_texts": ["Retry and duplicate callbacks must not create duplicate usage."],
                "risk_families": ["semantic-effect"],
                "risk_surfaces": [{"risk_family": "semantic-effect", "surface": "usage-record", "reason": "Usage is persisted by the productive path."}],
                "plausible_wrong_implementation": "Insert a new usage record on every retry while the first request still succeeds.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [negative("NEG-1", "semantic-effect", "usage-record", "duplicate-replay")],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        })
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "omits risk families rederived from source text" in proc.stdout
        assert "idempotency" in proc.stdout


def test_risk_saturation_rederives_idempotency_from_requirement_closure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        risk = base / "risk.json"
        write_json(closure, {
            "obligations": [{
                "id": "OBL-1",
                "disposition": "covered",
                "source_text": "Duplicate callbacks and retry must not duplicate the logical operation.",
                "requirement_ids": ["REQ-1"],
            }]
        })
        write_json(matrix, {
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-1",
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{"risk_family": "structural-contract", "surface": "runtime-path", "reason": "The runtime path persists the logical operation."}],
                "negative_controls": [negative("NEG-1", "structural-contract", "runtime-path", "runtime-branch")],
            }],
            "uncovered_requirements": [],
        })
        canonical = [
            "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
            "temporal-consistency", "temporal-destination", "concurrency-atomicity", "idempotency",
            "rollback", "historical-immutability", "structural-contract", "documentation",
        ]
        write_json(risk, {
            "schema_version": 1,
            "head_sha": HEAD,
            "families": [{
                "family": family,
                "applicable": family == "structural-contract",
                "reason": "Runtime structural control is active." if family == "structural-contract" else "Not applicable to the declared matrix.",
                "control_ids": ["NEG-1"] if family == "structural-contract" else [],
                "dimensions": [{
                    "surface": "runtime-path",
                    "reason": "The runtime path persists the logical operation.",
                    "control_ids": ["NEG-1"],
                    "status": "passed",
                }] if family == "structural-contract" else [],
                "status": "passed" if family == "structural-contract" else "not-applicable",
            } for family in canonical],
            "material_families_missing_controls": [],
        })
        proc = run(
            "validate_risk_saturation.py",
            "--attack-matrix", str(matrix),
            "--risk-saturation", str(risk),
            "--requirement-closure", str(closure),
        )
        assert proc.returncode == 2
        assert "rederived from requirement closure" in proc.stdout
        assert "idempotency" in proc.stdout


def test_semantic_identity_control_requires_deliberately_distinct_values() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        write_json(closure, {"obligations": [{"id": "OBL-1", "disposition": "covered", "requirement_ids": ["REQ-1"]}]})
        control = negative("IDENTITY-1", "structural-contract", "semantic-identity-propagation", "field-mapping")
        control["procedure"] = "Run the producer path and inspect the resulting repository payload."
        control["observed"] = "The repository payload matched the fixture used by the test."
        write_json(matrix, {
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-1",
                "source_texts": ["Persist plan, product and version identity for each event."],
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{
                    "risk_family": "structural-contract",
                    "surface": "semantic-identity-propagation",
                    "reason": "Adjacent commercial identity fields can be swapped by a producer adapter.",
                }],
                "plausible_wrong_implementation": "Map product and version from plan while the fixture happens to use equal values.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [control],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        })
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "does not use deliberately distinct/divergent identity values" in proc.stdout


def test_semantic_identity_control_accepts_distinct_values_at_persistence_boundary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        write_json(closure, {"obligations": [{"id": "OBL-1", "disposition": "covered", "requirement_ids": ["REQ-1"]}]})
        write_json(matrix, {
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-1",
                "source_texts": ["Persist plan, product and version identity for each event."],
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{
                    "risk_family": "structural-contract",
                    "surface": "semantic-identity-propagation",
                    "reason": "Adjacent commercial identity fields can be swapped by a producer adapter.",
                }],
                "plausible_wrong_implementation": "Map product and version from plan while the fixture happens to use equal values.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [negative("IDENTITY-1", "structural-contract", "semantic-identity-propagation", "distinct-field-mapping", source_fields=True)],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        })
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 0, proc.stdout


def test_quantitative_source_requires_provenance_even_when_matrix_does_not_declare_it() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        write_json(closure, {"obligations": [{"id": "OBL-1", "disposition": "covered", "requirement_ids": ["REQ-1"]}]})
        write_json(matrix, {
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-1",
                "source_texts": ["The report must expose average cost and aggregate count."],
                "risk_families": ["semantic-effect"],
                "risk_surfaces": [{"risk_family": "semantic-effect", "surface": "economic-report", "reason": "The report aggregates executed usage into economic output."}],
                "plausible_wrong_implementation": "Return a plausible report from stale aggregate values without measuring the frozen candidate.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "report.json"},
                "negative_controls": [negative("ECON-1", "semantic-effect", "economic-report", "stale-aggregate")],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        })
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "quantitative source requires quantitative positive control" in proc.stdout


def test_inherited_control_cannot_pass_with_status_and_generic_evidence_only() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        inherited = Path(tmp) / "inherited.json"
        write_json(inherited, {
            "schema_version": 1,
            "head_sha": HEAD,
            "source_audits": ["prior-independent-audit"],
            "controls": [{
                "id": "GENERIC-CONTROL-001",
                "status": "passed",
                "head_sha": HEAD,
                "evidence": "CI green",
            }],
            "unresolved_controls": [],
        })
        proc = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(inherited),
            "--head-sha", HEAD,
            "--previous-independent-rejection",
        )
        assert proc.returncode == 2
        assert "subject_sha differs from candidate" in proc.stdout
        assert "generic pass-through evidence" in proc.stdout or "generic CI/diff status" in proc.stdout
        assert "evidence_sha256" in proc.stdout


def test_inherited_control_requires_discriminant_exact_head_execution_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        inherited = base / "inherited.json"
        previous = base / "previous-inherited.json"
        control = {
            "id": "GENERIC-CONTROL-001",
            "status": "passed",
            "head_sha": HEAD,
            "subject_sha": HEAD,
            "control_type": "scenario",
            "procedure": "Execute the divergent sibling case against the frozen candidate boundary.",
            "expected": "The wrong implementation is rejected by the discriminant control.",
            "observed": "The divergent sibling was rejected with no persisted side effect.",
            "evidence": "artifacts/generic-control.log",
            "evidence_sha256": EVIDENCE_SHA,
        }
        write_json(previous, {
            "schema_version": 1,
            "head_sha": "b" * 40,
            "source_audits": ["prior-independent-audit"],
            "controls": [{**control, "head_sha": "b" * 40, "subject_sha": "b" * 40}],
            "unresolved_controls": [],
        })
        write_json(inherited, {
            "schema_version": 1,
            "head_sha": HEAD,
            "source_audits": ["prior-independent-audit"],
            "controls": [control],
            "unresolved_controls": [],
        })
        proc = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(inherited),
            "--head-sha", HEAD,
            "--previous-independent-rejection",
            "--previous-inherited-controls", str(previous),
        )
        assert proc.returncode == 0, proc.stdout


def test_inherited_control_lineage_rejects_silent_control_removal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        previous = base / "previous.json"
        current = base / "current.json"
        prior_control = {
            "id": "OLD-CONTROL-001", "status": "passed", "head_sha": "b" * 40,
            "subject_sha": "b" * 40, "control_type": "scenario",
            "procedure": "Execute the historical discriminant scenario against the frozen boundary.",
            "expected": "The historical wrong implementation is rejected.",
            "observed": "The historical discriminant scenario was rejected.",
            "evidence": "old.log", "evidence_sha256": EVIDENCE_SHA,
        }
        active = {
            "id": "NEW-CONTROL-001", "status": "passed", "head_sha": HEAD,
            "subject_sha": HEAD, "control_type": "scenario",
            "procedure": "Execute the current discriminant scenario against the frozen boundary.",
            "expected": "The current wrong implementation is rejected.",
            "observed": "The current discriminant scenario was rejected.",
            "evidence": "new.log", "evidence_sha256": EVIDENCE_SHA,
        }
        write_json(previous, {"schema_version": 1, "head_sha": "b" * 40, "source_audits": ["audit-a"], "controls": [prior_control], "unresolved_controls": []})
        write_json(current, {"schema_version": 1, "head_sha": HEAD, "source_audits": ["audit-a", "audit-b"], "controls": [active], "unresolved_controls": []})
        proc = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(current), "--head-sha", HEAD,
            "--previous-independent-rejection", "--previous-inherited-controls", str(previous),
        )
        assert proc.returncode == 2
        assert "OLD-CONTROL-001 disappeared" in proc.stdout


def test_inherited_control_lineage_accepts_explicit_supersession() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        previous = base / "previous.json"
        current = base / "current.json"
        old = {
            "id": "OLD-CONTROL-001", "status": "passed", "head_sha": "b" * 40,
            "subject_sha": "b" * 40, "control_type": "scenario",
            "procedure": "Execute the historical discriminant scenario against the frozen boundary.",
            "expected": "The historical wrong implementation is rejected.",
            "observed": "The historical discriminant scenario was rejected.",
            "evidence": "old.log", "evidence_sha256": EVIDENCE_SHA,
        }
        replacement = {
            "id": "NEW-CONTROL-001", "status": "passed", "head_sha": HEAD,
            "subject_sha": HEAD, "control_type": "scenario",
            "procedure": "Execute the stronger replacement discriminant scenario at the frozen boundary.",
            "expected": "The broader wrong implementation is rejected.",
            "observed": "The broader replacement scenario was rejected without side effects.",
            "evidence": "new.log", "evidence_sha256": EVIDENCE_SHA,
        }
        retirement = {
            "id": "OLD-CONTROL-001", "disposition": "superseded",
            "replacement_control_id": "NEW-CONTROL-001",
            "reason": "The replacement strictly covers the same historical failure mode and a broader sibling surface.",
            "subject_sha": HEAD,
            "procedure": "Compare the historical control contract with the replacement discriminant coverage.",
            "expected": "Every historical failure mode remains discriminated by the replacement control.",
            "observed": "The replacement control covers the historical failure mode and remains exact-head.",
            "evidence": "supersession.log", "evidence_sha256": EVIDENCE_SHA,
        }
        write_json(previous, {"schema_version": 1, "head_sha": "b" * 40, "source_audits": ["audit-a"], "controls": [old], "unresolved_controls": []})
        write_json(current, {"schema_version": 1, "head_sha": HEAD, "source_audits": ["audit-a", "audit-b"], "controls": [replacement], "retired_controls": [retirement], "unresolved_controls": []})
        proc = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(current), "--head-sha", HEAD,
            "--previous-independent-rejection", "--previous-inherited-controls", str(previous),
        )
        assert proc.returncode == 0, proc.stdout


def test_init_matrix_derives_relational_semantic_integrity_from_single_source_contract() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        write_json(closure, {
            "obligations": [{
                "id": "OBL-REL",
                "disposition": "covered",
                "source_text": (
                    "The aggregate dimension must_be_single_source. Each unit must come from linked records, "
                    "and values from different units cannot be combined without explicit conversion."
                ),
                "flags": [],
                "requirement_ids": ["REQ-REL"],
            }]
        })
        proc = run(
            "init_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--head-sha", HEAD,
            "--out", str(matrix),
        )
        assert proc.returncode == 0, proc.stdout
        item = json.loads(matrix.read_text(encoding="utf-8"))["requirements"][0]
        assert "structural-contract" in item["risk_families"]
        surfaces = {(entry["risk_family"], entry["surface"]) for entry in item["risk_surfaces"]}
        assert ("structural-contract", "relational-semantic-integrity") in surfaces


def test_relational_semantic_integrity_control_rejects_happy_path_only_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        source_text = (
            "The aggregate unit is a single source dimension and values from different units cannot be mixed "
            "without explicit conversion."
        )
        write_json(closure, {
            "obligations": [{
                "id": "OBL-REL",
                "disposition": "covered",
                "source_text": source_text,
                "requirement_ids": ["REQ-REL"],
            }]
        })
        weak = negative(
            "REL-SEM-001",
            "structural-contract",
            "relational-semantic-integrity",
            "coherent-fixture",
        )
        weak["procedure"] = "Run the aggregate with coherent fixture values and inspect the final response."
        weak["observed"] = "The final response kept the expected unit label and numeric partitions."
        write_json(matrix, {
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-REL",
                "source_texts": [source_text],
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{
                    "risk_family": "structural-contract",
                    "surface": "relational-semantic-integrity",
                    "reason": "Linked records can carry incompatible units even when the aggregate labels look correct.",
                }],
                "plausible_wrong_implementation": "Trust coherent fixtures while the canonical writer accepts incompatible linked dimensions.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [weak],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        })
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--attack-matrix", str(matrix),
        )
        assert proc.returncode == 2
        assert "deliberately incompatible/divergent linked values" in proc.stdout
        assert "canonical mutation/producer boundary" in proc.stdout


def test_relational_semantic_integrity_control_accepts_incompatible_write_boundary_attack() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        matrix = base / "matrix.json"
        source_text = (
            "The aggregate unit is a single source dimension and values from different units cannot be mixed "
            "without explicit conversion."
        )
        write_json(closure, {
            "obligations": [{
                "id": "OBL-REL",
                "disposition": "covered",
                "source_text": source_text,
                "requirement_ids": ["REQ-REL"],
            }]
        })
        control = negative(
            "REL-SEM-001",
            "structural-contract",
            "relational-semantic-integrity",
            "create-linked-mismatch",
        )
        control.update({
            "failure_mode": "A linked parent and child can carry incompatible unit dimensions while the downstream aggregate still renders plausible labels.",
            "plausible_wrong_implementation": "The canonical create or update producer accepts a parent in unit A and a related child in distinct unit B without explicit conversion.",
            "procedure": "Create linked parent and child records with deliberately incompatible unit values through the canonical mutation entrypoint, then attempt the same mismatch through update and inspect persistence plus the downstream aggregate.",
            "expected": "The producer rejects the incompatible relation without a write, or performs an explicit conversion that represents both linked sides before any downstream calculation.",
            "observed": "Create and update rejected the mismatched linked records with no persisted mutation; readback found no invalid relation and the aggregate consumed only compatible records.",
            "sibling_cases": [
                {"id": "REL-S1", "surface": "relational-semantic-integrity", "dimension": "update-linked-mismatch", "status": "passed"},
                {"id": "REL-S2", "surface": "relational-semantic-integrity", "dimension": "alternate-producer-mismatch", "status": "passed"},
            ],
        })
        write_json(matrix, {
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-REL",
                "source_texts": [source_text],
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{
                    "risk_family": "structural-contract",
                    "surface": "relational-semantic-integrity",
                    "reason": "Linked records can carry incompatible units even when the aggregate labels look correct.",
                }],
                "plausible_wrong_implementation": "Trust coherent fixtures while the canonical writer accepts incompatible linked dimensions.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [control],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        })
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--attack-matrix", str(matrix),
        )
        assert proc.returncode == 0, proc.stdout


def test_inherited_control_lineage_rejects_silent_removal_of_previously_retired_control() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        previous = base / "previous-retired.json"
        current = base / "current.json"
        replacement = {
            "id": "NEW-CONTROL-001", "status": "passed", "head_sha": HEAD,
            "subject_sha": HEAD, "control_type": "scenario",
            "procedure": "Execute the current discriminant scenario against the frozen boundary.",
            "expected": "The current wrong implementation is rejected.",
            "observed": "The current discriminant scenario was rejected.",
            "evidence": "new.log", "evidence_sha256": EVIDENCE_SHA,
        }
        retired = {
            "id": "OLD-CONTROL-001", "disposition": "superseded",
            "replacement_control_id": "NEW-CONTROL-001",
            "reason": "The replacement covers the historical failure mode while the retired identifier remains cumulative lineage.",
            "subject_sha": "b" * 40,
            "procedure": "Compare the historical control contract with its replacement coverage.",
            "expected": "The historical control remains explicitly represented after supersession.",
            "observed": "The historical control is retained as superseded in the prior snapshot.",
            "evidence": "old-retired.log", "evidence_sha256": EVIDENCE_SHA,
        }
        write_json(previous, {
            "schema_version": 1, "head_sha": "b" * 40, "source_audits": ["audit-a"],
            "controls": [{**replacement, "head_sha": "b" * 40, "subject_sha": "b" * 40}],
            "retired_controls": [retired], "unresolved_controls": [],
        })
        write_json(current, {
            "schema_version": 1, "head_sha": HEAD, "source_audits": ["audit-a", "audit-b"],
            "controls": [replacement], "retired_controls": [], "unresolved_controls": [],
        })
        proc = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(current), "--head-sha", HEAD,
            "--previous-independent-rejection", "--previous-inherited-controls", str(previous),
        )
        assert proc.returncode == 2
        assert "OLD-CONTROL-001 disappeared" in proc.stdout


def test_inherited_control_lineage_preserves_previously_retired_control() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        previous = base / "previous-retired.json"
        current = base / "current.json"
        replacement = {
            "id": "NEW-CONTROL-001", "status": "passed", "head_sha": HEAD,
            "subject_sha": HEAD, "control_type": "scenario",
            "procedure": "Execute the current discriminant scenario against the frozen boundary.",
            "expected": "The current wrong implementation is rejected.",
            "observed": "The current discriminant scenario was rejected.",
            "evidence": "new.log", "evidence_sha256": EVIDENCE_SHA,
        }
        prior_retired = {
            "id": "OLD-CONTROL-001", "disposition": "superseded",
            "replacement_control_id": "NEW-CONTROL-001",
            "reason": "The replacement covers the historical failure mode while the retired identifier remains cumulative lineage.",
            "subject_sha": "b" * 40,
            "procedure": "Compare the historical control contract with its replacement coverage.",
            "expected": "The historical control remains explicitly represented after supersession.",
            "observed": "The historical control is retained as superseded in the prior snapshot.",
            "evidence": "old-retired.log", "evidence_sha256": EVIDENCE_SHA,
        }
        current_retired = {
            **prior_retired,
            "subject_sha": HEAD,
            "observed": "The historical control remains explicitly superseded on the current candidate.",
        }
        write_json(previous, {
            "schema_version": 1, "head_sha": "b" * 40, "source_audits": ["audit-a"],
            "controls": [{**replacement, "head_sha": "b" * 40, "subject_sha": "b" * 40}],
            "retired_controls": [prior_retired], "unresolved_controls": [],
        })
        write_json(current, {
            "schema_version": 1, "head_sha": HEAD, "source_audits": ["audit-a", "audit-b"],
            "controls": [replacement], "retired_controls": [current_retired], "unresolved_controls": [],
        })
        proc = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(current), "--head-sha", HEAD,
            "--previous-independent-rejection", "--previous-inherited-controls", str(previous),
        )
        assert proc.returncode == 0, proc.stdout


def test_inherited_control_lineage_allows_restoration_from_trusted_historical_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        historical = base / "historical.json"
        previous = base / "previous.json"
        current = base / "current.json"
        replacement = {
            "id": "NEW-CONTROL-001", "status": "passed", "head_sha": HEAD,
            "subject_sha": HEAD, "control_type": "scenario",
            "procedure": "Execute the current discriminant scenario against the frozen boundary.",
            "expected": "The current wrong implementation is rejected.",
            "observed": "The current discriminant scenario was rejected.",
            "evidence": "new.log", "evidence_sha256": EVIDENCE_SHA,
        }
        retired = {
            "id": "OLD-CONTROL-001", "disposition": "superseded",
            "replacement_control_id": "NEW-CONTROL-001",
            "reason": "The replacement covers the historical failure mode while the retired identifier remains cumulative lineage.",
            "subject_sha": HEAD,
            "procedure": "Compare the historical control contract with its replacement coverage.",
            "expected": "The historical control remains explicitly represented after supersession.",
            "observed": "The historical control is restored from a trusted historical snapshot on the current candidate.",
            "evidence": "old-retired.log", "evidence_sha256": EVIDENCE_SHA,
        }
        write_json(historical, {
            "schema_version": 1, "head_sha": "b" * 40, "source_audits": ["audit-a"],
            "controls": [{**replacement, "head_sha": "b" * 40, "subject_sha": "b" * 40}],
            "retired_controls": [{**retired, "subject_sha": "b" * 40}], "unresolved_controls": [],
        })
        write_json(previous, {
            "schema_version": 1, "head_sha": "c" * 40, "source_audits": ["audit-a", "audit-b"],
            "controls": [{**replacement, "head_sha": "c" * 40, "subject_sha": "c" * 40}],
            "retired_controls": [], "unresolved_controls": [],
        })
        write_json(current, {
            "schema_version": 1, "head_sha": HEAD, "source_audits": ["audit-a", "audit-b", "audit-c"],
            "controls": [replacement], "retired_controls": [retired], "unresolved_controls": [],
        })
        blocked = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(current), "--head-sha", HEAD,
            "--previous-independent-rejection", "--previous-inherited-controls", str(previous),
        )
        assert blocked.returncode == 2
        assert "trusted historical snapshot" in blocked.stdout
        restored = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(current), "--head-sha", HEAD,
            "--previous-independent-rejection", "--previous-inherited-controls", str(previous),
            "--historical-inherited-controls", str(historical),
        )
        assert restored.returncode == 0, restored.stdout
