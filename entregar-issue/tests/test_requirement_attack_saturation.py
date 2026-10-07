from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
HEAD = "a" * 40
EVIDENCE_SHA = hashlib.sha256(b"negative").hexdigest()


def run(script: str, *args: str):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def negative_control(control_id: str, family: str, surface: str, dimension: str):
    return {
        "id": control_id,
        "status": "passed",
        "head_sha": HEAD,
        "evidence_path": "negative.log",
        "evidence_sha256": EVIDENCE_SHA,
        "risk_family": family,
        "surface": surface,
        "dimension": dimension,
        "failure_mode": "A stale or unauthorized value crosses the protected boundary.",
        "plausible_wrong_implementation": "Validate only the happy path and skip the definitive boundary check.",
        "control_type": "scenario",
        "procedure": "Execute the discriminant scenario against the frozen candidate.",
        "expected": "The invalid state is rejected at the definitive boundary.",
        "observed": "The invalid state was rejected without side effects.",
        "sibling_cases": [
            {"id": "S1", "surface": surface, "dimension": "deleted-reference", "status": "passed"},
            {"id": "S2", "surface": surface, "dimension": "changed-eligibility", "status": "passed"},
        ],
    }


def test_attack_matrix_requires_discriminant_controls_and_regression() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({"obligations": [{"id": "OBL-001", "disposition": "covered", "requirement_ids": ["REQ-001"]}]}), encoding="utf-8")
        matrix = base / "requirement-attack-matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-001",
                "obligation_ids": ["OBL-001"],
                "risk_families": ["reference-liveness"],
                "risk_surfaces": [{"risk_family": "reference-liveness", "surface": "reference-store", "reason": "Persisted references are consumed after approval."}],
                "plausible_wrong_implementation": "Validate the reference only during approval and never again during release.",
                "positive_control": {"id": "POS-1", "status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [negative_control("REF-LIVE-001", "reference-liveness", "reference-store", "release-time-liveness")],
                "regression_controls": [{"id": "REG-1", "status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 0, proc.stdout


def test_risk_saturation_requires_every_canonical_family_surface_and_active_control() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix = base / "requirement-attack-matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1, "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-001",
                "risk_families": ["temporal-destination"],
                "risk_surfaces": [{"risk_family": "temporal-destination", "surface": "destination-selector", "reason": "A concrete date selects a future destination."}],
                "negative_controls": [negative_control("TEMP-DEST-001", "temporal-destination", "destination-selector", "future-destination")],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        risk = base / "risk-saturation.json"
        proc = run("init_risk_saturation.py", "--attack-matrix", str(matrix), "--out", str(risk))
        assert proc.returncode == 0
        data = json.loads(risk.read_text())
        for item in data["families"]:
            if item["family"] == "temporal-destination":
                item["status"] = "passed"
                for dimension in item["dimensions"]:
                    dimension["status"] = "passed"
        risk.write_text(json.dumps(data), encoding="utf-8")
        proc = run("validate_risk_saturation.py", "--attack-matrix", str(matrix), "--risk-saturation", str(risk))
        assert proc.returncode == 0, proc.stdout


def test_init_attack_matrix_derives_performance_surfaces_from_source_text() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({
            "obligations": [
                {
                    "id": "OBL-001",
                    "disposition": "covered",
                    "source_text": "É possível identificar quanto tempo foi gasto em banco, montagem de contexto, IA e persistência.",
                    "flags": [],
                    "requirement_ids": ["REQ-PERF"],
                },
                {
                    "id": "OBL-002",
                    "disposition": "covered",
                    "source_text": "Operações não essenciais foram removidas do caminho crítico quando seguro.",
                    "flags": [],
                    "requirement_ids": ["REQ-PERF"],
                },
            ]
        }), encoding="utf-8")
        matrix = base / "matrix.json"
        proc = run("init_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--head-sha", HEAD, "--out", str(matrix))
        assert proc.returncode == 0, proc.stdout
        item = json.loads(matrix.read_text(encoding="utf-8"))["requirements"][0]
        assert "structural-contract" in item["risk_families"]
        surfaces = {entry["surface"] for entry in item["risk_surfaces"]}
        assert "stage-attribution-completeness" in surfaces
        assert "critical-path-necessity" in surfaces
        assert "performance_contract" in item
        assert item["performance_contract"]["operations"] == []
        assert len(item["source_texts"]) == 2


def test_attack_matrix_rejects_generic_placeholder_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({"obligations": [{"id": "OBL-001", "disposition": "covered", "requirement_ids": ["REQ-001"]}]}), encoding="utf-8")
        matrix = base / "requirement-attack-matrix.json"
        control = negative_control("NEG-1", "structural-contract", "runtime-boundary", "behavioral-escape")
        control.update({
            "failure_mode": "Silent contract break.",
            "plausible_wrong_implementation": "Wrong shortcut keeps happy path.",
            "procedure": "Run exact-head control.",
            "expected": "Contract holds.",
            "observed": "Observed pass.",
        })
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-001",
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{"risk_family": "structural-contract", "surface": "runtime-boundary", "reason": "A concrete runtime boundary can be bypassed by an alternate branch."}],
                "plausible_wrong_implementation": "A concrete alternate branch skips the definitive runtime boundary check.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [control],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "generic/tautological" in proc.stdout


