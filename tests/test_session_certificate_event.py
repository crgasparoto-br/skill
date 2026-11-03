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


@pytest.mark.parametrize("tamper", [None, "equivalent-preview", "base", "head", "preview", "title", "body"])
def test_certified_evidence_checks_pretest_event_before_verifier(
        monkeypatch, tmp_path, tamper):
    """The artifact cannot choose an event after the test runner altered it."""
    import build_test_candidate_index
    import require_actions_handoff_certificate
    import verify_independent_pr_audit

    identity, pr, merge = sample()
    merge["tree"] = {"sha": "1" * 40}
    recorded = {"repository": {"full_name": REPO}, "pull_request": {
        "number": 10, "title": pr["title"], "body": pr["body"],
        "merge_commit_sha": PREVIEW, "base": {"ref": "develop", "sha": BASE},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}}}}
    if tamper == "base":
        recorded["pull_request"]["base"]["sha"] = "d" * 40
    elif tamper == "head":
        recorded["pull_request"]["head"]["sha"] = "d" * 40
    elif tamper in {"preview", "equivalent-preview"}:
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
        if path.endswith("/git/commits/" + "d" * 40):
            return {"sha": "d" * 40, "parents": [{"sha": BASE}, {"sha": HEAD}],
                    "tree": {"sha": ("1" if tamper == "equivalent-preview" else "f") * 40}}
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
    if tamper and tamper != "equivalent-preview":
        with pytest.raises(ValueError, match="merge preview" if tamper == "preview"
                                   else "certification event altered or stale"):
            runner.certified_evidence(identity, checks, tmp_path)
        assert checked == []
    else:
        metadata, passed = runner.certified_evidence(identity, checks, tmp_path)
        assert checked == [(recorded, "develop")]
        assert metadata["artifact_id"] == 42
        assert metadata["certification_event_sha256"] == runner.digest(json.dumps(recorded).encode())
        assert metadata["merge_preview_reconciliation"]["mode"] == (
            "equivalent-ordered-parents-and-tree" if tamper == "equivalent-preview" else "exact")
        assert passed == {"passed-case"}


@pytest.mark.parametrize("case", ["equivalent", "different-tree", "reversed-parents",
                                 "foreign-parent", "missing-object", "corrupt-sha", "missing-tree"])
def test_preview_reconciliation_accepts_only_authenticated_same_tree_and_parents(monkeypatch, case):
    identity, _, _ = sample()
    fresh = "f" * 40
    original = {"sha": PREVIEW, "parents": [{"sha": BASE}, {"sha": HEAD}],
                "tree": {"sha": "1" * 40}}
    current = {"sha": fresh, "parents": [{"sha": BASE}, {"sha": HEAD}],
               "tree": {"sha": "1" * 40}}
    if case == "different-tree":
        current["tree"]["sha"] = "2" * 40
    if case == "reversed-parents":
        current["parents"].reverse()
    if case == "foreign-parent":
        original["parents"][0]["sha"] = "0" * 40
    if case == "corrupt-sha":
        current["sha"] = "0" * 40
    if case == "missing-tree":
        del original["tree"]

    def read(endpoint, *, binary=False):
        if endpoint.endswith(f"/git/commits/{PREVIEW}"):
            if case == "missing-object":
                raise ValueError("authenticated GitHub GET failed")
            return original
        if endpoint.endswith(f"/git/commits/{fresh}"):
            return current
        raise AssertionError(endpoint)

    monkeypatch.setattr(runner, "api", read)
    identity["merge_preview_sha"] = fresh
    if case == "equivalent":
        assert runner.authenticated_preview_reconciliation(identity, PREVIEW) == {
            "certified_sha": PREVIEW, "current_sha": fresh,
            "mode": "equivalent-ordered-parents-and-tree",
            "tree_sha": "1" * 40, "ordered_parents": [BASE, HEAD]}
    else:
        with pytest.raises(ValueError):
            runner.authenticated_preview_reconciliation(identity, PREVIEW)


@pytest.mark.parametrize("mutation", ["valid", "missing-commit", "foreign-commit",
                                       "wrong-parent", "wrong-base", "wrong-head", "duplicate"])
