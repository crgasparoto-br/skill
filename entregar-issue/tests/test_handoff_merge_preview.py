"""Adversarial checks for exact GitHub Actions merge-preview provenance."""
from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

import handoff_merge_preview as target
import pytest

if TYPE_CHECKING:
    from pathlib import Path

BASE = "b" * 40
HEAD = "a" * 40
STALE = "c" * 40
CURRENT = "d" * 40


def event(tmp_path: Path, monkeypatch, preview=STALE) -> Path:
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"repository": {"full_name": "owner/repo"}, "pull_request": {
        "number": 77, "merge_commit_sha": preview,
        "head": {"sha": HEAD}, "base": {"sha": BASE, "ref": "develop"}}}))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/77/merge")
    monkeypatch.setenv("GITHUB_SHA", CURRENT)
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://example.com")
    monkeypatch.setenv("GITHUB_API_URL", "https://api.example.com")
    monkeypatch.setenv("GITHUB_TOKEN", "test-fixture-token")
    return path


def api(monkeypatch, **changes) -> None:
    payload = {"number": 77, "state": "open", "merge_commit_sha": CURRENT,
               "head": {"sha": HEAD}, "base": {"sha": BASE, "ref": "develop"}}
    payload.update(changes)

    def read(request, timeout):
        assert timeout == 15
        assert request.full_url == "https://api.example.com/repos/owner/repo/pulls/77"
        assert request.get_header("Authorization") == "Bearer test-fixture-token"
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(target.urllib.request, "urlopen", read)


@pytest.mark.parametrize("event_preview", [STALE, None])
def test_stale_or_absent_webhook_preview_uses_verified_current_runner_sha(
        tmp_path, monkeypatch, event_preview):
    path = event(tmp_path, monkeypatch, event_preview)
    api(monkeypatch)
    assert target.require_event_merge_preview(path, "owner/repo", 77, HEAD, BASE) == CURRENT


@pytest.mark.parametrize("mutation", [
    {"merge_commit_sha": STALE},
    {"head": {"sha": "e" * 40}},
    {"base": {"sha": "e" * 40, "ref": "develop"}},
    {"base": {"sha": BASE, "ref": "main"}},
    {"state": "closed"},
    {"number": 78},
])
def test_mismatched_authenticated_remote_pr_blocks_certification(
        tmp_path, monkeypatch, mutation):
    path = event(tmp_path, monkeypatch)
    api(monkeypatch, **mutation)
    with pytest.raises(ValueError, match=r"authenticated GitHub PR|runner merge SHA"):
        target.require_event_merge_preview(path, "owner/repo", 77, HEAD, BASE)


@pytest.mark.parametrize("variable,value,reason", [
    ("GITHUB_SHA", STALE, "runner merge SHA"),
    ("GITHUB_REF", "refs/heads/develop", "runner context"),
    ("GITHUB_EVENT_NAME", "issue_comment", "runner context"),
    ("GITHUB_TOKEN", "", "credential unavailable"),
    ("GITHUB_API_URL", "https://example.com", "GitHub API origin"),
])
def test_invalid_runner_context_fails_closed(tmp_path, monkeypatch, variable, value, reason):
    path = event(tmp_path, monkeypatch)
    api(monkeypatch)
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError, match=reason):
        target.require_event_merge_preview(path, "owner/repo", 77, HEAD, BASE)


def test_synthetic_event_is_not_reattributed_to_real_runner(tmp_path, monkeypatch):
    path = event(tmp_path, monkeypatch)
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(tmp_path / "different-real-event.json"))
    monkeypatch.setattr(target.urllib.request, "urlopen",
                        lambda *_args, **_kwargs: pytest.fail("unexpected remote request"))
    assert target.require_event_merge_preview(path, "owner/repo", 77, HEAD, BASE) == STALE


def test_event_identity_mismatch_rejected_before_current_api(tmp_path, monkeypatch):
    path = event(tmp_path, monkeypatch)
    api(monkeypatch)
    with pytest.raises(ValueError, match="event identity differs"):
        target.require_event_merge_preview(path, "other/repo", 77, HEAD, BASE)