def test_performance_source_text_requires_stage_and_critical_path_surfaces() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({"obligations": [{"id": "OBL-001", "disposition": "covered", "requirement_ids": ["REQ-PERF"]}]}), encoding="utf-8")
        matrix = base / "requirement-attack-matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-PERF",
                "source_texts": [
                    "Instrumentação deve expor db_ms e context_ms por etapa.",
                    "Operações não essenciais devem sair do caminho crítico para reduzir latência p90.",
                ],
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{"risk_family": "structural-contract", "surface": "critical-path-latency", "reason": "The measured request can remain slow when hidden work survives in a parallel branch."}],
                "plausible_wrong_implementation": "Time only the primary loader while a parallel helper still performs database work before the provider call.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [negative_control("NEG-1", "structural-contract", "critical-path-latency", "parallel-hidden-work")],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "stage-attribution-completeness" in proc.stdout
        assert "critical-path-necessity" in proc.stdout


def test_performance_controls_require_concrete_stage_and_zero_call_observations() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({"obligations": [{"id": "OBL-001", "disposition": "covered", "requirement_ids": ["REQ-PERF"]}]}), encoding="utf-8")
        stage = negative_control("PERF-STAGE-ATTR-001", "structural-contract", "stage-attribution-completeness", "parallel-db-operation")
        stage.update({
            "failure_mode": "A parallel database query executes outside db_ms while still delaying the provider call.",
            "plausible_wrong_implementation": "Wrap only the primary loader with the db timer and leave the history query in a parallel helper outside the timer.",
            "procedure": "Trace every database operation from the productive entrypoint and compare query timestamps with the db_ms timer boundary.",
            "expected": "Every database query on the measured branch is contained by the db timer or has an explicit separate metric.",
            "observed": "The trace recorded both database queries inside the declared db metric boundary.",
            "sibling_cases": [{"id": "S1", "surface": "stage-attribution-completeness", "dimension": "transitive-query", "status": "passed"}],
        })
        necessity = negative_control("PERF-CRITICAL-WORK-001", "structural-contract", "critical-path-necessity", "unused-loader-zero-call")
        necessity.update({
            "failure_mode": "A generic branch still invokes an expensive loader whose output is discarded before the provider call.",
            "plausible_wrong_implementation": "Reuse a broad context builder that queries unrelated domain data even though the branch consumes only recent history.",
            "procedure": "Run the generic branch with spies on the unrelated loader and then run a sibling personal branch that requires the same loader.",
            "expected": "The generic branch records zero loader calls and the personal sibling branch records one required call.",
            "observed": "Generic branch call count was zero; personal sibling branch invoked the loader once and preserved behavior.",
            "sibling_cases": [{"id": "S2", "surface": "critical-path-necessity", "dimension": "required-loader-present", "status": "passed"}],
        })
        matrix = base / "requirement-attack-matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-PERF",
                "source_texts": [
                    "Instrumentação deve expor db_ms e context_ms por etapa.",
                    "Operações não essenciais devem sair do caminho crítico para reduzir latência p90.",
                ],
                "risk_families": ["structural-contract"],
                "risk_surfaces": [
                    {"risk_family": "structural-contract", "surface": "stage-attribution-completeness", "reason": "Stage timing can omit a parallel query and under-report database work."},
                    {"risk_family": "structural-contract", "surface": "critical-path-necessity", "reason": "A broad helper can execute unused I/O even when the selected branch discards its output."},
                ],
                "plausible_wrong_implementation": "Measure only the primary data loader and keep unrelated I/O in a broad context helper on every branch.",
                "performance_contract": {
                    "production_entrypoint": "server/webhook.ts#handleRequest",
                    "terminal_boundary": "server/lifecycle.ts#markProcessed",
                    "inventory_evidence": {
                        "status": "passed",
                        "head_sha": HEAD,
                        "procedure": "Trace direct, transitive and parallel operations from the productive entrypoint to the terminal boundary.",
                        "observed": "The inventory contains the required database read and the optional context loader for the measured branch.",
                        "evidence": "performance-inventory.log",
                        "evidence_sha256": EVIDENCE_SHA,
                    },
                    "operations": [
                        {
                            "id": "required-db-read",
                            "source": "server/data.ts#loadPrimary",
                            "stage": "db",
                            "metric": "db_ms",
                            "before_terminal": True,
                            "required_for_contract": True,
                        },
                        {
                            "id": "optional-history-read",
                            "source": "server/history.ts#loadHistory",
                            "stage": "db",
                            "metric": "db_ms",
                            "before_terminal": True,
                            "required_for_contract": False,
                        },
                    ],
                    "optimized_branches": [{
                        "id": "generic-branch",
                        "operations": [
                            {
                                "operation_id": "required-db-read",
                                "needed": True,
                                "expected_invocations": 1,
                                "observed_invocations": 1,
                                "status": "passed",
                            },
                            {
                                "operation_id": "optional-history-read",
                                "needed": False,
                                "expected_invocations": 0,
                                "observed_invocations": 0,
                                "status": "passed",
                            },
                        ],
                    }],
                    "benchmark": None,
                },
                "positive_control": {
                    "status": "passed", "head_sha": HEAD, "evidence": "performance.json",
                    "evidence_sha256": hashlib.sha256(b"performance").hexdigest(),
                    "evidence_kind": "quantitative", "evidence_id": "PERF-MEASURE-001",
                },
                "negative_controls": [stage, necessity],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        provenance = base / "evidence-provenance.json"
        provenance.write_text(json.dumps({
            "schema_version": 1,
            "material_head_sha": HEAD,
            "base_sha": "b" * 40,
            "evidence": [{
                "evidence_id": "PERF-MEASURE-001",
                "kind": "quantitative",
                "path": "performance.json",
                "sha256": hashlib.sha256(b"performance").hexdigest(),
                "subject_sha": HEAD,
                "freshness_policy": "exact-material-head",
                "producer": "synthetic-performance-fixture",
                "status": "passed",
            }],
        }), encoding="utf-8")
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--attack-matrix", str(matrix),
            "--evidence-provenance", str(provenance),
        )
        assert proc.returncode == 0, proc.stdout


