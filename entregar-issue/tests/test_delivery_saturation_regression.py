from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from risk_inference import derive_families_from_text, derive_surfaces

HEAD = "d" * 40
EVIDENCE_SHA = hashlib.sha256(b"evidence").hexdigest()
CANONICAL = [
    "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
    "temporal-consistency", "temporal-destination", "concurrency-atomicity",
    "idempotency", "rollback", "historical-immutability", "structural-contract", "documentation",
]


def run(script: str, *args: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def control(control_id: str, family: str, surface: str, dimension: str) -> dict:
    return {
        "id": control_id,
        "status": "passed",
        "head_sha": HEAD,
        "subject_sha": HEAD,
        "control_type": "scenario",
        "procedure": "Execute a divergent exact-head scenario against the definitive boundary.",
        "expected": "The invalid branch is rejected without mutating persistent state.",
        "observed": "The candidate rejected the divergent branch and persisted zero rejected effects.",
        "evidence": "evidence.json",
        "evidence_sha256": EVIDENCE_SHA,
        "risk_family": family,
        "surface": surface,
        "dimension": dimension,
        "sibling_cases": [
            {"id": "a", "surface": surface, "dimension": dimension + "-a", "status": "passed"},
            {"id": "b", "surface": surface, "dimension": dimension + "-b", "status": "passed"},
        ],
    }


def test_risk_inference_preserves_material_commercial_historical_and_lifecycle_families() -> None:
    text = "\n".join([
        "Mudança posterior de plano não reatribui histórico.",
        "Qualquer cobrança futura exige autorização explícita, desativação e rollback.",
        "Reconhecer receita proporcionalmente ao período de prestação do serviço e por competência.",
        "Limitação temporária admite uma extensão adicional com aprovação de segundo administrador.",
    ])
    families = derive_families_from_text(text)
    assert {"historical-immutability", "authorization", "rollback", "temporal-consistency", "concurrency-atomicity"} <= families
    surfaces = {(item["risk_family"], item["surface"]) for item in derive_surfaces([text])}
    assert ("historical-immutability", "usage-attribution-history") in surfaces
    assert ("authorization", "future-charge-authorization") in surfaces
    assert ("rollback", "future-charge-rollback") in surfaces
    assert ("temporal-consistency", "economic-competence") in surfaces
    assert ("temporal-consistency", "temporary-limitation-duration") in surfaces
    assert ("concurrency-atomicity", "limitation-lifecycle") in surfaces


def test_risk_inference_treats_explicit_tenant_profile_isolation_as_its_own_family() -> None:
    text = "Tenant e perfil continuam isolados em todos os cenários."
    families = derive_families_from_text(text)
    assert "tenant-isolation" in families
    surfaces = {(item["risk_family"], item["surface"]) for item in derive_surfaces([text])}
    assert ("tenant-isolation", "tenant-scope-isolation") in surfaces


def test_risk_inference_does_not_infer_tenant_isolation_from_profile_mention_alone() -> None:
    text = "O perfil seleciona o período do relatório."
    families = derive_families_from_text(text)
    assert "tenant-isolation" not in families


def test_risk_saturation_rejects_not_applicable_tenant_isolation_required_by_canonical_source() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-ISO",
                "disposition": "covered",
                "source_text": "Tenant e perfil continuam isolados em todos os cenários.",
                "flags": [],
                "requirement_ids": ["REQ"],
            }],
        }), encoding="utf-8")
        matrix = base / "matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ",
                "risk_families": ["authorization"],
                "risk_surfaces": [{
                    "risk_family": "authorization",
                    "surface": "profile-scope-preserved",
                    "reason": "The ordinary profile predicate remains present.",
                }],
                "negative_controls": [control("AUTH", "authorization", "profile-scope-preserved", "profile-filter")],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        risk = base / "risk.json"
        families = []
        for family in CANONICAL:
            applicable = family == "authorization"
            families.append({
                "family": family,
                "applicable": applicable,
                "reason": "Synthetic applicable family." if applicable else "Synthetic non applicable family.",
                "control_ids": ["AUTH"] if applicable else [],
                "dimensions": [{
                    "surface": "profile-scope-preserved",
                    "reason": "The ordinary profile predicate remains present.",
                    "control_ids": ["AUTH"],
                    "status": "passed",
                }] if applicable else [],
                "status": "passed" if applicable else "not-applicable",
            })
        risk.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "families": families,
            "material_families_missing_controls": [],
        }), encoding="utf-8")
        proc = run(
            "validate_risk_saturation.py",
            "--attack-matrix", str(matrix),
            "--risk-saturation", str(risk),
            "--requirement-closure", str(closure),
        )
        assert proc.returncode == 2
        assert "tenant-isolation" in proc.stdout
        assert "tenant-scope-isolation" in proc.stdout


