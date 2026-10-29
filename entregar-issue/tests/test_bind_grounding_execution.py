"""Real pytest and adversarial controls for the factual grounding binder."""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
HEAD = "a" * 40
TEST_PATH = "tests/test_example.py"
CASE = TEST_PATH + "::test_positive"
CASE_ID = "tests.test_example::test_positive"
PARAM_CASE = TEST_PATH + "::TestGroup::test_parameter[one::two]"
PARAM_ID = "tests.test_example.TestGroup::test_parameter[one::two]"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


binder = load("bind_grounding_execution")
indexer = load("build_test_candidate_index")


@pytest.fixture
def execution(tmp_path):
    root, out = tmp_path / "repo", tmp_path / "out"
    (root / "tests").mkdir(parents=True)
    out.mkdir()
    (root / TEST_PATH).write_text(
        "import pytest\n"
        "def test_positive():\n    assert 2 + 2 == 4\n"
        "class TestGroup:\n"
        "    @pytest.mark.parametrize('value', ['one::two'])\n"
        "    def test_parameter(self, value):\n        assert value.startswith('one')\n"
        "@pytest.mark.skip(reason='control must remain skipped')\n"
        "def test_skipped():\n    assert False\n"
    )
    junit = out / "pytest-exact-head.xml"
    result = subprocess.run([sys.executable, "-m", "pytest", "-vv", "--color=no", f"--junitxml={junit}"],
                            cwd=root, capture_output=True, check=False, timeout=20)
    assert result.returncode == 0, result.stdout.decode()
    log = result.stdout + result.stderr
    (out / "pytest-exact-head.log").write_bytes(log)
    facts = {"subject_sha": HEAD, "verification": "passed", "execution": {
        "command": "python -m pytest -vv --color=no --junitxml=$EVIDENCE_DIR/pytest-exact-head.xml",
        "exit_code": 0, "log_sha256": binder.sha256(log)}}
    (out / "test-execution-facts.json").write_text(json.dumps(facts))
    index = indexer.collect(junit, HEAD)
    report = {"head_sha": HEAD, "reviewed_coverage": "Preserve this reviewed semantic claim.",
              "test_decisions": [{"path": TEST_PATH, "operation": "modified", "decision": "extend",
                                  "scenario": "A reviewed scenario", "requirement": "REQ-1",
                                  "disposition": "keep-with-justification",
                                  "verification": {"status": "unknown", "reason": binder.PENDING_REASON}}]}
    bindings = {TEST_PATH: [{"case": CASE, "test_case_id": CASE_ID},
                           {"case": PARAM_CASE, "test_case_id": PARAM_ID}]}
    return root, out, report, bindings, index


def bind(execution):
    root, out, report, bindings, index = execution
    return binder.bind_grounding_execution(root, out, report, bindings, HEAD, index)


def test_binds_only_reviewed_execution_fields_from_real_pytest(execution, monkeypatch):
    root, out, original, _, _ = execution
    before = copy.deepcopy(original)
    result = bind(execution)
    assert original == before
    proof = result["test_decisions"][0]["verification"]
    assert proof["status"] == "passed"
    assert proof["reached_tests"] == sorted([CASE, PARAM_CASE])
    source = root / proof["evidence_path"]
    assert source.read_bytes() == (out / proof["evidence_path"]).read_bytes()
    assert binder.sha256(source.read_bytes()) == proof["evidence_sha256"]
    assert "SOURCE_SHA256: pytest-exact-head.xml" in source.read_text()
    restored = copy.deepcopy(result)
    restored["test_decisions"][0]["verification"] = before["test_decisions"][0]["verification"]
    assert restored == before  # No scenario, coverage, decision or disposition inferred.
    monkeypatch.syspath_prepend(str(SCRIPTS))
    validator = load("validate_codebase_grounding")
    errors = []
    validator.check_passed_test_evidence(result["test_decisions"][0], root, HEAD, errors)
    assert not errors
    source.write_bytes(source.read_bytes() + b"tampered\n")
    validator.check_passed_test_evidence(result["test_decisions"][0], root, HEAD, errors)
    assert any("evidence hash mismatch" in error for error in errors)


@pytest.mark.parametrize("mutation", ["absent", "skipped", "mismatched", "duplicate", "log-missing", "log-duplicate", "junit-failed"])
def test_grounding_binding_rejects_unreached_skipped_and_mismatched_cases(execution, mutation):
    root, out, _, bindings, index = execution
    entry = bindings[TEST_PATH][0]
    if mutation in {"absent", "skipped"}:
        name = "test_absent" if mutation == "absent" else "test_skipped"
        entry.update(case=f"{TEST_PATH}::{name}", test_case_id=f"tests.test_example::{name}")
    elif mutation == "mismatched":
        entry["test_case_id"] = PARAM_ID
    elif mutation == "duplicate":
        bindings[TEST_PATH].append(entry.copy())
    elif mutation in {"log-missing", "log-duplicate"}:
        log = out / "pytest-exact-head.log"
        log.write_text("3 passed\n" if mutation == "log-missing" else log.read_text() + f"\n{CASE} PASSED [100%]\n")
        facts_path = out / "test-execution-facts.json"
        facts = json.loads(facts_path.read_text())
        facts["execution"]["log_sha256"] = binder.sha256(log.read_bytes())
        facts_path.write_text(json.dumps(facts))
    elif mutation == "junit-failed":
        junit = out / "pytest-exact-head.xml"
        xml = ET.parse(junit)
        ET.SubElement(xml.find(".//testcase[@name='test_positive']"), "failure")
        xml.write(junit)
        index.clear()
        index.update(indexer.collect(junit, HEAD))
    with pytest.raises(ValueError, match=r"ambiguous repeated|absent, ambiguous, skipped, nonpassing or mismatched"):
        bind(execution)
    assert not (root / ".audit").exists()
    assert not (out / ".audit").exists()


