"""Transport, canonical parser, neutral packet and mutation regression controls."""
from __future__ import annotations

import copy
import importlib
import io
import json
import stat
import sys
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.test_session_review import fixtures, policy

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
    check = {"id": 5, "head_sha": "a" * 40, "name": runner.CHECK_NAME, "app": {"id": 15368},
             "output": {"text": json.dumps({"review_comment_id": 41})}}
    monkeypatch.setattr(runner, "api", lambda *_: {"total_count": 1, "check_runs": [check]})
    assert runner.review_journal("owner/repo", "a" * 40)[0] == 41


@pytest.mark.parametrize("base_ref", ["develop", "main"])
def test_publication_reuses_same_verified_fingerprint(review_backend, base_ref):
    backend = review_backend
    if base_ref == "main":
        backend.change_identity("base_ref")
    assert backend.run() == 0
    first = copy.deepcopy(backend.checks[-1])
    assert backend.run() == 0
    assert len(backend.checks) == 1
    assert backend.checks[-1]["id"] == first["id"]
    assert backend.checks[-1]["external_id"] == first["external_id"]
    assert backend.rechecks == 2  # Reuse still revalidates live authority/evidence.
    assert [method for method, _ in backend.writes] == ["POST", "PATCH", "PATCH", "PATCH"]


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


def test_failure_leaves_no_previous_green_as_latest_check(review_backend, monkeypatch):
    backend = review_backend
    assert backend.run() == 0
    def blocked(*args, **kwargs):
        raise ValueError("certificate missing")
    monkeypatch.setattr(runner, "prepare", blocked)
    assert backend.run() == 2
    assert len(backend.checks) == 1
    assert backend.checks[-1]["status"] == "completed"
    assert backend.checks[-1]["conclusion"] == "failure"
    assert "certificate missing" in backend.checks[-1]["output"]["summary"]


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


class ReviewBackend:
    """GitHub boundary fixture; evaluate, identity checks and publication stay real."""

    def __init__(self, monkeypatch, tmp_path):
        self.packet, self.report, comment, self.files, self.passed = fixtures()
        self.policy = policy()
        self.issue = {"number": 9, "title": "Exact evidence", "body": "## Requisitos\n- Validar evidencia.\n"}
        self.policy_path = tmp_path / runner.POLICY_PATH
        self.policy_path.parent.mkdir(parents=True)
        self.policy_path.write_bytes(runner.canonical(self.policy))
        self.packet["identity"].update(issue_sha256=runner.digest(self.issue["body"].encode()),
                                     policy_sha256=runner.digest(self.policy_path.read_bytes()))
        self.report["identity"] = copy.deepcopy(self.packet["identity"])
        comment["body"] = runner.PREFIX + json.dumps(self.report)
        self.comments = [comment]
        self.pr = {"number": 10, "state": "open", "draft": False, "body": "Refs #9",
                   "head": {"sha": "a" * 40, "repo": {"full_name": "owner/repo"}},
                   "base": {"sha": "b" * 40, "ref": "develop", "repo": {"full_name": "owner/repo"}},
                   "merge_commit_sha": "c" * 40}
        self.checks, self.writes, self.journal_reads = [], [], []
        self.on_prepare = self.on_recheck = lambda: None
        self.rechecks = 0
        monkeypatch.setattr(runner, "ROOT", tmp_path)
        monkeypatch.setattr(runner, "api", self.api)
        monkeypatch.setattr(runner, "prepare", self.prepare)
        monkeypatch.setattr(runner, "recheck_inputs", self.recheck)
        monkeypatch.setattr(runner, "authorized_operator", lambda *_: True)
        monkeypatch.setenv("GITHUB_RUN_ID", "123")
        monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)

    def prepare(self, *args, **kwargs):
        self.on_prepare()
        return copy.deepcopy((self.packet, self.policy, self.files, self.passed))

    def recheck(self, packet):
        self.rechecks += 1
        self.on_recheck()

    def run(self):
        return runner.evaluate("owner/repo", 10, 9)

    def seed(self, count):
        self.checks = [{"id": i + 1, "name": runner.CHECK_NAME, "head_sha": "a" * 40,
            "app": {"id": 15368}, "status": "completed", "conclusion": "success",
            "output": {"text": json.dumps({"review_comment_id": 20})}} for i in range(count)]

    def change_identity(self, field):
        value = "e" * 40
        if field in {"head_sha", "base_sha"}:
            self.pr[field.split("_")[0]]["sha"] = value
        elif field == "base_ref":
            value = self.pr["base"]["ref"] = "main"
        elif field == "merge_preview_sha":
            self.pr["merge_commit_sha"] = value
        elif field == "issue_sha256":
            self.issue["body"] += "- Rejeitar evidencia obsoleta.\n"
            value = runner.digest(self.issue["body"].encode())
        else:
            self.policy_path.write_text(json.dumps(self.policy, indent=2))
            value = runner.digest(self.policy_path.read_bytes())
        self.packet["identity"][field] = value
        self.report["identity"][field] = value
        self.comments[0]["body"] = runner.PREFIX + json.dumps(self.report)

    def api(self, endpoint, *, method="GET", data=None):
        path = urlsplit(endpoint).path
        page = int(parse_qs(urlsplit(endpoint).query).get("page", [1])[0])
        if method != "GET":
            self.writes.append((method, copy.deepcopy(data)))
            if method == "POST":
                self.checks.append({"id": max((c["id"] for c in self.checks), default=0) + 1,
                                    "app": {"id": 15368}, **copy.deepcopy(data)})
                check = self.checks[-1]
            else:
                check = next(c for c in self.checks if c["id"] == int(path.rsplit("/", 1)[1]))
                check.update(copy.deepcopy(data))
            if data.get("status") == "in_progress":
                check["conclusion"] = None
            return copy.deepcopy(check)
        if "/commits/" in path:
            self.journal_reads.append(page)
            checks = sorted(self.checks, key=lambda c: c["id"], reverse=True)
            return {"total_count": len(checks), "check_runs": copy.deepcopy(checks[(page - 1) * 100:page * 100])}
        if path.endswith("/pulls/10"):
            return copy.deepcopy(self.pr)
        if path.endswith("/issues/9"):
            return copy.deepcopy(self.issue)
        if path.endswith("/issues/10/comments"):
            return copy.deepcopy(self.comments[(page - 1) * 100:page * 100])
        if "/issues/comments/" in path:
            return copy.deepcopy(next(c for c in self.comments if c["id"] == int(path.rsplit("/", 1)[1])))
        if "/check-runs/" in path:
            return copy.deepcopy(next(c for c in self.checks if c["id"] == int(path.rsplit("/", 1)[1])))
        raise AssertionError(endpoint)


