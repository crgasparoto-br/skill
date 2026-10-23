"""Contract tests for the GitHub independent review gate."""
from __future__ import annotations

import copy
import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_independent_pr_audit.py"
spec = importlib.util.spec_from_file_location("independent_gate", SCRIPT)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
HEAD = "a" * 40
BASE_SHA = "b" * 40
HANDOFF = "collect / Require certified semantic handoff (exact SHA)"


def fixture(base="develop"):
    pr = {"state": "open", "base": {"ref": base, "sha": BASE_SHA}, "head": {"sha": HEAD},
          "user": {"login": "implementer"}}
    commits = [{"author": {"login": "implementer"}, "committer": {"login": "other-dev"}}]
    contract = {"schema": "solverit-audit-v1", "audit_round": "independent-01",
                "head_sha": HEAD, "finding_ids": ["A-112-01", "A-112-02"],
                "verified_finding_ids": ["A-112-01", "A-112-02"],
                "accepted_exclusions": []}
    reviews = [{"id": 1, "state": "APPROVED", "commit_id": HEAD,
                "submitted_at": "2026-10-23T20:00:00Z",
                "html_url": "https://github.com/example/repo/pull/1#pullrequestreview-1",
                "user": {"login": "independent-auditor"},
                "body": "SOLVERIT_AUDIT_JSON:" + json.dumps(contract)}]
    names = ["Structure and tests", "Offline authorization tests"]
    if base == "develop":
        names.append(HANDOFF)
    checks = {"total_count": len(names), "check_runs": [
        {"id": i + 1, "name": name, "head_sha": HEAD, "status": "completed",
         "conclusion": "success", "app": {"id": 15368}} for i, name in enumerate(names)
    ]}
    return pr, reviews, commits, checks


def verify(data, base="develop", authorized=None, trusted=None):
    if authorized is None:
        authorized = lambda reviewer: reviewer == "independent-auditor"
    if trusted is None:
        trusted = lambda _name, _check: True  # Pure gate unit tests only.
    return gate.verify_gate(*data, base, authorized, trusted)


def test_valid_independent_review_exact_sha_and_all_checks():
    assert "pullrequestreview-1" in verify(fixture())
    assert "pullrequestreview-1" in verify(fixture("main"), "main")


@pytest.mark.parametrize("mutate,reason", [
    (lambda d: d[1].clear(), "review history"),
    (lambda d: d[1][0]["user"].update(login="implementer"), "independent APPROVED"),
    (lambda d: d[1][0]["user"].update(login="other-dev"), "independent APPROVED"),
    (lambda d: d[1][0]["user"].update(login="robot[bot]"), "independent APPROVED"),
    (lambda d: d[1][0].update(commit_id="b" * 40), "exact-SHA"),
    (lambda d: d[1][0].update(state="COMMENTED"), "independent APPROVED"),
    (lambda d: d[1][0].update(body="SOLVERIT_AUDIT_JSON:{}"), "independent APPROVED"),
    (lambda d: d[3]["check_runs"][0].update(conclusion="failure"), "not green"),
    (lambda d: d[3]["check_runs"][0]["app"].update(id=999), "missing"),
    (lambda d: d[3].update(total_count=99), "truncated"),
    (lambda d: d[0]["base"].update(ref="other"), "PR base"),
])
def test_rejects_false_approval(mutate, reason):
    data = fixture()
    mutate(data)
    with pytest.raises(ValueError, match=reason):
        verify(data)


def test_clean_audit_can_approve_no_findings_with_complete_contract():
    data = fixture()
    review = data[1][0]
    contract = json.loads(review["body"].split(":", 1)[1])
    contract.update(finding_ids=[], verified_finding_ids=[], accepted_exclusions=[])
    review["body"] = "SOLVERIT_AUDIT_JSON:" + json.dumps(contract)
    assert "pullrequestreview-1" in verify(data)


def test_incomplete_or_overclaimed_audit_contract_rejected():
    for change in [
        {"verified_finding_ids": ["A-112-01"]},
        {"finding_ids": ["A-112-01", "A-112-01"]},
        {"accepted_exclusions": ["not-a-finding"]},
        {"audit_round": ""},
        {"head_sha": "b" * 40},
    ]:
        data = fixture()
        contract = json.loads(data[1][0]["body"].split(":", 1)[1])
        contract.update(change)
        data[1][0]["body"] = "SOLVERIT_AUDIT_JSON:" + json.dumps(contract)
        with pytest.raises(ValueError, match="independent APPROVED"):
            verify(data)