def test_specification_coverage_rejects_lossy_source_text_in_requirement_closure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        source = base / "issue.txt"
        source.write_text(
            "## Regras\n- Retry não duplica consumo.\n- Mudança posterior de plano não reatribui histórico.\n",
            encoding="utf-8",
        )
        snapshot = base / "specification-snapshot.json"
        proc = run(
            "build_specification_snapshot.py",
            "--repository", "owner/repo",
            "--issue", "1",
            "--primary-source-id", "SRC-ISSUE",
            "--source", f"issue-body:SRC-ISSUE:{source}",
            "--out", str(snapshot),
        )
        assert proc.returncode == 0, proc.stdout
        closure = base / "requirement-closure.json"
        proc = run("init_requirement_closure.py", "--specification-snapshot", str(snapshot), "--out", str(closure))
        assert proc.returncode == 0, proc.stdout
        data = json.loads(closure.read_text(encoding="utf-8"))
        for item in data["obligations"]:
            item["disposition"] = "covered"
            item["requirement_ids"] = ["REQ"]
        data["pass_c"].update({
            "status": "passed",
            "obligation_ids": [item["id"] for item in data["obligations"]],
            "reviewed_all_specification_sources": True,
        })
        data["obligations"][0]["source_text"] = "Texto reduzido que omite a regra original."
        closure.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        proc = run(
            "validate_specification_coverage.py",
            "--specification-snapshot", str(snapshot),
            "--requirement-closure", str(closure),
        )
        assert proc.returncode == 2
        assert "source_text differs from canonical specification candidate" in proc.stdout


def test_attack_matrix_requires_documentation_family_when_documentation_consistency_passed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-001", "disposition": "covered",
                "source_text": "Retry não duplica consumo.", "requirement_ids": ["REQ"],
            }],
            "documentation_consistency": {"status": "passed"},
        }), encoding="utf-8")
        matrix = base / "matrix.json"
        neg = control("IDEMP", "idempotency", "duplicate-processing", "replay")
        neg.update({
            "failure_mode": "A repeated callback records the same logical usage twice.",
            "plausible_wrong_implementation": "Insert every callback without checking the stable idempotency identity.",
        })
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ",
                "source_texts": ["Retry não duplica consumo."],
                "risk_families": ["idempotency"],
                "risk_surfaces": [{
                    "risk_family": "idempotency", "surface": "duplicate-processing",
                    "reason": "A repeated callback can duplicate one logical effect.",
                }],
                "plausible_wrong_implementation": "Insert every callback without checking a stable idempotency key.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.json"},
                "negative_controls": [neg],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.json"}],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run("validate_requirement_attack_matrix.py", "--requirement-closure", str(closure), "--attack-matrix", str(matrix))
        assert proc.returncode == 2
        assert "documentation consistency passed but attack matrix omits documentation risk family" in proc.stdout


