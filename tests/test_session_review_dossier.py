"""Exercise the reviewed issue-127 dossier through the official collector gate."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOSSIER = ROOT / ".github/handoff-evidence/issue-127"
SCRIPTS = ROOT / "entregar-issue/scripts"
SPEC = importlib.util.spec_from_file_location(
    "session_review_dossier_producer", SCRIPTS / "produce_actions_handoff_evidence.py"
)
producer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(producer)


def load(name):
    return json.loads((DOSSIER / name).read_text(encoding="utf-8"))


def starter(tmp_path, transform=lambda value: value):
    body = transform((DOSSIER / "reviewed-source-issue.md").read_text(encoding="utf-8"))
    source = tmp_path / "issue.txt"
    source.write_text(body, encoding="utf-8")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "schema_version": 1, "repository": "crgasparoto-br/skill", "issue": 127,
        "primary_source_id": "SRC-ISSUE-127", "sources": [{
            "id": "SRC-ISSUE-127", "kind": "issue-body", "textual": True,
            "path": source.name, "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }],
    }), encoding="utf-8")
    result = tmp_path / "closure.json"
    subprocess.run([
        sys.executable, str(SCRIPTS / "init_requirement_closure.py"),
        "--specification-snapshot", str(snapshot), "--out", str(result),
    ], check=True, capture_output=True, text=True)
    return json.loads(result.read_text(encoding="utf-8"))


def passed_index(bindings):
    return {case: "passed" for groups in bindings.values() for cases in groups.values() for case in cases}


def test_current_dossier_reconciles_all_canonical_candidates(tmp_path):
    canonical = starter(tmp_path)
    assert len(canonical["obligations"]) == 16
    merged = producer.merge_closure(copy.deepcopy(canonical), load("reviewed-closure.json"))
    immutable = ("candidate_key", "source_id", "source_sha256", "source_line", "source_text", "flags")
    assert [tuple(row[key] for key in immutable) for row in merged["obligations"]] == [
        tuple(row[key] for key in immutable) for row in canonical["obligations"]
    ]
    bindings = load("manifest.json")["test_bindings"]
    producer.validate_test_bindings(bindings, merged, passed_index(bindings))


@pytest.mark.parametrize("mutation", ["replace", "add", "remove"])
def test_changed_canonical_contract_rejects_reviewed_overlay(tmp_path, mutation):
    def change(body):
        if mutation == "replace":
            return body.replace("operator-attested-session-review", "different-assurance-contract")
        if mutation == "add":
            return body + "\n## Requisitos adicionais\n\n- [ ] R127-14 — Validar uma nova evidencia antes do handoff.\n"
        return "\n".join(line for line in body.splitlines() if "R127-05" not in line)

    with pytest.raises(ValueError, match="inventory incomplete"):
        producer.merge_closure(starter(tmp_path, change), load("reviewed-closure.json"))


def test_m2_is_excluded_from_implementation_bindings_and_retains_parent(tmp_path):
    merged = producer.merge_closure(starter(tmp_path), load("reviewed-closure.json"))
    deferred = [row for row in merged["obligations"] if row["disposition"] == "deferred"]
    assert len(deferred) == 2
    assert all(row["source_line"] in (28, 29) for row in deferred)
    for row in deferred:
        decision = row["scope_decision"]
        assert decision["decision_source_id"] == "SRC-ISSUE-127"
        assert decision["decision_source_sha256"] == row["source_sha256"]
        assert decision["target_issue"] == 127
        assert decision["parent_issue_must_remain_open"] is True
        assert "33" in decision["decision_locator"]
    bindings = load("manifest.json")["test_bindings"]
    assert not {"R127-12", "R127-13"}.intersection(bindings)
    extra = {**bindings, "R127-12": next(iter(bindings.values()))}
    with pytest.raises(ValueError, match="every covered requirement"):
        producer.validate_test_bindings(extra, merged, passed_index(extra))


@pytest.mark.parametrize("state", ["missing", "failed", "skipped"])
def test_dossier_cannot_promote_unexecuted_controls(tmp_path, state):
    merged = producer.merge_closure(starter(tmp_path), load("reviewed-closure.json"))
    bindings = load("manifest.json")["test_bindings"]
    tests = passed_index(bindings)
    target = bindings["R127-11"]["negative"][0]
    if state == "missing":
        del tests[target]
    else:
        tests[target] = state
    with pytest.raises(ValueError, match="unreached/skipped/nonpassing"):
        producer.validate_test_bindings(bindings, merged, tests)


def test_complete_dossier_passes_official_source_location_gate(tmp_path):
    """A blocked remediation ledger must not mask invalid downstream citations."""
    merged = producer.merge_closure(starter(tmp_path), load("reviewed-closure.json"))
    source_digest = hashlib.sha256((DOSSIER / "reviewed-source-issue.md").read_bytes()).hexdigest()
    assert {row["source_sha256"] for row in merged["obligations"]} == {source_digest}
    closure = tmp_path / "requirement-closure.json"
    closure.write_text(json.dumps(merged), encoding="utf-8")
    inputs = [closure, *(DOSSIER / name for name in (
        "requirement-attack-matrix.json", "risk-saturation.json", "inherited-controls.json"
    ))]
    bindings = load("manifest.json")["test_bindings"]
    matrix = load("requirement-attack-matrix.json")
    for row in matrix["requirements"]:
        identities = {case for cases in bindings[row["requirement_id"]].values() for case in cases}
        controls = [row["positive_control"], *row["negative_controls"], *row["regression_controls"]]
        for control in controls:
            cases = [control, *control.get("sibling_cases", [])]
            for case in cases:
                identity = case.get("junit_case")
                if identity is None:
                    assert case.get("control_type") == "procedure"
                    continue
                assert set(identity) == {"classname", "name"}
                assert identity["classname"] + "::" + identity["name"] in identities
    command = [sys.executable, str(SCRIPTS / "validate_evidence_source_locations.py"),
               "--repository-root", str(ROOT)]
    for path in inputs:
        command.extend(["--evidence", str(path)])
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "READY: validated" in result.stdout


@pytest.fixture
def auditor_saturation_packet(tmp_path):
    head = "a" * 40
    command = [sys.executable, str(ROOT / "auditar-issue/scripts/check_delivery_saturation.py"),
               "--head-sha", head]
    for flag, name in (("--attack-matrix", "requirement-attack-matrix.json"),
                       ("--risk-saturation", "risk-saturation.json"),
                       ("--inherited-controls", "inherited-controls.json")):
        path = tmp_path / name
        value = producer.bind_identity(load(name), head, load("manifest.json")["work_item_start_sha"])
        path.write_text(json.dumps(value), encoding="utf-8")
        command.extend([flag, str(path)])
    return command, tmp_path / "risk-saturation.json"


def test_complete_dossier_passes_official_auditor_saturation(auditor_saturation_packet):
    command, _ = auditor_saturation_packet
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "READY: delivery packet is saturated" in result.stdout


@pytest.mark.parametrize("mutation", ["missing", "not-applicable"])
def test_dossier_rejects_unsaturated_active_inherited_family(auditor_saturation_packet, mutation):
    command, path = auditor_saturation_packet
    risk = json.loads(path.read_text(encoding="utf-8"))
    family = next(item for item in risk["families"] if item["family"] == "semantic-effect")
    if mutation == "missing":
        risk["families"].remove(family)
    else:
        family.update({"applicable": False, "status": "not-applicable"})
    path.write_text(json.dumps(risk), encoding="utf-8")
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "active inherited control INHERITED-R127-03 requires risk family semantic-effect" in result.stdout