@pytest.fixture
def review_backend(monkeypatch, tmp_path):
    return ReviewBackend(monkeypatch, tmp_path)


@pytest.mark.parametrize("field", ["head_sha", "base_sha", "base_ref", "merge_preview_sha", "issue_sha256", "policy_sha256"])
def test_evaluate_rejects_changed_initial_identity(review_backend, field):
    backend = review_backend
    backend.on_prepare = lambda: backend.change_identity(field)
    assert backend.run() == 2
    assert backend.rechecks == 0
    assert backend.checks[-1]["head_sha"] == "a" * 40
    assert backend.checks[-1]["conclusion"] == "failure"
    assert "initial observation" in backend.checks[-1]["output"]["summary"]
    assert not any(body.get("conclusion") == "success" for _, body in backend.writes)


@pytest.mark.parametrize("field", ["head_sha", "base_sha", "base_ref", "merge_preview_sha", "issue_sha256", "policy_sha256"])
def test_evaluate_rejects_target_change_before_publication(review_backend, field):
    backend = review_backend
    backend.on_recheck = lambda: backend.change_identity(field)
    assert backend.run() == 2
    assert backend.checks[-1]["head_sha"] == "a" * 40
    assert backend.checks[-1]["conclusion"] == "failure"
    assert "target changed before publication" in backend.checks[-1]["output"]["summary"]