@pytest.mark.parametrize("mutation", ["stale-facts", "stale-index", "log", "junit", "exit", "unknown", "command", "symlink"])
def test_grounding_binding_rejects_tampered_or_stale_execution(execution, mutation, tmp_path):
    root, out, _, _, index = execution
    facts_path = out / "test-execution-facts.json"
    facts = json.loads(facts_path.read_text())
    if mutation == "stale-facts":
        facts["subject_sha"] = "b" * 40
    elif mutation == "stale-index":
        index["subject_sha"] = "b" * 40
    elif mutation in {"log", "junit"}:
        path = out / ("pytest-exact-head.log" if mutation == "log" else "pytest-exact-head.xml")
        path.write_bytes(path.read_bytes() + b"changed")
    elif mutation == "exit":
        facts["execution"]["exit_code"] = 1
    elif mutation == "unknown":
        facts["verification"] = "UNKNOWN"
    elif mutation == "command":
        facts["execution"]["command"] += "\nEXIT_CODE: 0"
    elif mutation == "symlink":
        source = out / "pytest-exact-head.log"
        moved = tmp_path / "outside.log"
        source.rename(moved)
        source.symlink_to(moved)
    facts_path.write_text(json.dumps(facts))
    with pytest.raises(ValueError, match=r"authenticated|unsafe"):
        bind(execution)
    assert not (root / ".audit").exists()


def test_existing_attested_and_unrelated_unknown_decisions_are_preserved(execution):
    root, out, report, _, index = execution
    report["test_decisions"][0]["verification"] = {"status": "passed", "subject_sha": HEAD,
                                                 "evidence_path": "reviewed.log", "evidence_sha256": "b" * 64}
    assert binder.bind_grounding_execution(root, out, report, None, HEAD, index) == report
    report["test_decisions"][0]["verification"] = {"status": "unknown", "reason": "semantic review pending"}
    assert binder.bind_grounding_execution(root, out, report, {}, HEAD, index) == report
    with pytest.raises(ValueError, match="exactly the pending"):
        bind(execution)
    assert not (root / ".audit").exists()


def test_deleted_test_requires_every_explicit_replacement(execution):
    root, out, report, bindings, index = execution
    item = report["test_decisions"][0]
    item.update(path="tests/test_deleted.py", operation="deleted", replacement_tests=[TEST_PATH])
    bindings[item["path"]] = bindings.pop(TEST_PATH)
    assert bind(execution)["test_decisions"][0]["verification"]["status"] == "passed"
    item["replacement_tests"].append("tests/test_unreached.py")
    with pytest.raises(ValueError, match="every replacement"):
        binder.bind_grounding_execution(root, out, report, bindings, HEAD, index)


def test_blocked_decision_cannot_gain_passed_execution(execution):
    root, _, report, _, _ = execution
    report["test_decisions"][0]["decision"] = "not-testable/blocked"
    with pytest.raises(ValueError, match="blocked or not-testable"):
        bind(execution)
    assert not (root / ".audit").exists()


def test_renamed_test_cannot_reuse_execution_of_old_path(execution):
    root, _, report, bindings, _ = execution
    new_path = "tests/test_renamed.py"
    (root / new_path).write_bytes((root / TEST_PATH).read_bytes())
    report["test_decisions"][0].update(path=new_path, operation="renamed", prior_path=TEST_PATH)
    bindings[new_path] = bindings.pop(TEST_PATH)
    with pytest.raises(ValueError, match="mismatched"):
        bind(execution)
    assert not (root / ".audit").exists()


@pytest.mark.parametrize("mutation", ["missing", "hash", "symlink", "parent-symlink", "traversal", "alias"])
def test_execution_proofs_are_published_only_from_verified_paths(execution, mutation, tmp_path):
    root, out, _, _, _ = execution
    report = bind(execution)
    proof = report["test_decisions"][0]["verification"]
    relative = proof["evidence_path"]
    assert binder.grounding_result_paths(root, out, report) == [relative]
    artifact = out / relative
    if mutation == "missing":
        artifact.unlink()
    elif mutation == "hash":
        artifact.write_bytes(b"different")
    elif mutation == "symlink":
        artifact.unlink()
        artifact.symlink_to(root / relative)
    elif mutation == "parent-symlink":
        parent = artifact.parent
        moved = tmp_path / "execution"
        parent.rename(moved)
        parent.symlink_to(moved)
    elif mutation == "traversal":
        proof["evidence_path"] = binder.EXECUTION_PREFIX + "../execution/" + artifact.name
    elif mutation == "alias":
        proof["evidence_path"] = binder.EXECUTION_PREFIX + "./" + artifact.name
    with pytest.raises(ValueError, match=r"missing|digest|symlink|noncanonical"):
        binder.grounding_result_paths(root, out, report)


def test_proof_creation_rejects_unsafe_destination_and_nonexecution_paths(execution, tmp_path):
    root, out, _, _, _ = execution
    (root / ".audit").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlink"):
        bind(execution)
    assert not (out / ".audit").exists()
    for relative in ("other/proof.log", "/tmp/proof.log", "../proof.log"):
        with pytest.raises(ValueError, match=r"prefix|noncanonical"):
            binder.execution_path(root, relative)