def test_risk_saturation_rejects_family_hidden_while_active_inherited_control_requires_it() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix = base / "matrix.json"
        matrix.write_text(json.dumps({
            "schema_version": 1, "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ",
                "risk_families": ["structural-contract"],
                "risk_surfaces": [{"risk_family": "structural-contract", "surface": "material-composition", "reason": "The handoff must bind the final material candidate."}],
                "negative_controls": [control("STRUCT", "structural-contract", "material-composition", "final-head")],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        risk = base / "risk.json"
        families = []
        for family in CANONICAL:
            applicable = family == "structural-contract"
            families.append({
                "family": family,
                "applicable": applicable,
                "reason": "Synthetic material family." if applicable else "Synthetic non applicable family.",
                "control_ids": ["STRUCT"] if applicable else [],
                "dimensions": [{
                    "surface": "material-composition", "reason": "Final material identity is protected.",
                    "control_ids": ["STRUCT"], "status": "passed",
                }] if applicable else [],
                "status": "passed" if applicable else "not-applicable",
            })
        risk.write_text(json.dumps({"schema_version": 1, "head_sha": HEAD, "families": families, "material_families_missing_controls": []}), encoding="utf-8")
        inherited = base / "inherited.json"
        inherited.write_text(json.dumps({
            "schema_version": 1, "head_sha": HEAD,
            "controls": [control("ROLLBACK-INHERITED", "rollback", "future-charge-rollback", "reversible-activation")],
            "unresolved_controls": [],
        }), encoding="utf-8")
        proc = run(
            "validate_risk_saturation.py",
            "--attack-matrix", str(matrix),
            "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited),
        )
        assert proc.returncode == 2
        assert "active inherited controls" in proc.stdout
        assert "rollback" in proc.stdout


def test_inherited_control_cannot_retire_not_applicable_while_canonical_contract_still_requires_family() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        previous = base / "previous.json"
        prior = control("HIST", "historical-immutability", "usage-attribution-history", "later-plan-change")
        previous.write_text(json.dumps({
            "schema_version": 1, "head_sha": "c" * 40,
            "source_audits": [{"kind": "independent-audit-outcome", "finding": "historical-attribution"}],
            "controls": [prior], "unresolved_controls": [],
        }), encoding="utf-8")
        current = base / "current.json"
        current.write_text(json.dumps({
            "schema_version": 1, "head_sha": HEAD,
            "source_audits": [{"kind": "independent-audit-outcome", "finding": "historical-attribution"}],
            "controls": [control("KEEP", "structural-contract", "material-composition", "final-head")],
            "retired_controls": [{
                "id": "HIST", "disposition": "not-applicable",
                "reason": "The delivery claims historical attribution no longer needs an adversarial control.",
                "subject_sha": HEAD,
                "procedure": "Inspect the exact-head contract and attempt to retire the historical control.",
                "expected": "Retirement is allowed only when the canonical contract no longer requires the family.",
                "observed": "The canonical contract still states that later plan changes must preserve history.",
                "evidence": "retirement.json", "evidence_sha256": EVIDENCE_SHA,
            }],
            "unresolved_controls": [],
        }), encoding="utf-8")
        closure = base / "closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-001", "disposition": "covered",
                "source_text": "Mudança posterior de plano não reatribui histórico.",
                "flags": [], "requirement_ids": ["REQ"],
            }],
        }), encoding="utf-8")
        proc = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(current),
            "--head-sha", HEAD,
            "--previous-independent-rejection",
            "--previous-inherited-controls", str(previous),
            "--requirement-closure", str(closure),
        )
        assert proc.returncode == 2
        assert "cannot become not-applicable while canonical requirement closure still requires risk family historical-immutability" in proc.stdout


def test_specification_coverage_rejects_pending_terminal_closure_gate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        source = base / "issue.txt"
        source.write_text("- Implementar o comportamento solicitado.\n", encoding="utf-8")
        snapshot = base / "specification-snapshot.json"
        proc = run(
            "build_specification_snapshot.py",
            "--repository", "owner/repo",
            "--issue", "1",
            "--primary-source-id", "SRC-ISSUE",
            "--source", f"issue-body:SRC-ISSUE:{source}",
            "--out", str(snapshot),
        )
        assert proc.returncode == 0, proc.stdout
        closure = base / "requirement-closure.json"
        proc = run("init_requirement_closure.py", "--specification-snapshot", str(snapshot), "--out", str(closure))
        assert proc.returncode == 0, proc.stdout
        data = json.loads(closure.read_text(encoding="utf-8"))
        obligation = data["obligations"][0]
        obligation["disposition"] = "covered"
        obligation["requirement_ids"] = ["REQ"]
        data["scope_reduction_review"] = {"status": "passed", "matches": []}
        data["pass_c"].update({
            "status": "passed",
            "obligation_ids": [obligation["id"]],
            "reviewed_all_specification_sources": True,
        })
        # The bug class: producer attempts handoff while semantic closure gates remain pending.
        assert data["read_model_closures"]["status"] == "pending"
        closure.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        proc = run(
            "validate_specification_coverage.py",
            "--specification-snapshot", str(snapshot),
            "--requirement-closure", str(closure),
        )
        assert proc.returncode == 2
        assert "read_model_closures gate is still pending" in proc.stdout
        assert "canonical_source_consistency gate is still pending" in proc.stdout
        assert "documentation_consistency gate is still pending" in proc.stdout


def test_inherited_control_rejects_stale_sha_asserted_as_current_in_observed_narrative() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        stale = "a" * 40
        item = control("EXACT-HEAD", "structural-contract", "evidence-freshness", "exact-material-subject")
        item["observed"] = (
            "Normalized provenance and benchmark candidateSha both equal the frozen material head " + stale + "."
        )
        current = base / "inherited.json"
        current.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "controls": [item],
            "unresolved_controls": [],
        }), encoding="utf-8")

        proc = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(current),
            "--head-sha", HEAD,
        )
        assert proc.returncode == 2
        assert "observed narrative asserts non-current SHA(s) as current/exact-head" in proc.stdout
        assert stale in proc.stdout


