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


@pytest.mark.parametrize("tamper", [None, "equivalent-preview", "base", "head", "preview", "title", "body",
                                    "certificate-preview-equivalent", "certificate-preview-different-tree",
                                    "certificate-preview-reversed-parent", "pretest-preview-tampered"])
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
    certificate_preview = "d" * 40 if isinstance(tamper, str) and tamper.startswith("certificate-preview-") else PREVIEW
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
    preflight = {"identity": {"issue_number": 9, "base_sha": BASE,
                              "merge_preview_sha": recorded["pull_request"]["merge_commit_sha"]},
                 "source": {"issue_body_sha256": identity["issue_sha256"]}}
    if tamper == "pretest-preview-tampered":
        preflight["identity"]["merge_preview_sha"] = "e" * 40
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as out:
        for name, data in [
            ("certification-event.json", json.dumps(recorded)),
            (".audit/entregar-issue/handoff-ready.json", json.dumps({
                "identity": {"merge_preview_sha": certificate_preview,
                             "material_merge_preview_sha": certificate_preview}})),
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
            parents = [{"sha": BASE}, {"sha": HEAD}]
            if tamper == "certificate-preview-reversed-parent":
                parents.reverse()
            accepted = tamper in {"equivalent-preview", "certificate-preview-equivalent",
                                  "certificate-preview-reversed-parent"}
            return {"sha": "d" * 40, "parents": parents,
                    "tree": {"sha": ("1" if accepted else "f") * 40}}
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
    success_cases = {None, "equivalent-preview", "certificate-preview-equivalent"}
    if tamper not in success_cases:
        with pytest.raises(ValueError, match="merge preview" if tamper in {
                "preview", "certificate-preview-different-tree", "certificate-preview-reversed-parent",
                "pretest-preview-tampered"} else "certification event altered or stale"):
            runner.certified_evidence(identity, checks, tmp_path)
        assert checked == []
    else:
        metadata, passed = runner.certified_evidence(identity, checks, tmp_path)
        expected = copy.deepcopy(recorded)
        expected["pull_request"]["merge_commit_sha"] = certificate_preview
        assert checked == [(expected, "develop")]
        assert metadata["artifact_id"] == 42
        assert metadata["certified_handoff_preview_reconciliation"]["mode"] == (
            "equivalent-ordered-parents-and-tree" if tamper == "certificate-preview-equivalent" else "exact")
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
    assert "entregar-issue/scripts/require_actions_handoff_certificate.py" in runner.TRUSTED_PATHS
    assert "entregar-issue/scripts/handoff_merge_preview.py" in runner.TRUSTED_PATHS

@pytest.mark.parametrize("attack", [
    "valid", "missing-native-contract", "changed-native-contract",
    "changed-base", "stale-issue", "changed-head", "stale-test-index",
    "skipped-native-test", "native-check-failed",
])
def test_native_session_review_uses_real_exact_sha_evidence_without_legacy_certificate(
        monkeypatch, tmp_path, attack):
    """Native route skips only the legacy certificate, never JUnit or trusted Actions."""
    import build_test_candidate_index
    import verify_independent_pr_audit

    identity, pr, _ = sample()
    event = {"repository": {"full_name": REPO}, "pull_request": {
        "number": 10, "title": pr["title"], "body": pr["body"],
        "merge_commit_sha": PREVIEW,
        "base": {"ref": "develop", "sha": BASE},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
    }}
    canonical_contract_sha = "f" * 64
    transport = {"mode": "native-github-audit", "contract_sha256": canonical_contract_sha}
    source = {"mode": "native-github-audit", "repository": REPO,
              "trusted_anchor_sha": BASE, "material_head_sha": HEAD,
              "contract": {"source_sha256": canonical_contract_sha}}
    if attack == "missing-native-contract":
        source.pop("contract")
    if attack == "changed-native-contract":
        source["contract"]["source_sha256"] = "0" * 64
    if attack == "changed-base":
        source["trusted_anchor_sha"] = "0" * 40
    if attack == "changed-head":
        source["material_head_sha"] = "0" * 40

    log = b"1 passed\n"
    junit_bytes = (b'<testsuite name="pytest"><testcase classname="tests.native" '
                   b'name="test_native_review"/></testsuite>')
    if attack == "skipped-native-test":
        junit_bytes = (b'<testsuite name="pytest"><testcase classname="tests.native" '
                       b'name="test_native_review"><skipped/></testcase></testsuite>')
    junit = tmp_path / "pytest-exact-head.xml"
    junit.write_bytes(junit_bytes)
    index = build_test_candidate_index.collect(junit, HEAD)
    if attack == "stale-test-index":
        index["subject_sha"] = "0" * 40
    issue_digest = identity["issue_sha256"]
    if attack == "stale-issue":
        issue_digest = "0" * 64
    records = {
        "certification-event.json": json.dumps(event),
        "handoff-preflight.json": json.dumps({
            "identity": {"issue_number": 9, "base_sha": BASE,
                         "merge_preview_sha": PREVIEW},
            "source": {"issue_body_sha256": issue_digest},
        }),
        "audit-transport.json": json.dumps(source),
        "test-execution-facts.json": json.dumps({
            "subject_sha": HEAD, "verification": "passed",
            "execution": {"exit_code": 0, "log_sha256": runner.digest(log)},
        }),
        "pytest-exact-head.log": log,
        "pytest-exact-head.xml": junit_bytes,
        "test-candidate-index.json": json.dumps(index),
    }
    zipped = io.BytesIO()
    with zipfile.ZipFile(zipped, "w") as arc:
        for name, content in records.items():
            arc.writestr(name, content)
    blob = zipped.getvalue()
    name = f"handoff-evidence-10-{HEAD}"
    artifact = {"id": 42, "name": name, "expired": False,
                "digest": "sha256:" + runner.digest(blob)}
    check_names = ["Structure and tests", "Offline authorization tests",
                   verify_independent_pr_audit.NATIVE_EVIDENCE]
    checks = {"total_count": 3, "check_runs": [
        {"id": i + 1, "name": check_name, "head_sha": HEAD,
         "status": "completed", "conclusion": (
             "failure" if attack == "native-check-failed" and i == 2 else "success"),
         "completed_at": "2026-11-19T00:00:00Z",
         "details_url": f"https://github.com/{REPO}/actions/runs/19/job/21",
         "app": {"id": 15368}}
        for i, check_name in enumerate(check_names)
    ]}

    def api(path, *, binary=False):
        if path == f"/repos/{REPO}/actions/runs/19/artifacts?per_page=100":
            return {"total_count": 1, "artifacts": [artifact]}
        if path == f"/repos/{REPO}/actions/artifacts/42/zip" and binary:
            return blob
        raise AssertionError(path)

    monkeypatch.setenv("GH_TOKEN", "unit-test-only")
    monkeypatch.setattr(runner, "api", api)
    monkeypatch.setattr(runner, "authenticated_certificate_event", lambda *_: event)
    monkeypatch.setattr(runner, "authenticated_preview_reconciliation",
                        lambda *_: {"mode": "exact"})
    monkeypatch.setattr(verify_independent_pr_audit, "trusted_workflow_check",
                        lambda *_: True)

    if attack == "valid":
        metadata, passed = runner.certified_evidence(identity, checks, tmp_path, transport)
        assert metadata["audit_transport"] == "native-github-audit"
        assert metadata["native_contract_sha256"] == canonical_contract_sha
        assert metadata["technical_check_ids"] == [1, 2, 3]
        assert "certified_handoff_preview_reconciliation" not in metadata
        assert passed
    else:
        with pytest.raises(ValueError):
            runner.certified_evidence(identity, checks, tmp_path, transport)
