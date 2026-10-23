"""Trusted post-certification publisher: only exact, allowlisted GitHub evidence."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts" / "publish_actions_handoff.py"
spec = importlib.util.spec_from_file_location("publish_actions_handoff", PATH)
assert spec and spec.loader
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
HEAD = "a" * 40
BASE = "b" * 40


def test_allowlist_blocks_material_paths_and_unexpected_names():
    with pytest.raises(ValueError, match="non-audit"):
        publisher.allowed_paths({"certificate_commit_policy": {
            "mode": "result-only-child", "allowed_paths": [publisher.CERTIFICATE, "src/app.py"]}})
    with pytest.raises(ValueError, match="unsafe"):
        publisher.allowed_paths({"certificate_commit_policy": {
            "mode": "result-only-child",
            "allowed_paths": [publisher.CERTIFICATE, ".audit/entregar-issue/../escape.json"]}})
    assert publisher.allowed_paths({"certificate_commit_policy": {
        "mode": "result-only-child",
        "allowed_paths": [publisher.CERTIFICATE, ".audit/entregar-issue/requirement-closure.json"],
    }})[0].startswith(publisher.PREFIX)


def test_bundle_paths_reject_symlink_and_absence(tmp_path):
    p = tmp_path / publisher.CERTIFICATE
    p.parent.mkdir(parents=True)
    p.write_text("{}")
    assert publisher.safe_bundle_path(tmp_path, publisher.CERTIFICATE) == p
    with pytest.raises(ValueError, match="missing or unsafe"):
        publisher.safe_bundle_path(tmp_path, ".audit/entregar-issue/nonexistent.json")
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}")
    alias = tmp_path / ".audit" / "entregar-issue" / "alias.json"
    alias.symlink_to(outside)
    with pytest.raises(ValueError, match="missing or unsafe"):
        publisher.safe_bundle_path(tmp_path, ".audit/entregar-issue/alias.json")


def test_reject_invalid_workflow_event_before_api(monkeypatch):
    monkeypatch.setattr(publisher, "api_get", lambda *_: pytest.fail("network must not be reached"))
    event = {"repository": {"full_name": "team/skill"}, "workflow_run": {
        "status": "completed", "conclusion": "failure", "event": "pull_request",
        "head_sha": HEAD, "pull_requests": [{"number": 113}],
    }}
    with pytest.raises(ValueError, match="only one completed"):
        publisher.target_from_event(event)


def test_reject_live_pr_sha_drift(monkeypatch):
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "state": "open", "head": {"sha": BASE, "ref": "feat/112",
        "repo": {"full_name": "team/skill"}},
        "base": {"sha": BASE, "ref": "develop"},
    })
    event = {"repository": {"full_name": "team/skill"}, "workflow_run": {
        "status": "completed", "conclusion": "success", "event": "pull_request",
        "path": ".github/workflows/handoff-evidence.yml",
        "head_sha": HEAD, "pull_requests": [{"number": 113}],
    }}
    with pytest.raises(ValueError, match="changed identity"):
        publisher.target_from_event(event)


def test_material_ci_requires_every_observed_check_green(monkeypatch):
    def response(status):
        return {"total_count": 3, "workflow_runs": [
            {"workflow_id": index, "name": name, "head_sha": HEAD,
             "event": "pull_request", "pull_requests": [{"number": 113}],
             "run_number": 1, "status": "completed", "conclusion": status if index == 3 else "success"}
            for index, name in enumerate((
                "Validate skills", "Validate GitHub Audit MCP",
                "Collect and certify exact-SHA handoff"), 1)
        ]}
    monkeypatch.setattr(publisher, "api_get", lambda *_: response("failure"))
    with pytest.raises(ValueError, match="not terminal success"):
        publisher.check_material_ci("team/skill", HEAD, 113)
    monkeypatch.setattr(publisher, "api_get", lambda *_: response("success"))
    publisher.check_material_ci("team/skill", HEAD, 113)

def test_parent_control_snapshots_are_immutable(tmp_path):
    source = tmp_path / "source"
    audit = source / ".audit" / "entregar-issue"
    audit.mkdir(parents=True)
    (audit / "inherited-controls.json").write_bytes(b'{"v":"material"}')
    destination = publisher.material_parent_snapshots(source, tmp_path)
    assert (destination / "inherited-controls.json").read_bytes() == b'{"v":"material"}'
    (audit / "inherited-controls.json").write_bytes(b'{"v":"new"}')
    assert (destination / "inherited-controls.json").read_bytes() == b'{"v":"material"}'

def test_trusted_publisher_accepts_configured_producer_and_base(monkeypatch):
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "state": "open",
        "head": {"sha": HEAD, "ref": "feat/112", "repo": {"full_name": "team/skill"}},
        "base": {"sha": BASE, "ref": "integration"},
    })
    event = {"repository": {"full_name": "team/skill"}, "workflow_run": {
        "status": "completed", "conclusion": "success", "event": "pull_request",
        "path": ".github/workflows/caller.yml",
        "head_sha": HEAD, "pull_requests": [{"number": 113}],
    }}
    with pytest.raises(ValueError, match="only one completed"):
        publisher.target_from_event(event)
    assert publisher.target_from_event(event, "integration", ".github/workflows/caller.yml") == (
        "team/skill", 113, HEAD, BASE
    )
    with pytest.raises(ValueError, match="producer workflow path"):
        publisher.target_from_event(event, "integration", "../caller.yml")


def test_consumer_required_check_names_are_enforced(monkeypatch):
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "total_count": 1,
        "workflow_runs": [{
            "workflow_id": 3, "name": "My custom quality check",
            "head_sha": HEAD, "event": "pull_request", "pull_requests": [{"number": 113}],
            "run_number": 1, "status": "completed", "conclusion": "success",
        }],
    })
    publisher.check_material_ci("team/skill", HEAD, 113, {"My custom quality check"})
    with pytest.raises(ValueError, match="not present"):
        publisher.check_material_ci("team/skill", HEAD, 113, {"Other required check"})