def test_init_attack_matrix_derives_evidence_effect_scope_from_contract_text() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-SCOPE",
                "disposition": "covered",
                "source_text": "Only affected operations related to the evidence may be restricted, including an emergency exception path.",
                "flags": [],
                "requirement_ids": ["REQ-SCOPE"],
            }]
        }), encoding="utf-8")
        matrix = base / "matrix.json"
        proc = run("init_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--head-sha", HEAD, "--out", str(matrix))
        assert proc.returncode == 0, proc.stdout
        item = json.loads(matrix.read_text(encoding="utf-8"))["requirements"][0]
        assert "authorization" in item["risk_families"]
        assert {entry["surface"] for entry in item["risk_surfaces"]} == {"evidence-effect-scope"}


def test_validator_rejects_evidence_effect_contract_without_scope_surface() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({"obligations": [{"id": "OBL-SCOPE", "disposition": "covered", "requirement_ids": ["REQ-SCOPE"]}]}), encoding="utf-8")
        matrix = base / "matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-SCOPE",
                "source_texts": ["Only affected operations related to the evidence may be restricted, including an emergency exception path."],
                "risk_families": ["authorization"],
                "risk_surfaces": [{"risk_family": "authorization", "surface": "admin-boundary", "reason": "An administrative caller can request a protected mutation."}],
                "plausible_wrong_implementation": "Check that evidence exists and that the requested effect is generally permitted without binding both scopes.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [negative_control("AUTH-1", "authorization", "admin-boundary", "role-denied")],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "evidence-effect-scope" in proc.stdout


