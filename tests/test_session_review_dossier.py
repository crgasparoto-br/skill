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