def test_inherited_control_allows_explicit_historical_sha_but_requires_current_active_claim() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        stale = "a" * 40
        item = control("EXACT-HEAD", "structural-contract", "evidence-freshness", "exact-material-subject")
        item["observed"] = (
            f"Historical stale evidence at {stale} was superseded; "
            f"active exact-head evidence now equals {HEAD}."
        )
        current = base / "inherited.json"
        current.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "controls": [item],
            "unresolved_controls": [],
        }), encoding="utf-8")

        proc = run(
            "validate_inherited_controls.py",
            "--inherited-controls", str(current),
            "--head-sha", HEAD,
        )
        assert proc.returncode == 0, proc.stdout


def test_audit_escape_rejects_stale_sha_asserted_as_active_literal_case() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        stale = "b" * 40
        closure = base / "audit-escape-closure.json"
        closure.write_text(json.dumps({
            "schema_version": 1,
            "escapes": [{
                "escape_id": "ESC-EXACT-HEAD",
                "escape_class": "quantitative-evidence-freshness-substitution",
                "status": "passed",
                "plausible_wrong_implementation": "Reuse an ancestor result and relabel it as exact-head evidence for a later material candidate.",
                "sibling_cases": [
                    {"id": "S1", "status": "passed"},
                    {"id": "S2", "status": "passed"},
                ],
                "prevention_change": {"evidence": "evidence.txt"},
                "detection_change": {"evidence": "evidence.txt"},
                "revalidated_head_sha": HEAD,
                "literal_case": {
                    "status": "passed",
                    "observed": f"Active quantitative evidence now has subject_sha/candidateSha equal to {stale}."
                },
            }],
        }), encoding="utf-8")

        proc = run(
            "validate_audit_escape_lineage.py",
            "--closure", str(closure),
            "--head-sha", HEAD,
        )
        assert proc.returncode == 2
        assert "literal_case.observed asserts non-current SHA(s) as current/exact-head" in proc.stdout
        assert stale in proc.stdout


def test_terminal_closure_rejects_unjustified_not_applicable_bypass() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        source = base / "issue.txt"
        source.write_text("- Exibir histórico consistente usando a fonte canônica atual.\n", encoding="utf-8")
        snapshot = base / "specification-snapshot.json"
        proc = run(
            "build_specification_snapshot.py",
            "--repository", "owner/repo",
            "--issue", "1",
            "--primary-source-id", "SRC-ISSUE",
            "--source", f"issue-body:SRC-ISSUE:{source}",
            "--out", str(snapshot),
        )
        assert proc.returncode == 0, proc.stdout
        closure = base / "requirement-closure.json"
        proc = run("init_requirement_closure.py", "--specification-snapshot", str(snapshot), "--out", str(closure))
        assert proc.returncode == 0, proc.stdout
        data = json.loads(closure.read_text(encoding="utf-8"))
        obligation = data["obligations"][0]
        obligation["disposition"] = "covered"
        obligation["requirement_ids"] = ["REQ"]
        data["read_model_closures"] = {"status": "not-applicable", "applicability_reason": "No read model is needed here despite the history requirement."}
        data["canonical_source_consistency"] = {"status": "not-applicable", "applicability_reason": "No canonical source check is needed despite the canonical-source requirement."}
        data["documentation_consistency"] = {"status": "not-applicable", "applicability_reason": "No documentation transition is present in this synthetic contract."}
        data["structural_invariant_closures"] = {"status": "not-applicable", "applicability_reason": "No structural invariant is present in this synthetic contract."}
        data["scope_reduction_review"] = {"status": "passed", "matches": []}
        data["pass_c"].update({
            "status": "passed",
            "obligation_ids": [obligation["id"]],
            "reviewed_all_specification_sources": True,
        })
        closure.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        proc = run(
            "validate_specification_coverage.py",
            "--specification-snapshot", str(snapshot),
            "--requirement-closure", str(closure),
        )
        assert proc.returncode == 2
        assert "read_model_closures gate cannot be not-applicable for the canonical contract" in proc.stdout
        assert "canonical_source_consistency gate cannot be not-applicable for the canonical contract" in proc.stdout