def test_validator_requires_divergent_scope_and_exception_sibling() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({"obligations": [{"id": "OBL-SCOPE", "disposition": "covered", "requirement_ids": ["REQ-SCOPE"]}]}), encoding="utf-8")
        control = negative_control("AUTH-EFFECT-SCOPE-001", "authorization", "evidence-effect-scope", "unrelated-effect-rejected")
        control.update({
            "failure_mode": "A valid evidence record exists but an unrelated operation is accepted outside the approved scope.",
            "plausible_wrong_implementation": "Validate evidence existence and generic operation permission without comparing the approved evidence scope to the requested effect.",
            "procedure": "Authorize effect_a in the evidence, request divergent effect_b, and inspect persistence before and after rejection.",
            "expected": "The unrelated effect_b is rejected before mutation because it is outside the authorized evidence scope.",
            "observed": "The divergent effect_b request was rejected and no mutation was recorded.",
            "sibling_cases": [
                {"id": "S1", "surface": "evidence-effect-scope", "dimension": "mixed-scope-request", "status": "passed"},
                {"id": "S2", "surface": "evidence-effect-scope", "dimension": "emergency-branch-unrelated-effect", "status": "passed"},
            ],
        })
        matrix = base / "matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-SCOPE",
                "source_texts": ["Only affected operations related to the evidence may be restricted, including an emergency exception path."],
                "risk_families": ["authorization"],
                "risk_surfaces": [{"risk_family": "authorization", "surface": "evidence-effect-scope", "reason": "A valid evidence source can be present while a later branch requests an unrelated effect."}],
                "plausible_wrong_implementation": "Check only that evidence exists and accept any generally allowed effect in the emergency branch.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [control],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 0, proc.stdout

        data = json.loads(matrix.read_text(encoding="utf-8"))
        data["requirements"][0]["negative_controls"][0]["sibling_cases"][1]["dimension"] = "ordinary-branch-unrelated-effect"
        matrix.write_text(json.dumps(data), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "exception/emergency branch sibling" in proc.stdout


def test_init_attack_matrix_derives_benchmark_path_fidelity_surface() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-BENCH",
                "disposition": "covered",
                "source_text": "O harness deve exercitar o mesmo caminho produtivo usado pela aplicação.",
                "flags": [],
                "requirement_ids": ["REQ-BENCH-PATH"],
            }]
        }), encoding="utf-8")
        matrix = base / "matrix.json"
        proc = run("init_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--head-sha", HEAD, "--out", str(matrix))
        assert proc.returncode == 0, proc.stdout
        item = json.loads(matrix.read_text(encoding="utf-8"))["requirements"][0]
        assert "structural-contract" in item["risk_families"]
        assert "benchmark-path-fidelity" in {entry["surface"] for entry in item["risk_surfaces"]}
        assert item["performance_contract"]["production_entrypoint"] == ""


