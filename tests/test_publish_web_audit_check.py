"""Independent signed web-audit publisher contract tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_web_audit_check.py"
spec = importlib.util.spec_from_file_location("publish_web_audit_check", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
HEAD = "a" * 40
BASE = "b" * 40
PREVIEW = "c" * 40


def producer_run():
    return {
        "repository": {"full_name": "org/repo"},
        "path": ".github/workflows/produce-independent-audit.yml@main",
        "event": "workflow_run",
        "status": "completed",
        "conclusion": "success",
    }


def test_source_must_be_trusted_workflow(monkeypatch):
    monkeypatch.setattr(gate, "github", lambda *_: producer_run())
    gate.verify_producer("org/repo", 11, "token")
    for field, value in [
        ("event", "workflow_dispatch"),
        ("path", ".github/workflows/other.yml@main"),
        ("conclusion", "failure"),
        ("status", "in_progress"),
        ("repository", {"full_name": "foreign/repo"}),
    ]:
        run = producer_run()
        run[field] = value
        monkeypatch.setattr(gate, "github", lambda *_args, run=run: run)
        with pytest.raises(ValueError, match="trusted"):
            gate.verify_producer("org/repo", 11, "token")


def test_association_requires_unique_current_pr_and_canonical_issue(monkeypatch):
    pr = {
        "number": 5,
        "state": "open",
        "head": {"sha": HEAD},
        "base": {"ref": "develop", "sha": BASE},
        "body": "Closes #127",
        "merge_commit_sha": PREVIEW,
    }
    def fake_api(repo, suffix, token):
        return [pr] if suffix.startswith("commits/") else pr
    monkeypatch.setattr(gate, "github", fake_api)
    assert gate.discover_target("org/repo", {"head_sha": HEAD, "issue": 127}, "token") == pr
    with pytest.raises(ValueError, match="issue"):
        gate.discover_target("org/repo", {"head_sha": HEAD, "issue": 125}, "token")


def test_ambiguous_pr_association_cannot_authorize_merge(monkeypatch):
    pr = {"state": "open", "number": 5, "head": {"sha": HEAD}, "base": {"ref": "develop"}}
    monkeypatch.setattr(gate, "github", lambda *_: [pr, dict(pr, number=6)])
    with pytest.raises(ValueError, match="exactly one"):
        gate.discover_target("org/repo", {"head_sha": HEAD}, "token")


def test_publisher_never_accepts_wrong_status():
    with pytest.raises(ValueError, match="invalid"):
        gate.publish_check("org/repo", HEAD, "neutral", "https://github.com", "note", "token")
    with pytest.raises(ValueError, match="invalid"):
        gate.publish_check("org/repo", "short", "success", "https://github.com", "note", "token")


def test_publisher_never_publishes_to_foreign_head(monkeypatch):
    calls = []
    def api(repo, suffix, token, body):
        calls.append(body)
        return {"conclusion": body["conclusion"]}
    monkeypatch.setattr(gate, "call_api", api)
    gate.publish_check("org/repo", HEAD, "failure", "https://github.com", "bad", "token")
    assert calls[0]["head_sha"] == HEAD
    assert calls[0]["conclusion"] == "failure"
    assert calls[0]["name"] == gate.CHECK_NAME
