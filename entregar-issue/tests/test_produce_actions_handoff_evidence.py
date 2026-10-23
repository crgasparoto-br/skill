"""GitHub Actions reviewed-evidence producer: provenance, fail-closed, exact SHA."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("produce_actions_handoff_evidence",
                                               SCRIPTS / "produce_actions_handoff_evidence.py")
assert spec and spec.loader
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)


def put(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def fixture(tmp_path: Path, *, dossier=True, skipped=False):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "develop")
    git(root, "config", "user.email", "ci@example.invalid")
    git(root, "config", "user.name", "CI Test")
    (root / "README.md").write_text("baseline\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    start = git(root, "rev-parse", "HEAD")

    source = root / ".github" / "handoff-evidence" / "issue-112"
    if dossier:
        source.mkdir(parents=True)
        reviewed = {
            "schema_version": 1,
            "obligations": {"c" * 64: {
                "disposition": "covered", "requirement_ids": ["REQ-1"],
                "inventory_ids": [], "assertion_ids": [],
                "scope_decision": None, "rationale": "Inspected positive and negative behavior.",
            }},
            "controls": {"pass_c": {"status": "passed"}},
        }
        put(source / "reviewed-closure.json", reviewed)
        hashes = {"reviewed-closure.json": hashlib.sha256(
            (source / "reviewed-closure.json").read_bytes()).hexdigest()}
        put(source / "manifest.json", {
            "schema_version": 1, "repository": "team/skill", "issue_number": 112,
            "pull_request_number": 113, "base_ref": "develop",
            "head_ref": "feat/112-producer", "work_item_start_sha": start,
            "evidence_profile": "light", "audit_history": "verified-no-rejection",
            "risk_justification": "Reviewed delivery impacts and assessed its evidence profile.",
            "audit_history_evidence": "Reviewed the issue and PR audit history as of this delivery.",
            "artifact_sha256": hashes,
            "test_bindings": {"REQ-1": {
                "positive": ["suite::positive"], "negative": ["suite::negative"],
                "regression": ["suite::regression"],
            }},
        })
    change = root / "docs" / "change.md"
    change.parent.mkdir()
    change.write_text("Changed contract text\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "material candidate")
    head = git(root, "rev-parse", "HEAD")
    out = tmp_path / "out"
    audit = out / ".audit" / "entregar-issue"
    audit.mkdir(parents=True)
    put(audit / "requirement-closure.json", {
        "schema_version": 3, "specification_snapshot": {},
        "primary_issue_source_id": "SRC-ISSUE-112",
        "source_coverage": [],
        "obligations": [{"id": "OBL-001", "candidate_key": "c" * 64,
                         "source_text": "Must have positive and negative controls.",
                         "disposition": "pending", "requirement_ids": [],
                         "inventory_ids": [], "assertion_ids": [],
                         "scope_decision": None, "rationale": ""}],
        "pass_c": {"status": "pending"},
    })
    ev = tmp_path / "event.json"
    put(ev, {"repository": {"full_name": "team/skill"}, "pull_request": {
        "number": 113, "title": "feat: policy (#112)", "body": "",
        "head": {"ref": "feat/112-producer", "sha": head,
                 "repo": {"full_name": "team/skill"}},
        "base": {"ref": "develop", "sha": start},
    }})
    put(out / "handoff-preflight.json", {"identity": {
        "repository": "team/skill", "issue_number": 112, "pull_request_number": 113,
        "material_head_sha": head, "base_sha": start,
    }})
    log = b"3 passed\n"
    junit = (b"<testsuite><testcase classname='suite' name='positive'>"
             + (b"<skipped/>" if skipped else b"")
             + b"</testcase><testcase classname='suite' name='negative'/>"
             + b"<testcase classname='suite' name='regression'/></testsuite>")
    (out / "pytest-exact-head.log").write_bytes(log)
    (out / "pytest-exact-head.xml").write_bytes(junit)
    put(out / "test-execution-facts.json", {
        "subject_sha": head, "execution": {"exit_code": 0,
                                          "log_sha256": hashlib.sha256(log).hexdigest()},
    })
    index_spec = importlib.util.spec_from_file_location(
        "build_test_candidate_index", SCRIPTS / "build_test_candidate_index.py"
    )
    assert index_spec and index_spec.loader
    indexer = importlib.util.module_from_spec(index_spec)
    index_spec.loader.exec_module(indexer)
    put(out / "test-candidate-index.json",
        indexer.collect(out / "pytest-exact-head.xml", head))
    return root, out, ev, source, head


def test_stages_reviewed_light_bundle_without_declaring_certificate(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    root, out, event, _, head = fixture(tmp_path)
    producer.produce(root, out, event, "develop")
    result = json.loads((out / "certification-inputs.json").read_text())
    assert result["subject_sha"] == head
    assert result["evidence_profile"] == "light"
    assert json.loads((out / "handoff-producer-status.json").read_text())["status"] == \
        "staged-for-independent-validation"
    assert json.loads((out / ".audit/entregar-issue/requirement-closure.json").read_text())[
        "obligations"][0]["disposition"] == "covered"
    assert not (out / ".audit/entregar-issue/handoff-ready.json").exists()


def test_missing_reviewed_evidence_is_blocked_with_candidate_inventory(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    root, out, event, _, _ = fixture(tmp_path, dossier=False)
    with pytest.raises(ValueError, match="reviewed semantic evidence not supplied"):
        producer.produce(root, out, event, "develop")
    inventory = json.loads((out / "semantic-evidence-candidates.json").read_text())
    assert inventory["mapping"] == "UNKNOWN"
    assert inventory["obligations"][0]["candidate_key"] == "c" * 64
    assert not (out / "certification-inputs.json").exists()


def test_missing_review_is_factual_collection_success_not_certification(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    root, out, event, _, head = fixture(tmp_path, dossier=False)
    monkeypatch.setattr(sys, "argv", [
        "producer", "--root", str(root), "--out", str(out),
        "--event", str(event), "--base-ref", "develop",
    ])
    assert producer.main() == 0
    receipt = json.loads((out / "handoff-producer-status.json").read_text())
    worklist = json.loads((out / "evidence-review-worklist.json").read_text())
    assert receipt["status"] == "awaiting-reviewed-evidence"
    assert worklist["subject_sha"] == head
    assert worklist["semantic_control_mapping"] == "UNKNOWN"
    assert worklist["pending_obligations"][0]["disposition"] == "pending-review"
    delta = json.loads((out / "material-change-index.json").read_text())
    assert delta["subject_sha"] == head
    assert "docs/change.md" in delta["changed_paths"]
    assert delta["semantic_test_impact"] == "UNKNOWN"
    assert not (out / "certification-inputs.json").exists()


def test_invalid_reviewed_inputs_fail_collection_not_just_certification(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    root, out, event, source, _ = fixture(tmp_path)
    put(source / "reviewed-closure.json", {"schema_version": 1})
    monkeypatch.setattr(sys, "argv", [
        "producer", "--root", str(root), "--out", str(out),
        "--event", str(event), "--base-ref", "develop",
    ])
    assert producer.main() == 2
    assert json.loads((out / "handoff-producer-status.json").read_text())[
        "status"] == "blocked-invalid-input"


def test_draft_code_growth_is_measured_by_official_exact_diff(tmp_path):
    root, out, _, source, head = fixture(tmp_path)
    report = producer.stage_draft_code_growth(root, out, source, head)
    assert report["status"] == "passed"
    assert report["exit_code"] == 0
    actual = json.loads(
        (out / ".audit/entregar-issue/code-growth.json").read_text())
    assert actual["control_id"] == "CODE-GROWTH-001"
    assert actual["subject_sha"] == head
    assert actual["comparison_base_sha"] == json.loads((source / "manifest.json").read_text())["work_item_start_sha"]
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["work_item_start_sha"] = "fake"
    put(source / "manifest.json", manifest)
    with pytest.raises(ValueError, match="valid work-item start"):
        producer.stage_draft_code_growth(root, out, source, head)


def test_incomplete_review_validates_keys_without_claiming_approval(tmp_path):
    _, out, _, source, _ = fixture(tmp_path)
    starter = json.loads(
        (out / ".audit/entregar-issue/requirement-closure.json").read_text())
    manifest = json.loads((source / "manifest.json").read_text())
    manifest.update(review_state="incomplete", artifact_sha256={}, test_bindings={})
    put(source / "manifest.json", manifest)
    record = json.loads((source / "reviewed-closure.json").read_text())
    record["obligations"]["c" * 64]["disposition"] = "pending"
    put(source / "reviewed-closure.json", record)
    result = producer.validate_incomplete_review(source, starter)
    assert result["pending_obligations"] == 1
    assert result["canonical_candidate_keys_verified"] is True
    record["obligations"]["c" * 64]["disposition"] = "covered"
    put(source / "reviewed-closure.json", record)
    with pytest.raises(ValueError, match="must not claim semantic coverage"):
        producer.validate_incomplete_review(source, starter)
    record["obligations"] = {"d" * 64: record["obligations"].pop("c" * 64)}
    put(source / "reviewed-closure.json", record)
    with pytest.raises(ValueError, match="differs from canonical"):
        producer.validate_incomplete_review(source, starter)


def test_incomplete_review_manifest_is_not_mistaken_for_certified_evidence(tmp_path, monkeypatch):
    root, _, event, source, head = fixture(tmp_path)
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["review_state"] = "incomplete"
    put(source / "manifest.json", manifest)
    # The material source is committed in CI. Isolate review-state semantics here.
    actual_git = producer.git
    monkeypatch.setattr(producer, "git",
                        lambda path, *args: "" if args[:2] == ("status", "--porcelain")
                        else actual_git(path, *args))
    target = {"repository": "team/skill", "issue_number": 112,
              "pull_request_number": 113, "base_ref": "develop", "head_sha": head}
    with pytest.raises(producer.MissingReviewedEvidenceError, match="explicitly incomplete"):
        producer.load_reviewed_manifest(root, source, event, target)
    manifest["review_state"] = "invalid-approval"
    put(source / "manifest.json", manifest)
    with pytest.raises(ValueError, match="unrecognized reviewed evidence state"):
        producer.load_reviewed_manifest(root, source, event, target)


def test_skipped_test_is_not_a_control(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    root, out, event, _, _ = fixture(tmp_path, skipped=True)
    with pytest.raises(ValueError, match="nonpassing positive"):
        producer.produce(root, out, event, "develop")
    assert not (out / "certification-inputs.json").exists()


def test_tampered_reviewed_digest_fails_closed(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    root, out, event, source, _ = fixture(tmp_path)
    put(source / "reviewed-closure.json", {"schema_version": 1})
    with pytest.raises(ValueError, match="clean material HEAD"):
        producer.produce(root, out, event, "develop")


def test_verified_source_also_checks_declared_digest(tmp_path):
    root, _, _, source, _ = fixture(tmp_path)
    manifest = json.loads((source / "manifest.json").read_text())
    put(source / "reviewed-closure.json", {"schema_version": 1})
    with pytest.raises(ValueError, match="digest mismatch"):
        producer.verified_source(root, source, "reviewed-closure.json", manifest["artifact_sha256"])


def test_tampered_runner_provenance_is_rejected(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    root, out, event, _, _ = fixture(tmp_path)
    (out / "pytest-exact-head.log").write_bytes(b"fake passing text")
    with pytest.raises(ValueError, match="attestation failed"):
        producer.produce(root, out, event, "develop")


def test_forged_candidate_index_is_rejected(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    root, out, event, _, _ = fixture(tmp_path)
    index_file = out / "test-candidate-index.json"
    index = json.loads(index_file.read_text())
    index["tests"][0]["status"] = "passed" if index["tests"][0]["status"] != "passed" else "skipped"
    put(index_file, index)
    with pytest.raises(ValueError, match="differs from exact-head JUnit"):
        producer.produce(root, out, event, "develop")


def test_immutable_obligation_identity_cannot_be_rewritten():
    starter = {"schema_version": 3, "specification_snapshot": {},
               "primary_issue_source_id": "SRC-ISSUE",
               "source_coverage": [], "obligations": [
                   {"id": "OBL-001", "candidate_key": "c" * 64, "disposition": "pending"}],
               "pass_c": {}}
    with pytest.raises(ValueError, match="inventory incomplete"):
        producer.merge_closure(starter, {"schema_version": 1, "obligations": {}, "controls": {"pass_c": {}}})
    with pytest.raises(ValueError, match="fields invalid"):
        producer.merge_closure(starter, {"schema_version": 1, "obligations": {
            "c" * 64: {"id": "OBL-999"}}, "controls": {"pass_c": {}}})


def test_identity_substitution_is_scoped_to_identity_fields():
    assert producer.bind_identity({"head_sha": "__MATERIAL_HEAD_SHA__",
                                   "nested": [{"base_sha": "__WORK_ITEM_START_SHA__"}]},
                                  "a" * 40, "b" * 40) == {
        "head_sha": "a" * 40, "nested": [{"base_sha": "b" * 40}]}
    with pytest.raises(ValueError, match="outside a declared identity"):
        producer.bind_identity({"control_evidence": "__MATERIAL_HEAD_SHA__"}, "a" * 40, "b" * 40)


def test_approved_review_cannot_stage_pending_obligations():
    closure = {"obligations": [
        {"id": "OBL-001", "disposition": "covered"},
        {"id": "OBL-002", "disposition": "pending"},
        {"id": "OBL-003", "disposition": "blocked"},
    ]}
    with pytest.raises(producer.MissingReviewedEvidenceError,
                       match="2 unresolved obligations .*OBL-002, OBL-003"):
        producer.require_complete_semantic_review(closure)


def test_approved_review_can_explicitly_exclude_nonapplicable_obligation():
    producer.require_complete_semantic_review({"obligations": [
        {"id": "OBL-001", "disposition": "covered"},
        {"id": "OBL-002", "disposition": "not-applicable"},
    ]})