@pytest.mark.parametrize("count", [99, 100, 101, 205, 2500])
def test_evaluate_reads_complete_journal_beyond_one_page(review_backend, count):
    backend = review_backend
    backend.seed(count)
    assert backend.run() == 0
    assert len(backend.checks) == count
    assert backend.checks[-1]["id"] == count
    assert backend.checks[-1]["conclusion"] == "success"
    assert backend.journal_reads == list(range(1, (count + 99) // 100 + 1))


def test_evaluate_preserves_revocation_across_pages_and_reuse(review_backend):
    backend = review_backend
    backend.seed(205)
    backend.checks[0]["output"]["text"] = json.dumps({"minimum_comment_id": 21})
    assert backend.run() == 2
    assert json.loads(backend.checks[-1]["output"]["text"])["minimum_comment_id"] == 21
    backend.checks.pop(0)  # The reused receipt retains the oldest revocation.
    assert backend.run() == 2
    backend.comments[0]["id"] = 22
    assert backend.run() == 0
    assert backend.checks[-1]["id"] == 205
    assert len(backend.checks) == 204


def test_review_journal_rejects_inventory_above_page_budget(review_backend):
    backend = review_backend
    backend.seed(2501)
    with pytest.raises(ValueError, match="incomplete paginated inventory"):
        runner.review_journal("owner/repo", "a" * 40)
    assert backend.journal_reads == list(range(1, 26))


def test_evaluate_publishes_failure_when_journal_is_unreadable(review_backend, monkeypatch):
    backend = review_backend
    backend.seed(1)
    calls = []
    def broken_journal(*args):
        calls.append(args)
        raise ValueError("journal unavailable")
    monkeypatch.setattr(runner, "review_journal", broken_journal)
    assert backend.run() == 2
    assert len(calls) == 1
    assert backend.checks[-1]["status"] == "completed"
    assert backend.checks[-1]["conclusion"] == "failure"
    assert "journal unavailable" in backend.checks[-1]["output"]["summary"]


@pytest.mark.parametrize("raw", ["[]", "null", '{"x":1,"x":2}', '{"review_comment_id":true}'])
def test_evaluate_revokes_success_when_prior_receipt_is_malformed(review_backend, raw):
    backend = review_backend
    backend.seed(1)
    backend.checks[0]["output"]["text"] = raw
    assert backend.run() == 2
    assert backend.checks[-1]["status"] == "completed"
    assert backend.checks[-1]["conclusion"] == "failure"


@pytest.mark.parametrize("action", ["edited", "deleted", "rejected"])
def test_evaluate_revocation_survives_reuse_and_old_approval_fallback(review_backend, monkeypatch, tmp_path, action):
    backend = review_backend
    assert backend.run() == 0
    original = copy.deepcopy(backend.comments[0])
    latest = copy.deepcopy(original)
    latest["id"] = 21
    if action == "rejected":
        report = copy.deepcopy(backend.report)
        report["conclusion"] = "rejected"
        latest["body"] = runner.PREFIX + json.dumps(report)
    elif action == "edited":
        latest["body"] = "marker removed"
    backend.comments = [original] if action == "deleted" else [original, latest]
    if action != "rejected":
        event = tmp_path / "event.json"
        event.write_text(json.dumps({"action": action, "comment": latest,
            "changes": {"body": {"from": original["body"]}}}))
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert backend.run() == 2
    backend.comments = [original]
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert backend.run() == 2
    assert len(backend.checks) == 1
    assert backend.checks[-1]["conclusion"] == "failure"
    backend.comments[0]["id"] = 23
    assert backend.run() == 0
    assert len(backend.checks) == 1


def test_packet_collection_rejects_initial_head_drift_without_writing(review_backend, tmp_path):
    backend = review_backend
    backend.on_prepare = lambda: backend.change_identity("head_sha")
    destination = tmp_path / "packet.json"
    assert runner.evaluate("owner/repo", 10, 9, destination) == 2
    assert not destination.exists()
    assert backend.writes == []


def test_publish_rejects_receipt_for_another_sha_before_writing(review_backend):
    backend = review_backend
    with pytest.raises(ValueError, match="does not authorize"):
        runner.publish("owner/repo", "b" * 40, "success", "verified", {"identity": {"head_sha": "a" * 40}}, "123")
    assert backend.writes == []


@pytest.mark.parametrize("field,value", [("head_sha", "b" * 40), ("name", "unrelated"), ("app", {"id": 999})])
def test_publish_rejects_a_check_for_another_target_or_publisher(review_backend, field, value):
    backend = review_backend
    backend.seed(1)
    backend.checks[0][field] = value
    with pytest.raises(ValueError, match="another target or publisher"):
        runner.publish("owner/repo", "a" * 40, "success", "verified", {"identity": {"head_sha": "a" * 40}}, "123", 1)
    assert backend.writes == []


@pytest.mark.parametrize("failure", ["truncated", "changed-count", "duplicate", "overflow"])
def test_review_journal_rejects_inconsistent_pages(review_backend, monkeypatch, failure):
    backend = review_backend
    backend.seed(101)
    def api(endpoint, **kwargs):
        result = backend.api(endpoint, **kwargs)
        if "page=2" in endpoint:
            if failure == "truncated":
                result["check_runs"] = []
            elif failure == "changed-count":
                result["total_count"] = 102
            elif failure == "overflow":
                result["check_runs"].append(copy.deepcopy(backend.checks[-1]))
            else:
                result["check_runs"] = [copy.deepcopy(backend.checks[-1])]
        return result
    monkeypatch.setattr(runner, "api", api)
    with pytest.raises(ValueError, match=r"inventory|duplicated"):
        runner.review_journal("owner/repo", "a" * 40)