def test_later_review_revokes_prior_approval():
    data = fixture()
    last = copy.deepcopy(data[1][0])
    last.update(id=2, state="CHANGES_REQUESTED", submitted_at="2026-10-23T21:00:00Z")
    data[1].append(last)
    with pytest.raises(ValueError, match="request for changes"):
        verify(data)
    data[1][-1].update(state="COMMENTED")
    with pytest.raises(ValueError, match="independent APPROVED"):
        verify(data)


@pytest.mark.parametrize("unknown_field", ["author", "committer"])
def test_unknown_commit_participant_cannot_prove_independence(unknown_field):
    data = fixture()
    data[2][0][unknown_field] = None
    with pytest.raises(ValueError, match="identity unavailable"):
        verify(data)


def test_unlinked_commit_participant_cannot_prove_independence():
    data = fixture()
    data[2][0]["author"] = {"login": None}
    with pytest.raises(ValueError, match="identity unavailable"):
        verify(data)


def test_reviewer_must_have_repository_write_access():
    with pytest.raises(ValueError, match="independent APPROVED"):
        verify(fixture(), authorized=lambda reviewer: False)


@pytest.mark.parametrize("permission,expected", [
    ("admin", True), ("maintain", True), ("write", True),
    ("read", False), ("triage", False), ("none", False), (None, False),
])
def test_reviewer_permission_checked_against_authenticated_github(
        monkeypatch, permission, expected):
    queries = []

    def github(path, token):
        queries.append((path, token))
        return {"permission": permission}

    monkeypatch.setattr(gate, "github", github)
    result = gate.is_authorized_reviewer("org/repo", "auditor", "token")
    assert result is expected
    assert queries == [("/repos/org/repo/collaborators/auditor/permission", "token")]


def test_non_collaborator_does_not_block_other_valid_reviewer(monkeypatch):
    def github(path, token):
        if path.endswith("/external/permission"):
            raise urllib.error.HTTPError(path, 404, "not found", {}, None)
        return {"permission": "write"}

    monkeypatch.setattr(gate, "github", github)
    data = fixture()
    outsider = copy.deepcopy(data[1][0])
    outsider["user"]["login"] = "external"
    outsider["id"] = 2
    data[1].append(outsider)
    authorized = lambda user: gate.is_authorized_reviewer("org/repo", user, "token")
    assert "pullrequestreview-1" in verify(data, authorized=authorized)


def test_permission_api_error_does_not_grant_approval(monkeypatch):
    def github(path, token):
        raise urllib.error.HTTPError(path, 403, "forbidden", {}, None)

    monkeypatch.setattr(gate, "github", github)
    with pytest.raises(urllib.error.HTTPError):
        gate.is_authorized_reviewer("org/repo", "auditor", "token")


def test_edited_review_rechecked_and_rejected_if_contract_changes():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                / "independent-audit-gate.yml").read_text(encoding="utf-8")
    assert "types: [submitted, edited, dismissed]" in workflow
    data = fixture()
    data[1][0]["body"] = "SOLVERIT_AUDIT_JSON:{}"
    with pytest.raises(ValueError, match="independent APPROVED"):
        verify(data)


def test_later_failed_rerun_overrides_success():
    data = fixture()
    last = copy.deepcopy(data[3]["check_runs"][0])
    last.update(id=999, conclusion="failure")
    data[3]["check_runs"].append(last)
    data[3]["total_count"] += 1
    with pytest.raises(ValueError, match="not green"):
        verify(data)


def test_paginated_review_inventory_is_not_truncated(monkeypatch):
    calls = []
    def github(path, token):
        calls.append(path)
        return [{"id": i} for i in range(100)] if path.endswith("&page=1") else []
    monkeypatch.setattr(gate, "github", github)
    assert len(gate.page_all("org/repo", "pulls/1/reviews", "token")) == 100
    assert any("page=2" in item for item in calls)
    with pytest.raises(ValueError, match="bounded pagination"):
        gate.page_all("org/repo", "pulls/1/commits", "token", max_pages=1)