def test_performance_contract_rejects_database_operation_outside_db_metric() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-STAGE",
                "disposition": "covered",
                "source_text": "Instrumentação deve expor db_ms para o tempo gasto em banco.",
                "requirement_ids": ["REQ-STAGE"],
            }]
        }), encoding="utf-8")
        stage = negative_control("PERF-STAGE-ATTR-001", "structural-contract", "stage-attribution-completeness", "wrapper-db-read")
        stage.update({
            "failure_mode": "A database lookup in a productive wrapper executes before the handler but remains outside db_ms.",
            "plausible_wrong_implementation": "Time only context loaders while leaving the user lookup database query outside the db_ms boundary.",
            "procedure": "Trace database operations from the production entrypoint and compare each query with the db_ms timer boundary.",
            "expected": "Every database operation before the terminal boundary is attributed to db_ms.",
            "observed": "The user lookup query was found outside the declared db_ms boundary.",
        })
        matrix = base / "matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-STAGE",
                "source_texts": ["Instrumentação deve expor db_ms para o tempo gasto em banco."],
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{
                    "risk_family": "structural-contract",
                    "surface": "stage-attribution-completeness",
                    "reason": "A wrapper database read can execute outside the declared stage timer.",
                }],
                "plausible_wrong_implementation": "Measure only database reads performed by the inner handler and omit wrapper lookups from db_ms.",
                "performance_contract": {
                    "production_entrypoint": "server/webhook.ts#handleWebhook",
                    "terminal_boundary": "server/lifecycle.ts#markProcessed",
                    "inventory_evidence": {
                        "status": "passed",
                        "head_sha": HEAD,
                        "procedure": "Trace direct, transitive and parallel operations from the production entrypoint to the terminal boundary.",
                        "observed": "The inventory identified the user lookup database read before the handler.",
                        "evidence": "inventory.log",
                        "evidence_sha256": EVIDENCE_SHA,
                    },
                    "operations": [{
                        "id": "user-lookup",
                        "source": "server/users.ts#findUserByPhone",
                        "stage": "db",
                        "metric": None,
                        "before_terminal": True,
                        "required_for_contract": True,
                    }],
                    "optimized_branches": [],
                    "benchmark": None,
                },
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [stage],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "must be attributed to db_ms" in proc.stdout


def test_performance_contract_rejects_unused_operation_that_still_runs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-CRITICAL",
                "disposition": "covered",
                "source_text": "Operações não essenciais devem sair do caminho crítico quando seguro.",
                "requirement_ids": ["REQ-CRITICAL"],
            }]
        }), encoding="utf-8")
        control = negative_control("PERF-CRITICAL-WORK-001", "structural-contract", "critical-path-necessity", "unused-history-zero-call")
        control.update({
            "failure_mode": "A generic branch still calls history I/O even though the response does not consume that history.",
            "plausible_wrong_implementation": "Keep a broad helper that always queries recent history and discard the result for generic questions.",
            "procedure": "Run the generic branch with a call counter on the history loader and compare it with a sibling branch that needs history.",
            "expected": "The generic branch records zero history calls while the sibling branch may call history when needed.",
            "observed": "The generic branch unexpectedly recorded one history loader call.",
        })
        matrix = base / "matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-CRITICAL",
                "source_texts": ["Operações não essenciais devem sair do caminho crítico quando seguro."],
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{
                    "risk_family": "structural-contract",
                    "surface": "critical-path-necessity",
                    "reason": "A generic branch can keep unused history I/O on the critical path.",
                }],
                "plausible_wrong_implementation": "Reduce the final prompt payload but still execute the history query whose result is discarded.",
                "performance_contract": {
                    "production_entrypoint": "server/webhook.ts#handleWebhook",
                    "terminal_boundary": "server/lifecycle.ts#markProcessed",
                    "inventory_evidence": {
                        "status": "passed",
                        "head_sha": HEAD,
                        "procedure": "Trace all before-terminal operations and classify their branch necessity from the production entrypoint.",
                        "observed": "The inventory includes the core lookup and optional recent-history query.",
                        "evidence": "inventory.log",
                        "evidence_sha256": EVIDENCE_SHA,
                    },
                    "operations": [
                        {
                            "id": "core-lookup",
                            "source": "server/users.ts#loadUser",
                            "stage": "db",
                            "metric": "db_ms",
                            "before_terminal": True,
                            "required_for_contract": True,
                        },
                        {
                            "id": "recent-history",
                            "source": "server/history.ts#loadRecentHistory",
                            "stage": "db",
                            "metric": "db_ms",
                            "before_terminal": True,
                            "required_for_contract": False,
                        },
                    ],
                    "optimized_branches": [{
                        "id": "generic-question",
                        "operations": [
                            {"operation_id": "core-lookup", "needed": True, "expected_invocations": 1, "observed_invocations": 1, "status": "passed"},
                            {"operation_id": "recent-history", "needed": False, "expected_invocations": 0, "observed_invocations": 1, "status": "passed"},
                        ],
                    }],
                    "benchmark": None,
                },
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [control],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "unused non-required operation must prove zero invocations" in proc.stdout