def test_implementation_chain_requires_git_authenticated_linear_material_history(monkeypatch, mutation):
    first, last = "1" * 40, HEAD
    identity, _, _ = sample()
    rows = [{"sha": first}, {"sha": last}]
    objects = {
        first: {"sha": first, "parents": [{"sha": BASE}]},
        last: {"sha": last, "parents": [{"sha": first}]},
    }
    if mutation == "missing-commit":
        rows.pop(0)
    elif mutation == "foreign-commit":
        objects[last]["sha"] = "f" * 40
    elif mutation == "wrong-parent":
        objects[last]["parents"][0]["sha"] = "f" * 40
    elif mutation == "wrong-base":
        objects[first]["parents"][0]["sha"] = "f" * 40
    elif mutation == "wrong-head":
        rows[-1]["sha"] = "f" * 40
    elif mutation == "duplicate":
        rows.append({"sha": last})
    monkeypatch.setattr(runner, "pages", lambda repo, endpoint: copy.deepcopy(rows))

    def read(endpoint, *, binary=False):
        sha = endpoint.rsplit("/", 1)[-1]
        return copy.deepcopy(objects.get(sha, {"sha": sha, "parents": [{"sha": BASE}]}))
    monkeypatch.setattr(runner, "api", read)
    metadata = {"artifact_id": 42, "artifact_digest": "sha256:" + "d" * 64}
    if mutation == "valid":
        result = runner.authenticated_implementation_provenance(identity, metadata)
        assert result["commits"] == [first, last]
        assert result["head_sha"] == HEAD
        assert result["handoff"]["artifact_id"] == 42
    else:
        with pytest.raises(ValueError):
            runner.authenticated_implementation_provenance(identity, metadata)


def test_promoted_trusted_base_requires_rebased_material_commits_and_new_handoff(monkeypatch):
    """An old PR history cannot be rebound to a newly installed trusted base."""
    identity, _, _ = sample()
    old_base, old_head = identity["base_sha"], identity["head_sha"]
    new_base, new_first, new_head = "2" * 40, "3" * 40, "4" * 40
    old_first = "1" * 40
    old_rows = [{"sha": old_first}, {"sha": old_head}]
    new_rows = [{"sha": new_first}, {"sha": new_head}]
    objects = {
        old_first: {"sha": old_first, "parents": [{"sha": old_base}]},
        old_head: {"sha": old_head, "parents": [{"sha": old_first}]},
        new_first: {"sha": new_first, "parents": [{"sha": new_base}]},
        new_head: {"sha": new_head, "parents": [{"sha": new_first}]},
    }
    rows = [old_rows]
    monkeypatch.setattr(runner, "pages", lambda *_: copy.deepcopy(rows[0]))
    monkeypatch.setattr(
        runner, "api", lambda path, **_: copy.deepcopy(objects[path.rsplit("/", 1)[-1]])
    )
    metadata = {"artifact_id": 42, "artifact_digest": "sha256:" + "d" * 64}
    old_proof = runner.authenticated_implementation_provenance(identity, metadata)

    # Promotion changes the protected base, but old material objects stay
    # immutable; a timestamp-equivalent merge cannot repair their ancestry.
    identity["base_sha"] = new_base
    with pytest.raises(ValueError, match="linear material chain"):
        runner.authenticated_implementation_provenance(identity, metadata)

    # Explicit linear rebase produces different commits and requires a new
    # exact-head certificate. Old provenance cannot be relabeled.
    rows[0] = new_rows
    identity["head_sha"] = new_head
    new_metadata = {"artifact_id": 43, "artifact_digest": "sha256:" + "e" * 64}
    refreshed = runner.authenticated_implementation_provenance(identity, new_metadata)
    assert refreshed["commits"] == [new_first, new_head]
    assert refreshed["base_sha"] == new_base
    assert refreshed["head_sha"] == new_head
    assert refreshed["handoff"]["artifact_id"] == 43
    assert refreshed != old_proof

    packet = {"identity": identity, "artifact_id": 43,
              "artifact_digest": new_metadata["artifact_digest"],
              "implementation_provenance": refreshed}
    declaration = {"type": runner.PROVENANCE_TYPE, "original_session_unavailable": True,
                   "github": old_proof}
    from session_review import verify_implementation_provenance
    policy = {"implementation_provenance": {
        "mode": "enabled", "type": runner.PROVENANCE_TYPE}}
    with pytest.raises(ValueError, match="forged, truncated or altered"):
        verify_implementation_provenance(declaration, packet, policy)


def test_preview_reconciliation_requires_exact_base_and_head_before_api(monkeypatch):
    identity, _, _ = sample()
    packet = {"identity": identity, "merge_preview_reconciliation": {
        "certified_sha": PREVIEW, "current_sha": PREVIEW, "mode": "exact"}}
    live = copy.deepcopy(identity)
    live["base_sha"] = "f" * 40
    monkeypatch.setattr(runner, "api", lambda *_, **__: pytest.fail("no GitHub call on changed base"))
    with pytest.raises(ValueError, match="base/HEAD"):
        runner.reconcile_target(packet, live)


def test_trusted_runner_binds_extracted_github_facts_to_protected_base():
    """Extraction cannot let the candidate replace an unauthenticated helper."""
    assert "scripts/session_review_github.py" in runner.TRUSTED_PATHS
    assert "scripts/verify_session_review.py" in runner.TRUSTED_PATHS
    assert "scripts/session_review.py" in runner.TRUSTED_PATHS