def test_pr_head_change_after_approval_rejected(monkeypatch):
    data = fixture()
    calls = 0
    def github(path, token):
        nonlocal calls
        if path.endswith("/pulls/3"):
            calls += 1
            pr = copy.deepcopy(data[0])
            if calls == 2:
                pr["head"]["sha"] = "b" * 40
            return pr
        if "/reviews?" in path:
            return data[1]
        if "/commits?" in path:
            return data[2]
        if "/check-runs?" in path:
            return data[3]
        if "/collaborators/" in path:
            return {"permission": "write"}
        raise AssertionError(path)
    monkeypatch.setattr(gate, "github", github)
    monkeypatch.setattr(gate, "trusted_workflow_check", lambda *args: True)
    with pytest.raises(ValueError, match="PR HEAD or trusted base SHA changed"):
        gate.run("org/repo", 3, "develop", BASE_SHA, "token")


def test_spoofed_later_green_check_does_not_override_official_failure():
    data = fixture()
    official = data[3]["check_runs"][0]
    official["conclusion"] = "failure"
    forged = copy.deepcopy(official)
    forged.update(id=999, conclusion="success")
    data[3]["check_runs"].append(forged)
    data[3]["total_count"] += 1
    with pytest.raises(ValueError, match="not green"):
        verify(data, trusted=lambda _name, check: check["id"] != 999)


@pytest.mark.parametrize("mutation", [
    lambda run, job, check: run.update(path=".github/workflows/fake.yml"),
    lambda run, job, check: run.update(check_suite_id=999),
    lambda run, job, check: run.update(head_sha="c" * 40),
    lambda run, job, check: run.update(event="workflow_dispatch"),
    lambda run, job, check: run.update(pull_requests=[{"number": 99}]),
    lambda run, job, check: job.update(check_run_url="https://api.github.com/other/check-runs/42"),
    lambda run, job, check: job.update(run_id=999),
    lambda run, job, check: check.update(details_url="https://untrusted.example/other"),
])
def test_check_requires_matching_github_workflow_suite_and_job(monkeypatch, mutation):
    check = {
        "id": 42, "check_suite": {"id": 33},
        "details_url": "https://github.com/org/repo/actions/runs/23/job/44",
    }
    run = {
        "id": 23, "path": ".github/workflows/validate.yml@refs/pull/3/merge",
        "head_sha": HEAD, "event": "pull_request", "check_suite_id": 33,
        "status": "completed", "conclusion": "success",
        "pull_requests": [{"number": 3}],
    }
    job = {
        "id": 44, "run_id": 23, "name": "Structure and tests",
        "status": "completed", "conclusion": "success",
        "check_run_url": "https://api.github.com/repos/org/repo/check-runs/42",
    }
    response = {
        "/repos/org/repo/actions/runs/23": run,
        "/repos/org/repo/actions/jobs/44": job,
    }
    monkeypatch.setattr(gate, "github", lambda path, token: response[path])
    assert gate.trusted_workflow_check(
        "org/repo", 3, "Structure and tests", check, HEAD, "token")
    mutation(run, job, check)
    assert not gate.trusted_workflow_check(
        "org/repo", 3, "Structure and tests", check, HEAD, "token")


@pytest.mark.parametrize("phase", ["initial", "final"])
def test_trusted_base_sha_drift_is_rejected(monkeypatch, phase):
    data = fixture()
    calls = 0

    def github(path, token):
        nonlocal calls
        if path.endswith("/pulls/3"):
            calls += 1
            pr = copy.deepcopy(data[0])
            if (phase == "initial" and calls == 1) or (
                    phase == "final" and calls == 2):
                pr["base"]["sha"] = "c" * 40
            return pr
        if "/reviews?" in path:
            return data[1]
        if "/commits?" in path:
            return data[2]
        if "/check-runs?" in path:
            return data[3]
        if "/collaborators/" in path:
            return {"permission": "write"}
        raise AssertionError(path)

    monkeypatch.setattr(gate, "github", github)
    monkeypatch.setattr(gate, "trusted_workflow_check", lambda *args: True)
    with pytest.raises(ValueError, match=r"trusted .*base SHA changed"):
        gate.run("org/repo", 3, "develop", BASE_SHA, "token")


def test_workflow_passes_trusted_base_sha_and_scoped_actions_permission():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                / "independent-audit-gate.yml").read_text(encoding="utf-8")
    assert "  actions: read" in workflow
    assert "TARGET_BASE_SHA: ${{ github.event.pull_request.base.sha }}" in workflow
    assert '--base-sha "$TARGET_BASE_SHA"' in workflow
