"""Authenticated GitHub PR/merge and recorded-event controls for session certification."""
from __future__ import annotations

import copy
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

from tests.test_session_review_runner import runner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "entregar-issue" / "scripts"))

REPO = "owner/repo"
BASE = "b" * 40
HEAD = "a" * 40
PREVIEW = "c" * 40


def sample(base_ref="develop"):
    identity = {"repository": REPO, "pull_request": 10, "issue": 9,
                "base_ref": base_ref, "base_sha": BASE, "head_sha": HEAD,
                "merge_preview_sha": PREVIEW, "issue_sha256": "e" * 64}
    pr = {"number": 10, "state": "open", "draft": False,
          "title": "Trusted packet fix", "body": "Refs #9", "merge_commit_sha": PREVIEW,
          "base": {"ref": base_ref, "sha": BASE, "repo": {"full_name": REPO}},
          "head": {"sha": HEAD, "repo": {"full_name": REPO}}}
    merge = {"sha": PREVIEW, "parents": [{"sha": BASE}, {"sha": HEAD}]}
    return identity, pr, merge


def reader(pr, merge, calls):
    def read(path, *, binary=False):
        calls.append((path, binary))
        if path == f"/repos/{REPO}/pulls/10":
            return copy.deepcopy(pr)
        if path == f"/repos/{REPO}/git/commits/{PREVIEW}":
            return copy.deepcopy(merge)
        raise AssertionError(f"unexpected GitHub read: {path}")
    return read


@pytest.mark.parametrize("base_ref", ["develop", "main"])
def test_exact_authenticated_event_contains_all_required_fields(monkeypatch, base_ref):
    identity, pr, merge = sample(base_ref)
    calls = []
    monkeypatch.setattr(runner, "api", reader(pr, merge, calls))
    event = runner.authenticated_certificate_event(identity)
    assert event == {"repository": {"full_name": REPO}, "pull_request": {
        "number": 10, "title": pr["title"], "body": pr["body"],
        "merge_commit_sha": PREVIEW,
        "base": {"ref": base_ref, "sha": BASE},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}}}}
    assert calls == [(f"/repos/{REPO}/pulls/10", False),
                     (f"/repos/{REPO}/git/commits/{PREVIEW}", False)]


@pytest.mark.parametrize(("field", "value"), [
    ("number", 11), ("state", "closed"), ("draft", True),
    ("base.ref", "main"), ("base.sha", "d" * 40),
    ("base.repo.full_name", "other/repo"),
    ("head.sha", "d" * 40), ("head.repo.full_name", "other/repo"),
    ("merge_commit_sha", None), ("merge_commit_sha", "d" * 40),
    ("merge_commit_sha", "malformed"),
])
def test_changed_or_foreign_live_pr_never_reuses_old_certificate(monkeypatch, field, value):
    identity, pr, merge = sample()
    node = pr
    keys = field.split(".")
    for key in keys[:-1]:
        node = node[key]
    node[keys[-1]] = value
    monkeypatch.setattr(runner, "api", reader(pr, merge, []))
    with pytest.raises(ValueError, match="PR identity/preview drift"):
        runner.authenticated_certificate_event(identity)


@pytest.mark.parametrize("parents", [
    [HEAD, BASE], [BASE], [BASE, "d" * 40],
    [BASE, HEAD, "d" * 40], [],
])
def test_merge_preview_requires_exactly_two_ordered_git_parents(monkeypatch, parents):
    identity, pr, merge = sample()
    merge["parents"] = [{"sha": sha} for sha in parents]
    monkeypatch.setattr(runner, "api", reader(pr, merge, []))
    with pytest.raises(ValueError, match="incorrect ordered base/HEAD parents"):
        runner.authenticated_certificate_event(identity)


@pytest.mark.parametrize("tamper", [None, "base", "head", "preview", "title", "body"])
def test_certified_evidence_checks_pretest_event_before_verifier(
        monkeypatch, tmp_path, tamper):
    """The artifact cannot choose an event after the test runner altered it."""
    import build_test_candidate_index
    import require_actions_handoff_certificate
    import verify_independent_pr_audit

    identity, pr, merge = sample()
    recorded = {"repository": {"full_name": REPO}, "pull_request": {
        "number": 10, "title": pr["title"], "body": pr["body"],
        "merge_commit_sha": PREVIEW, "base": {"ref": "develop", "sha": BASE},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}}}}
    if tamper == "base":
        recorded["pull_request"]["base"]["sha"] = "d" * 40
    elif tamper == "head":
        recorded["pull_request"]["head"]["sha"] = "d" * 40
    elif tamper == "preview":
        recorded["pull_request"]["merge_commit_sha"] = "d" * 40
    elif tamper in {"title", "body"}:
        recorded["pull_request"][tamper] = "mutated-after-collection"

    log = b"HEAD: exact\nCOMMAND: pytest\nEXIT_CODE: 0\n"
    facts = {"subject_sha": HEAD, "verification": "passed",
             "execution": {"exit_code": 0, "log_sha256": runner.digest(log)}}
    preflight = {"identity": {"issue_number": 9, "base_sha": BASE},
                 "source": {"issue_body_sha256": identity["issue_sha256"]}}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as out:
        for name, data in [
            ("certification-event.json", json.dumps(recorded)),
            ("handoff-preflight.json", json.dumps(preflight)),
            ("test-execution-facts.json", json.dumps(facts)),
            ("pytest-exact-head.xml", "<testsuite/>"),
            ("pytest-exact-head.log", log),
        ]:
            out.writestr(name, data)
    raw = archive.getvalue()
    runs = {"total_count": 1, "artifacts": [{
        "id": 42, "expired": False, "name": f"handoff-evidence-10-{HEAD}",
        "digest": "sha256:" + runner.digest(raw)}]}
    def read(path, *, binary=False):
        if path.endswith("/pulls/10"):
            return pr
        if path.endswith(f"/git/commits/{PREVIEW}"):
            return merge
        if path.endswith("/actions/runs/19/artifacts?per_page=100"):
            return runs
        if path.endswith("/actions/artifacts/42/zip") and binary:
            return raw
        raise AssertionError(f"unexpected GitHub read: {path}")

    checked = []
    monkeypatch.setenv("GH_TOKEN", "unit-test-only")
    monkeypatch.setattr(runner, "api", read)
    monkeypatch.setattr(verify_independent_pr_audit, "trusted_workflow_check",
                        lambda *_: True)
    monkeypatch.setattr(verify_independent_pr_audit, "required_checks_green",
                        lambda *_: None)
    monkeypatch.setattr(require_actions_handoff_certificate, "verify",
                        lambda evidence, event, branch: checked.append(
                            (json.loads(event.read_bytes()), branch)))
    monkeypatch.setattr(build_test_candidate_index, "collect",
                        lambda *_: {"counts": {"failure": 0, "error": 0},
                                    "tests": [{"id": "passed-case", "status": "passed"}]})
    checks = {"check_runs": [{
        "id": 17, "name": verify_independent_pr_audit.HANDOFF, "head_sha": HEAD,
        "details_url": f"https://github.com/{REPO}/actions/runs/19/job/21",
        "completed_at": "2026-10-28T00:00:00Z"}]}
    if tamper:
        with pytest.raises(ValueError, match="certification event altered or stale"):
            runner.certified_evidence(identity, checks, tmp_path)
        assert checked == []
    else:
        metadata, passed = runner.certified_evidence(identity, checks, tmp_path)
        assert checked == [(recorded, "develop")]
        assert metadata["artifact_id"] == 42
        assert passed == {"passed-case"}