def test_performance_contract_rejects_benchmark_that_omits_productive_wrapper_operation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "requirement-closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-BENCH-PATH",
                "disposition": "covered",
                "source_text": "O harness deve exercitar o mesmo caminho produtivo usado pela aplicação.",
                "requirement_ids": ["REQ-BENCH-PATH"],
            }]
        }), encoding="utf-8")
        control = negative_control("PERF-BENCH-PATH-001", "structural-contract", "benchmark-path-fidelity", "wrapper-operation-omitted")
        control.update({
            "failure_mode": "The benchmark harness bypasses a production wrapper operation and reports a faster path than the application executes.",
            "plausible_wrong_implementation": "Call the inner handler directly, inject a resolved value, and omit the productive wrapper lookup from the benchmark path.",
            "procedure": "Compare the production entrypoint operation inventory with the benchmark harness covered and omitted operation sets.",
            "expected": "Every productive before-terminal operation is covered directly or explicitly bridged with exact-head evidence.",
            "observed": "The benchmark omitted the timezone lookup operation from its covered path.",
        })
        matrix = base / "matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-BENCH-PATH",
                "source_texts": ["O harness deve exercitar o mesmo caminho produtivo usado pela aplicação."],
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{
                    "risk_family": "structural-contract",
                    "surface": "benchmark-path-fidelity",
                    "reason": "A harness can bypass a productive wrapper and still produce valid-looking latency results.",
                }],
                "plausible_wrong_implementation": "Benchmark a lower-level handler and simulate wrapper delay without executing the productive resolution semantics.",
                "performance_contract": {
                    "production_entrypoint": "server/webhook.ts#handleWebhook",
                    "terminal_boundary": "server/lifecycle.ts#markProcessed",
                    "inventory_evidence": {
                        "status": "passed",
                        "head_sha": HEAD,
                        "procedure": "Trace the production entrypoint through wrappers, lookups and the terminal persistence boundary.",
                        "observed": "The inventory contains both user lookup and timezone lookup before the inner handler.",
                        "evidence": "inventory.log",
                        "evidence_sha256": EVIDENCE_SHA,
                    },
                    "operations": [
                        {
                            "id": "user-lookup",
                            "source": "server/users.ts#findUserByPhone",
                            "stage": "db",
                            "metric": "db_ms",
                            "before_terminal": True,
                            "required_for_contract": True,
                        },
                        {
                            "id": "timezone-lookup",
                            "source": "server/timezone.ts#resolveTimezone",
                            "stage": "db",
                            "metric": "db_ms",
                            "before_terminal": True,
                            "required_for_contract": True,
                        },
                    ],
                    "optimized_branches": [],
                    "benchmark": {
                        "mode": "production-direct",
                        "production_entrypoint": "server/webhook.ts#handleWebhook",
                        "harness_entrypoint": "server/webhook.ts#handleWebhook",
                        "covered_operation_ids": ["user-lookup"],
                        "bridged_operation_ids": [],
                        "omitted_operation_ids": ["timezone-lookup"],
                    },
                },
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
                "negative_controls": [control],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "benchmark omits productive operations" in proc.stdout
