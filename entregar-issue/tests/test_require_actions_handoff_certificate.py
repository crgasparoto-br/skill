"""Separation contract: technical evidence is never a certification receipt."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "require_actions_handoff_certificate.py"
spec = importlib.util.spec_from_file_location("require_actions_handoff_certificate", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
HEAD = "a" * 40


def put(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(tmp_path: Path, *, state: str = "blocked") -> tuple[Path, Path]:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    event = tmp_path / "event.json"
    put(event, {"repository": {"full_name": "team/repo"}, "pull_request": {
        "number": 113, "head": {"sha": HEAD, "repo": {"full_name": "team/repo"}},
        "base": {"ref": "develop", "sha": "b" * 40},
    }})
    put(evidence / "handoff-preflight.json", {"identity": {
        "repository": "team/repo", "pull_request_number": 113,
        "issue_number": 112, "material_head_sha": HEAD,
    }})
    put(evidence / "handoff-certification-status.json", {
        "status": state, "reason": "semantic closures have not been supplied",
        "material_head_sha": HEAD, "terminal_ready": False, "certificate_published": False,
    })
    if state == "certificate-generated":
        put(evidence / ".audit/entregar-issue/handoff-ready.json", {
            "schema_version": 2, "status": "ready",
            "identity": {"material_head_sha": HEAD},
            "subject": {"repository": "team/repo", "issue_number": 112,
                        "pull_request_number": 113, "base_ref": "develop"},
            "certificate_commit_policy": {"mode": "result-only-child"},
        })
    if state == "certificate-generated":
        put(evidence / ".audit/entregar-issue/requirement-closure.json",
            {"obligations": []})
    return evidence, event


def test_missing_semantic_closure_is_blocked_even_when_technical_facts_exist(tmp_path):
    evidence, event = fixture(tmp_path)
    with pytest.raises(ValueError, match="semantic certification BLOCKED"):
        gate.verify(evidence, event, "develop")


def test_certificate_generated_requires_exact_issue_head_and_result_only_policy(tmp_path):
    evidence, event = fixture(tmp_path, state="certificate-generated")
    gate.verify(evidence, event, "develop")
    certificate = evidence / ".audit/entregar-issue/handoff-ready.json"
    value = json.loads(certificate.read_text())
    value["subject"]["issue_number"] = 113
    put(certificate, value)
    with pytest.raises(ValueError, match="certificate body"):
        gate.verify(evidence, event, "develop")


def test_stale_or_misleading_receipt_fails_closed(tmp_path):
    evidence, event = fixture(tmp_path, state="certificate-generated")
    receipt = evidence / "handoff-certification-status.json"
    value = json.loads(receipt.read_text())
    value["material_head_sha"] = "b" * 40
    put(receipt, value)
    with pytest.raises(ValueError, match="different material SHA"):
        gate.verify(evidence, event, "develop")
    value["material_head_sha"] = HEAD
    value["certificate_published"] = True
    put(receipt, value)
    with pytest.raises(ValueError, match="falsely claims"):
        gate.verify(evidence, event, "develop")


def test_partial_handoff_requires_exact_deferred_ledger_and_live_parent(tmp_path, monkeypatch):
    evidence, event = fixture(tmp_path, state="certificate-generated")
    certificate = evidence / ".audit/entregar-issue/handoff-ready.json"
    closure_path = evidence / ".audit/entregar-issue/requirement-closure.json"
    cert = json.loads(certificate.read_text())
    cert["completion"] = {
        "issue_completion": "partial",
        "deferred_obligation_ids": ["OBL-040"],
        "remaining_issue_ids": [112],
        "parent_issue_must_remain_open": True,
    }
    put(certificate, cert)
    put(closure_path, {"obligations": [{"id": "OBL-040", "disposition": "deferred"}]})
    observed = []
    monkeypatch.setattr(gate, "verify_open_parent_issue",
                        lambda repo, issue: observed.append((repo, issue)))
    gate.verify(evidence, event, "develop")
    assert observed == [("team/repo", 112)]
    cert["completion"]["deferred_obligation_ids"] = ["OBL-044"]
    put(certificate, cert)
    with pytest.raises(ValueError, match="every deferred obligation"):
        gate.verify(evidence, event, "develop")
    cert["completion"]["deferred_obligation_ids"] = ["OBL-040"]
    cert["completion"]["remaining_issue_ids"] = []
    put(certificate, cert)
    with pytest.raises(ValueError, match="every deferred obligation"):
        gate.verify(evidence, event, "develop")


def test_partial_handoff_parent_state_requires_authenticated_read(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(ValueError, match="authenticated parent issue read"):
        gate.verify_open_parent_issue("team/repo", 112)


def test_workflow_separates_collecting_and_certifying_without_publish_bypass():
    workflow = yaml.safe_load((ROOT.parents[0] / ".github/workflows/reusable-handoff.yml").read_text())
    jobs = workflow["jobs"]
    collecting = jobs["evidence"]
    certifying = jobs["certification"]
    assert certifying["needs"] == "evidence"
    assert "technical evidence" in collecting["name"].lower()
    assert "certified semantic" in certifying["name"].lower()
    assert any("upload-artifact@" in step.get("uses", "") for step in collecting["steps"])
    assert any("download-artifact@" in step.get("uses", "") for step in certifying["steps"])
    assert any("require_actions_handoff_certificate.py" in step.get("run", "")
               for step in certifying["steps"])
    assert not any("Require full certification" in step.get("name", "")
                   for step in collecting["steps"])
    # Entire producer workflow still fails if the required certificate gate fails.
    publish = yaml.safe_load((ROOT.parents[0] / ".github/workflows/publish-handoff.yml").read_text())
    assert publish["jobs"]["publish"]["if"] .find("conclusion == 'success'") >= 0
