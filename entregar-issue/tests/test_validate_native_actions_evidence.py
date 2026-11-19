"""Fail-closed native evidence gateway; no positive result is an independent review."""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
native = importlib.import_module("validate_native_actions_evidence")


BASE, HEAD, PREVIEW = "b" * 40, "a" * 40, "c" * 40
BODY = "## Critérios de aceite\n- [ ] Validar contrato\n"


def write(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


@pytest.fixture
def proof(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    event = tmp_path / "event.json"
    write(event, {"repository": {"full_name": "owner/repository"},
                  "pull_request": {"number": 199, "title": "feat #198", "body": "Refs #198",
                                   "head": {"sha": HEAD, "repo": {"full_name": "owner/repository"}},
                                   "base": {"ref": "develop", "sha": BASE},
                                   "merge_commit_sha": PREVIEW}})
    monkeypatch.setattr(native, "read_event", lambda *_: ("owner/repository", 199, 198, HEAD, BASE))
    transport = {"mode": "native-github-audit", "legacy_handoff_required": False}
    monkeypatch.setattr(native, "resolve", lambda *_: transport)
    monkeypatch.setattr(native, "issue_body", lambda *_: BODY)
    monkeypatch.setattr(native, "require_event_merge_preview", lambda *_: PREVIEW)
    previews = []
    monkeypatch.setattr(native, "require_equivalent_merge_previews", lambda *args:
                        previews.append(args))
    write(evidence / "audit-transport.json", transport)
    (evidence / "issue-body.md").write_text(BODY, encoding="utf-8")
    write(evidence / "handoff-preflight.json", {
        "identity": {"repository": "owner/repository", "issue_number": 198,
                     "pull_request_number": 199, "material_head_sha": HEAD,
                     "base_sha": BASE, "merge_preview_sha": PREVIEW},
        "base_ref": "develop",
        "source": {"issue_body_sha256": hashlib.sha256(BODY.encode()).hexdigest()}})
    source = json.loads(event.read_text())["pull_request"]
    write(evidence / "certification-event.json", {
        "repository": {"full_name": "owner/repository"},
        "pull_request": {"number": 199, "title": source["title"], "body": source["body"],
                         "head": {"sha": HEAD, "repo": {"full_name": "owner/repository"}},
                         "base": {"ref": "develop", "sha": BASE},
                         "merge_commit_sha": PREVIEW}})
    log = evidence / "pytest-exact-head.log"
    log.write_text("1 passed\n", encoding="utf-8")
    write(evidence / "test-execution-facts.json", {
        "subject_sha": HEAD, "verification": "passed",
        "execution": {"command": "python -m pytest", "exit_code": 0,
                      "log_path": log.name, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}})
    junit = evidence / "pytest-exact-head.xml"
    junit.write_text('<testsuite><testcase classname="tests.unit" name="test_good"/></testsuite>',
                     encoding="utf-8")
    write(evidence / "test-candidate-index.json", native.collect(junit, HEAD))
    return tmp_path, evidence, event, previews


def test_exact_sha_native_proof_does_not_self_approve(proof):
    root, evidence, event, previews = proof
    receipt = native.verify(root, evidence, event, "develop")
    assert receipt["status"] == "verified-technical-evidence"
    assert receipt["material_head_sha"] == HEAD
    assert receipt["test_count"] == 1
    assert receipt["semantic_certification"] == "NOT_ASSERTED"
    assert receipt["independent_review"] == "NOT_ASSERTED"
    assert len(previews) == 1


def test_legacy_mode_cannot_claim_native_readiness(proof, monkeypatch):
    root, evidence, event, _ = proof
    monkeypatch.setattr(native, "resolve", lambda *_: {"mode": "certified-handoff"})
    with pytest.raises(ValueError, match="cannot replace required legacy"):
        native.verify(root, evidence, event, "develop")


@pytest.mark.parametrize("name,field,value", [
    ("audit-transport.json", "mode", "certified-handoff"),
    ("handoff-preflight.json", "base_ref", "main"),
    ("test-execution-facts.json", "subject_sha", "f" * 40),
    ("test-candidate-index.json", "requirement_mapping", "APPROVED"),
])
def test_tampered_record_does_not_validate(proof, name, field, value):
    root, evidence, event, _ = proof
    path = evidence / name
    data = json.loads(path.read_text())
    data[field] = value
    write(path, data)
    with pytest.raises(ValueError):
        native.verify(root, evidence, event, "develop")


@pytest.mark.parametrize("name,field,value", [
    ("handoff-preflight.json", "issue_number", 123),
    ("handoff-preflight.json", "material_head_sha", "f" * 40),
    ("handoff-preflight.json", "base_sha", "f" * 40),
    ("handoff-preflight.json", "merge_preview_sha", "f" * 40),
])
def test_tampered_preflight_identity_does_not_validate(proof, name, field, value):
    root, evidence, event, _ = proof
    path = evidence / name
    data = json.loads(path.read_text())
    data["identity"][field] = value
    write(path, data)
    with pytest.raises(ValueError):
        native.verify(root, evidence, event, "develop")


@pytest.mark.parametrize("field", ["repository", "pull_request"])
def test_tampered_recorded_event_does_not_validate(proof, field):
    root, evidence, event, _ = proof
    path = evidence / "certification-event.json"
    data = json.loads(path.read_text())
    data[field] = {"spoof": "malicious"}
    write(path, data)
    with pytest.raises(ValueError):
        native.verify(root, evidence, event, "develop")


def test_changed_live_issue_blocks_old_technical_evidence(proof, monkeypatch):
    root, evidence, event, _ = proof
    monkeypatch.setattr(native, "issue_body", lambda *_: BODY + "modified")
    with pytest.raises(ValueError, match="canonical GitHub issue body"):
        native.verify(root, evidence, event, "develop")


@pytest.mark.parametrize("tamper", ["badlog", "failed", "command", "skipped", "doctype", "xmlchanged"])
def test_invalid_test_or_junit_evidence_is_rejected(proof, tamper):
    root, evidence, event, _ = proof
    facts = evidence / "test-execution-facts.json"
    log = evidence / "pytest-exact-head.log"
    junit = evidence / "pytest-exact-head.xml"
    if tamper == "badlog":
        log.write_text("not the tested output")
    if tamper == "failed":
        data = json.loads(facts.read_text())
        data["execution"]["exit_code"] = 1
        write(facts, data)
    if tamper == "command":
        data = json.loads(facts.read_text())
        data["execution"]["command"] = ""
        write(facts, data)
    if tamper == "skipped":
        junit.write_text('<testsuite><testcase classname="tests.unit" name="test_good"><skipped/></testcase></testsuite>')
    if tamper == "doctype":
        junit.write_text('<!DOCTYPE foo><testsuite><testcase classname="tests.unit" name="test_good"/></testsuite>')
    if tamper == "xmlchanged":
        junit.write_text('<testsuite><testcase classname="tests.unit" name="test_bad"/></testsuite>')
    with pytest.raises(ValueError):
        native.verify(root, evidence, event, "develop")


def test_symlinked_evidence_cannot_be_verified(proof):
    root, evidence, event, _ = proof
    index = evidence / "test-candidate-index.json"
    target = evidence / "payload.json"
    index.rename(target)
    index.symlink_to(target)
    with pytest.raises(ValueError, match="missing"):
        native.verify(root, evidence, event, "develop")
