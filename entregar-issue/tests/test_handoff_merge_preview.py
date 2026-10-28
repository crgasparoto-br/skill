"""Positive, negative and regression controls for trusted live GitHub merge previews."""
import json
from pathlib import Path

import handoff_merge_preview as tool
import pytest
import yaml

REPO = "team/repo"
BASE = "b" * 40
HEAD = "a" * 40
STALE = "c" * 40
FRESH = "d" * 40


def event(tmp_path, preview=STALE):
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"repository": {"full_name": REPO}, "pull_request": {
        "number": 141, "merge_commit_sha": preview,
        "base": {"sha": BASE, "ref": "develop"},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
    }}))
    return path


def live(preview=FRESH):
    return {"number": 141, "state": "open", "merged": False, "merge_commit_sha": preview,
            "base": {"sha": BASE, "ref": "develop", "repo": {"full_name": REPO}},
            "head": {"sha": HEAD, "repo": {"full_name": REPO}}}


def test_stale_event_preview_is_replaced_by_live_verified_parents(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW", "1")
    requests = []

    def read(path):
        requests.append(path)
        if path.endswith("/pulls/141"):
            return live()
        if path.endswith(FRESH):
            return {"sha": FRESH, "parents": [{"sha": BASE}, {"sha": HEAD}]}
        pytest.fail(f"unexpected request: {path}")

    monkeypatch.setattr(tool, "_read_json", read)
    monkeypatch.setattr(tool.time, "sleep", lambda _: pytest.fail("no retry needed"))
    assert tool.require_event_merge_preview(event(tmp_path), REPO, 141, HEAD, BASE) == FRESH
    assert len(requests) == 3


def test_old_parent_is_blocked_even_when_event_and_live_sha_agree(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW", "1")

    def read(path):
        if path.endswith("/pulls/141"):
            return live(STALE)
        return {"sha": STALE, "parents": [{"sha": BASE}, {"sha": "f" * 40}]}

    monkeypatch.setattr(tool, "_read_json", read)
    monkeypatch.setattr(tool.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="stale or not bound"):
        tool.require_event_merge_preview(event(tmp_path), REPO, 141, HEAD, BASE)


@pytest.mark.parametrize("mutation", ["foreign-repo", "base-sha", "head-sha", "base-ref"])
def test_live_identity_drift_is_blocked(monkeypatch, tmp_path, mutation):
    monkeypatch.setenv("SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW", "1")
    candidate = live()
    if mutation == "foreign-repo":
        candidate["head"]["repo"]["full_name"] = "wrong/repo"
    elif mutation == "base-sha":
        candidate["base"]["sha"] = "e" * 40
    elif mutation == "head-sha":
        candidate["head"]["sha"] = "e" * 40
    else:
        candidate["base"]["ref"] = "main"
    monkeypatch.setattr(tool, "_read_json", lambda _: candidate)
    with pytest.raises(ValueError, match="identity differs"):
        tool.require_event_merge_preview(event(tmp_path), REPO, 141, HEAD, BASE)


def test_live_preview_drift_between_reads_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW", "1")
    count = [0]

    def read(path):
        if path.endswith("/pulls/141"):
            count[0] += 1
            return live(FRESH if count[0] % 2 else STALE)
        return {"sha": FRESH, "parents": [{"sha": BASE}, {"sha": HEAD}]}

    monkeypatch.setattr(tool, "_read_json", read)
    monkeypatch.setattr(tool.time, "sleep", lambda _: None)
    with pytest.raises(ValueError, match="stale or not bound"):
        tool.require_event_merge_preview(event(tmp_path), REPO, 141, HEAD, BASE)


@pytest.mark.parametrize("preview", [None, "invalid", "0" * 39])
def test_invalid_event_preview_is_not_promoted(monkeypatch, tmp_path, preview):
    monkeypatch.setattr(tool, "_read_json", lambda _: pytest.fail("unexpected API call"))
    with pytest.raises(ValueError, match="valid merge preview"):
        tool.require_event_merge_preview(event(tmp_path, preview), REPO, 141, HEAD, BASE)


def test_offline_historical_replay_never_contacts_github(monkeypatch, tmp_path):
    monkeypatch.delenv("SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW", raising=False)
    monkeypatch.setattr(tool, "_read_json", lambda _: pytest.fail("offline replay cannot read API"))
    assert tool.require_event_merge_preview(event(tmp_path), REPO, 141, HEAD, BASE) == STALE


def test_required_mode_fails_closed_without_token(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW", "1")
    monkeypatch.setenv("GITHUB_API_URL", "https://example.com")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(ValueError, match="context is unavailable"):
        tool.require_event_merge_preview(event(tmp_path), REPO, 141, HEAD, BASE)


def test_official_certification_and_producer_must_enforce_live_preview():
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/reusable-handoff.yml"
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    for job, name in (
        ("evidence", "Capture canonical PR/issue identity and initialize closure"),
        ("certification", "Require authentic certified evidence (not merely passing tests)"),
    ):
        step = next(item for item in jobs[job]["steps"] if item.get("name") == name)
        assert step["env"]["SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW"] == "1"
        assert step["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    late = next(item for item in jobs["evidence"]["steps"]
                if item.get("name") == "Validate evidence and build handoff certificate, fail closed")
    assert "GITHUB_TOKEN" not in late["env"]
    assert "SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW" not in late["env"]
    assert "certification-event.json" in late["run"]
