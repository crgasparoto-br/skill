"""Transport, canonical parser, neutral packet and mutation regression controls."""
from __future__ import annotations

import importlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
runner = importlib.import_module("verify_session_review")


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, value in entries:
            z.writestr(name, value)
    return out.getvalue()


def test_archive_rejects_traversal_duplicates_symlink(tmp_path):
    for entries in [ [("../escape", "x")], [("/escape", "x")], [("file", "x"), ("file", "y")] ]:
        with pytest.raises(ValueError):
            runner.unpack(archive(entries), tmp_path)
    link = zipfile.ZipInfo("link")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match="symlink"):
        runner.unpack(archive([(link, "/etc/passwd")]), tmp_path)
    runner.unpack(archive([("nested/facts.json", "{}")]), tmp_path)
    assert (tmp_path / "nested/facts.json").read_text() == "{}"


def test_canonical_requirements_use_existing_issue_parser():
    issue = {"number": 9, "body": "## Requisitos\n- Exigir SHA exato.\n- Rejeitar evidencia ausente.\n"}
    rows = runner.requirements("owner/repo", issue)
    assert len(rows) == 2
    assert all(len(row["candidate_key"]) == 64 for row in rows)
    assert rows == runner.requirements("owner/repo", issue)
    issue["body"] += "- Validar assinatura quando aplicavel.\n"
    assert len(runner.requirements("owner/repo", issue)) == 3


def test_full_pagination_not_first_page_only(monkeypatch):
    calls = []
    def api(path):
        calls.append(path)
        return [{"n": i} for i in range(100)] if path.endswith("&page=1") else []
    monkeypatch.setattr(runner, "api", api)
    assert len(runner.pages("owner/repo", "pulls?state=open")) == 100
    assert calls[-1].endswith("&page=2")
    assert all("?state=open&per_page" in call for call in calls)


def test_edited_issue_selects_only_its_open_pr(monkeypatch):
    prs = [{"number": 10, "state": "open", "base": {"ref": "develop"}, "body": "Refs #9"},
           {"number": 11, "state": "open", "base": {"ref": "main"}, "body": "Refs #8"}]
    monkeypatch.setattr(runner, "pages", lambda *_: prs)
    monkeypatch.setattr(runner, "api", lambda path: next(p for p in prs if path.endswith('/' + str(p['number']))))
    event = {"repository": {"full_name": "owner/repo"}, "issue": {"number": 9}, "action": "edited"}
    assert runner.resolve_targets("owner/repo", event) == [(10, 9)]


def test_no_recursive_workflow_trigger(tmp_path):
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/session-review.yml").read_text()
    assert '"Verify session review' not in workflow.split("workflow_run:", 1)[1].split("types:", 1)[0]
    assert "pull_request_target:" in workflow
    assert "checks: write" in workflow
    assert "contents: write" not in workflow
    assert "secrets." not in workflow
    assert "self-hosted" not in workflow
    assert "github.event.pull_request.head.sha" not in workflow
    assert "persist-credentials: false" in workflow


def test_revocation_watermark_survives_missing_report(monkeypatch):
    check = {"name": runner.CHECK_NAME, "app": {"id": 15368},
             "output": {"text": json.dumps({"review_comment_id": 41})}}
    monkeypatch.setattr(runner, "api", lambda *_: {"total_count": 1, "check_runs": [check]})
    assert runner.review_journal("owner/repo", "a" * 40)[0] == 41


def test_publication_reuses_same_verified_fingerprint(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "review_journal", lambda *_: (41, [{"id": 5, "conclusion": "success", "external_id": "fingerprint"}]))
    monkeypatch.setattr(runner, "api", lambda *a, **kw: calls.append((a, kw)))
    runner.publish("owner/repo", "a" * 40, "success", "verified", {"fingerprint": "fingerprint"}, "123")
    assert calls == []


def test_packet_rebuilds_full_diff_from_immutable_blobs_not_truncated_patch(monkeypatch):
    reads = []
    def read(repo, path, sha):
        reads.append((path, sha))
        return (b"old\n" if sha == "b" * 40 else b"new\n"), "blob-sha"
    monkeypatch.setattr(runner, "content", read)
    files, diffs = runner.freeze_files("owner/repo", [{"status": "modified", "filename": "src.py", "patch": "TRUNCATED"}],
                                      "b" * 40, "a" * 40)
    assert files == {"base/src.py": "old\n", "head/src.py": "new\n"}
    assert "-old" in diffs["src.py"] and "+new" in diffs["src.py"]
    assert "TRUNCATED" not in diffs["src.py"]
    assert reads == [("src.py", "b" * 40), ("src.py", "a" * 40)]


def test_owner_authorization_needs_no_extra_account_or_admin_secret(monkeypatch):
    monkeypatch.setattr(runner, "api", lambda *_: {"owner": {"type": "User", "id": 123, "login": "owner"}})
    assert runner.authorized_operator("owner/repo", {"id": 123, "login": "owner"}) is True


def test_edit_revokes_even_with_equal_second_timestamps(monkeypatch, tmp_path):
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"action": "edited", "comment": {"id": 41, "body": runner.PREFIX + "{}",
                          "user": {"id": 123, "login": "owner", "type": "User"}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    assert runner.event_review_id({"operators": [{"id": 123, "login": "owner"}]}) == 42


def test_failure_leaves_no_previous_green_as_latest_check(monkeypatch):
    events = []
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setattr(runner, "api", lambda path, **kw: {"head": {"sha": "a" * 40}} if '/pulls/' in path else {"id": 77})
    monkeypatch.setattr(runner, "review_journal", lambda *_: (41, []))
    monkeypatch.setattr(runner, "event_review_id", lambda *_: 0)
    def blocked(*args, **kwargs):
        raise ValueError("certificate missing")
    monkeypatch.setattr(runner, "prepare", blocked)
    monkeypatch.setattr(runner, "publish", lambda *args: events.append(args))
    assert runner.evaluate("owner/repo", 10, 9) == 2
    assert events[-1][2] == "failure"
    assert events[-1][-1] == 77  # Completes the pending check, not an old success.


@pytest.mark.parametrize("path", ["a//b", "a/./b", ".", "./", "a\x00b"])
def test_archive_rejects_path_aliases(path, tmp_path):
    # Pure-path aliases must not overwrite previously validated members.
    assert runner.safe_path(path) is False


def test_edit_removing_marker_still_revokes(monkeypatch, tmp_path):
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"action": "edited", "comment": {"id": 41, "body": "removed marker",
                    "user": {"id": 123, "login": "owner", "type": "User"}},
                    "changes": {"body": {"from": runner.PREFIX + "{}"}}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
    assert runner.event_review_id({"operators": [{"id": 123, "login": "owner"}]}) == 42



def test_ambiguous_pr_reference_is_retained_for_revocation(monkeypatch):
    pr = {"number": 10, "state": "open", "base": {"ref": "develop"}, "body": "Refs #9\nRefs #8"}
    monkeypatch.setattr(runner, "api", lambda *_: pr)
    event = {"repository": {"full_name": "owner/repo"}, "pull_request": {"number": 10}}
    assert runner.resolve_targets("owner/repo", event) == [(10, 0)]


def test_review_revocation_events_are_queued_not_replaced():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/session-review.yml").read_text()
    assert "  queue: max\n" in workflow
    assert "  cancel-in-progress: false\n" in workflow