def test_inherited_control_rejects_current_stale_sha_after_historical_clause() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        historical = "a" * 40
        stale_current = "b" * 40
        item = control("EXACT-HEAD", "structural-contract", "evidence-freshness", "exact-material-subject")
        item["observed"] = (
            f"Historical stale evidence at {historical} was superseded, but active exact-head evidence now equals {stale_current}."
        )
        current = base / "inherited.json"
        current.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "controls": [item],
            "unresolved_controls": [],
        }), encoding="utf-8")
        proc = run("validate_inherited_controls.py", "--inherited-controls", str(current), "--head-sha", HEAD)
        assert proc.returncode == 2
        assert stale_current in proc.stdout


def test_tenant_isolation_surface_requires_distinct_scope_no_leak_control() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-ISO",
                "disposition": "covered",
                "source_text": "Profiles remain isolated with no cross-tenant data leakage.",
                "flags": [],
                "requirement_ids": ["REQ"],
            }],
        }), encoding="utf-8")
        matrix = base / "matrix.json"
        weak = control("ISO", "tenant-isolation", "tenant-scope-isolation", "scope-boundary")
        weak.update({
            "failure_mode": "A profile query could include records outside the expected scope.",
            "plausible_wrong_implementation": "Keep the normal profile filter but never exercise a second scope.",
            "procedure": "Run the ordinary profile-scoped happy path.",
            "expected": "The request succeeds without checking sibling data.",
            "observed": "The ordinary request succeeded.",
        })
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ",
                "obligation_ids": ["OBL-ISO"],
                "source_texts": ["Profiles remain isolated with no cross-tenant data leakage."],
                "risk_families": ["tenant-isolation"],
                "risk_surfaces": [{
                    "risk_family": "tenant-isolation",
                    "surface": "tenant-scope-isolation",
                    "reason": "A sibling scope can leak into a valid-looking scoped response.",
                }],
                "plausible_wrong_implementation": "Filter the common happy path but never prove sibling-scope exclusion.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.json"},
                "negative_controls": [weak],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.json"}],
                "obligation_control_map": [{
                    "obligation_id": "OBL-ISO",
                    "primary_negative_control_id": "ISO",
                }],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--attack-matrix", str(matrix),
        )
        assert proc.returncode == 2
        assert "tenant isolation control does not use deliberately distinct scopes" in proc.stdout
        assert "tenant isolation control does not prove exclusion/no-leak behavior" in proc.stdout


def test_tenant_isolation_surface_accepts_distinct_scope_no_leak_control() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure = base / "closure.json"
        source = "Profiles remain isolated with no cross-tenant data leakage."
        closure.write_text(json.dumps({
            "obligations": [{
                "id": "OBL-ISO",
                "disposition": "covered",
                "source_text": source,
                "flags": [],
                "requirement_ids": ["REQ"],
            }],
        }), encoding="utf-8")
        matrix = base / "matrix.json"
        strong = control("ISO", "tenant-isolation", "tenant-scope-isolation", "sibling-profile-exclusion")
        strong.update({
            "failure_mode": "A query for profile A can accidentally include rows owned by a different profile B.",
            "plausible_wrong_implementation": "Apply the profile predicate on one join but omit it on another joined source.",
            "procedure": "Create deliberately distinct profile A and profile B with conflicting values, query A, and inspect every returned aggregate and item.",
            "expected": "All profile B data is excluded from profile A; no cross-tenant or sibling-profile leakage is observable.",
            "observed": "The query for profile A excluded every profile B row and no sibling-scope value influenced the result.",
        })
        matrix.write_text(json.dumps({
            "schema_version": 1,
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ",
                "obligation_ids": ["OBL-ISO"],
                "source_texts": [source],
                "risk_families": ["tenant-isolation"],
                "risk_surfaces": [{
                    "risk_family": "tenant-isolation",
                    "surface": "tenant-scope-isolation",
                    "reason": "A sibling scope can leak into a valid-looking scoped response.",
                }],
                "plausible_wrong_implementation": "Filter one data source by profile while another source remains unscoped.",
                "positive_control": {"status": "passed", "head_sha": HEAD, "evidence": "positive.json"},
                "negative_controls": [strong],
                "regression_controls": [{"status": "passed", "head_sha": HEAD, "evidence": "regression.json"}],
                "obligation_control_map": [{
                    "obligation_id": "OBL-ISO",
                    "primary_negative_control_id": "ISO",
                }],
            }],
            "uncovered_requirements": [],
        }), encoding="utf-8")
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure", str(closure),
            "--attack-matrix", str(matrix),
        )
        assert proc.returncode == 0, proc.stdout
        assert "READY" in proc.stdout
