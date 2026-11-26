"""The transition is routing only, not a second source of review authority."""
from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
route = importlib.import_module("dispatch_session_review")
contract = importlib.import_module("session_review")
HEAD, MAIN, TREE = "a" * 40, "b" * 40, "c" * 40
PREVIEW = "e" * 40
PREFIX = f"/repos/{route.REPO}"
INSTALL_HEAD = "f" * 40
INSTALL_PR = 220
ENROLL_COMMENT = 83
COMMENT_PATH = f"{PREFIX}/issues/comments/{ENROLL_COMMENT}"


@pytest.fixture
def state(monkeypatch):
    repo = {"full_name": route.REPO}
    pr = {"number": 21, "state": "open", "draft": False, "test_issue": route.PARITY_ISSUE,
          "merge_commit_sha": PREVIEW,
          "head": {"sha": HEAD, "repo": repo, "ref": route.PARITY_BRANCH},
          "base": {"ref": "develop", "sha": route.DEVELOP_PIN, "repo": repo}}
    event = {"repository": repo, "workflow_run": {
        "event": "pull_request", "head_repository": repo, "head_sha": HEAD,
        "path": ".github/workflows/handoff-evidence.yml"}}
    body = route.ENROLLMENT_PREFIX + json.dumps({
        "schema_version": 1, "repository": route.REPO, "issue": route.PARITY_ISSUE,
        "pull_request": 21, "base_sha": route.DEVELOP_PIN, "head_sha": HEAD,
        "merge_preview_sha": PREVIEW, "tree_sha": TREE, "installed_main_sha": MAIN,
    })
    enrollment = {"id": ENROLL_COMMENT, "node_id": "IC_fixture83", "body": body,
                  "url": f"https://api.github.com{COMMENT_PATH}",
                  "issue_url": f"https://api.github.com{PREFIX}/issues/{route.PARITY_ISSUE}",
                  "user": {"id": route.OWNER_ID, "type": "User", "login": "fixture-owner"},
                  "author_association": "OWNER", "performed_via_github_app": None,
                  "created_at": "2026-01-01T12:00:01Z", "updated_at": "2026-01-01T12:00:01Z"}
    data = {f"{PREFIX}/pulls/21": pr,
            f"{PREFIX}/pulls/{INSTALL_PR}": {
                "number": INSTALL_PR, "merged": True, "state": "closed", "merge_commit_sha": MAIN,
                "merged_at": "2026-01-01T12:00:00Z", "test_issue": route.CORRECTION_ISSUE,
                "head": {"sha": INSTALL_HEAD, "ref": route.CORRECTION_BRANCH, "repo": repo},
                "base": {"ref": "main", "sha": route.MAIN_PRE_INSTALL, "repo": repo}},
            COMMENT_PATH: enrollment,
            f"{PREFIX}/branches/main": {"name": "main", "protected": True, "commit": {"sha": MAIN}},
            f"{PREFIX}/branches/develop": {"name": "develop", "protected": True, "commit": {"sha": route.DEVELOP_PIN}},
            f"{PREFIX}/git/commits/{route.DEVELOP_PIN}": {"sha": route.DEVELOP_PIN, "tree": {"sha": route.DEVELOP_TREE}},
            f"{PREFIX}/git/commits/{MAIN}": {"sha": MAIN, "tree": {"sha": TREE},
                "parents": [{"sha": route.MAIN_PRE_INSTALL}, {"sha": INSTALL_HEAD}]},
            f"{PREFIX}/git/commits/{INSTALL_HEAD}": {"sha": INSTALL_HEAD, "tree": {"sha": TREE}},
            f"{PREFIX}/git/commits/{PREVIEW}": {"sha": PREVIEW, "tree": {"sha": TREE},
                "parents": [{"sha": route.DEVELOP_PIN}, {"sha": HEAD}]},
            f"{PREFIX}/git/commits/{HEAD}": {"sha": HEAD, "tree": {"sha": TREE}, "parents": [{"sha": route.DEVELOP_PIN}]}}
    inventories = {f"commits/{MAIN}/pulls": [{"number": INSTALL_PR, "merge_commit_sha": MAIN}],
                   f"issues/{route.PARITY_ISSUE}/comments": [copy.deepcopy(enrollment)],
                   "pulls?state=open&base=develop": [copy.deepcopy(pr)]}
    edit = {"__typename": "IssueComment", "id": "IC_fixture83", "body": body,
            "lastEditedAt": None, "includesCreatedEdit": False}
    monkeypatch.setattr(route, "comment_edit_state", lambda _: edit)
    digest = contract.digest(contract.canonical(contract.review_snapshot(enrollment, route.REPO, route.PARITY_ISSUE)))
    target = route.ParityTarget(21, route.PARITY_ISSUE, HEAD, MAIN, PREVIEW, TREE, ENROLL_COMMENT, digest)
    return data, event, inventories, edit, target


@pytest.mark.parametrize("mutation", [None, "main-drift", "not-protected",
                                      "wrong-old-tree", "wrong-head-tree", "foreign-wake", "stale-wake", "foreign-pr",
                                      "wrong-issue", "multi-global-pr", "unmerged-installer", "wrong-installer-parent",
                                      "wrong-installer-tree", "branch-history", "wrong-installer-branch",
                                      "wrong-installer-issue", "ambiguous-installer", "preview-drift",
                                      "preview-tree-drift", "preview-parents-drift"])
def test_routing_requires_protected_pins_and_exact_installed_tree(mutation, state):
    data, event, inventories, _, target = state
    if mutation in {"main-drift", "develop-drift"}:
        data[f"{PREFIX}/branches/{mutation.split('-')[0]}"]["commit"]["sha"] = "d" * 40
    elif mutation == "not-protected":
        data[f"{PREFIX}/branches/develop"]["protected"] = False
    elif mutation == "wrong-head-tree":
        data[f"{PREFIX}/git/commits/{HEAD}"]["tree"]["sha"] = "d" * 40
    elif mutation == "wrong-old-tree":
        data[f"{PREFIX}/git/commits/{route.DEVELOP_PIN}"]["tree"]["sha"] = "d" * 40
    elif mutation == "foreign-wake":
        event["workflow_run"]["path"] = ".github/workflows/other.yml"
    elif mutation == "stale-wake":
        event["workflow_run"]["head_sha"] = "d" * 40
    inventory = inventories["pulls?state=open&base=develop"]
    if mutation == "foreign-pr":
        data[f"{PREFIX}/pulls/21"]["head"]["repo"] = {"full_name": "elsewhere/repo"}
    elif mutation == "wrong-issue":
        data[f"{PREFIX}/pulls/21"]["test_issue"] = 197
    elif mutation == "multi-global-pr":
        inventory.append({**inventory[0], "number": 90, "draft": True})
    elif mutation == "unmerged-installer":
        data[f"{PREFIX}/pulls/{INSTALL_PR}"]["merged"] = False
    elif mutation == "wrong-installer-parent":
        data[f"{PREFIX}/git/commits/{MAIN}"]["parents"].reverse()
    elif mutation == "wrong-installer-tree":
        data[f"{PREFIX}/git/commits/{INSTALL_HEAD}"]["tree"]["sha"] = "4" * 40
    elif mutation == "branch-history":
        data[f"{PREFIX}/git/commits/{HEAD}"]["parents"].append({"sha": "e" * 40})
    elif mutation == "wrong-installer-branch":
        data[f"{PREFIX}/pulls/{INSTALL_PR}"]["head"]["ref"] = "other-branch"
    elif mutation == "wrong-installer-issue":
        data[f"{PREFIX}/pulls/{INSTALL_PR}"]["test_issue"] = 224
    elif mutation == "ambiguous-installer":
        inventories[f"commits/{MAIN}/pulls"].append({"number": 217, "merge_commit_sha": MAIN})
    elif mutation == "preview-drift":
        data[f"{PREFIX}/pulls/21"]["merge_commit_sha"] = "6" * 40
    elif mutation == "preview-tree-drift":
        data[f"{PREFIX}/git/commits/{PREVIEW}"]["tree"]["sha"] = "6" * 40
    elif mutation == "preview-parents-drift":
        data[f"{PREFIX}/git/commits/{PREVIEW}"]["parents"].reverse()

    def pages(repo, endpoint):
        assert repo == route.REPO
        return inventories[endpoint]

    def select():
        return route.select_bridge(data.__getitem__, pages, lambda pr: pr["test_issue"],
                                   lambda *_: [(21, route.PARITY_ISSUE)], route.REPO, event, route.SOURCE, MAIN)

    if mutation:
        with pytest.raises(ValueError):
            select()
    else:
        assert select() == target


def test_new_protected_develop_does_not_use_the_temporary_pin(state):
    data, event, _, _, _ = state
    data[f"{PREFIX}/branches/develop"]["commit"]["sha"] = "d" * 40
    assert route.select_bridge(data.__getitem__, lambda *_: [], lambda pr: pr["test_issue"],
                               lambda *_: [(21, route.PARITY_ISSUE)], route.REPO, event, route.SOURCE, MAIN) is None


@pytest.mark.parametrize("kind", [
    "absent", "multiple", "owner-id", "association", "via-app", "wrong-issue", "before-install",
    "list-readback-drift", "edited-same-second", "edit-history-unavailable", "invalid-record", "duplicate-key",
])
def test_enrollment_authority_is_mandatory_before_event_target_resolution(kind, state):
    data, event, inventories, edit, _ = state
    rows = inventories[f"issues/{route.PARITY_ISSUE}/comments"]
    if kind == "absent":
        rows.clear()
    elif kind == "multiple":
        rows.append(copy.deepcopy(rows[0]))
    elif kind == "edited-same-second":
        edit["lastEditedAt"] = data[COMMENT_PATH]["created_at"]
    elif kind == "edit-history-unavailable":
        edit.clear()
    else:
        raw = data[COMMENT_PATH]
        if kind == "owner-id":
            raw["user"]["id"] += 1
        elif kind == "association":
            raw["author_association"] = "MEMBER"
        elif kind == "via-app":
            raw["performed_via_github_app"] = {"id": 12}
        elif kind == "wrong-issue":
            raw["issue_url"] = f"https://api.github.com{PREFIX}/issues/197"
        elif kind == "before-install":
            raw["created_at"] = raw["updated_at"] = data[f"{PREFIX}/pulls/{INSTALL_PR}"]["merged_at"]
        elif kind == "list-readback-drift":
            raw["body"] += "\n"
        elif kind == "invalid-record":
            raw["body"] = raw["body"].replace('"schema_version": 1', '"schema_version": true')
        elif kind == "duplicate-key":
            raw["body"] = raw["body"].replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
        if kind != "list-readback-drift":
            rows[:] = [copy.deepcopy(raw)]
            edit["body"] = raw["body"]

    def no_event_resolution(*_):
        pytest.fail("event target must not supply missing pre-authorization")

    with pytest.raises(ValueError):
        route.select_bridge(data.__getitem__, lambda _, e: inventories[e], lambda pr: pr["test_issue"],
                            no_event_resolution, route.REPO, event, route.SOURCE, MAIN)


def test_valid_registration_never_routes_another_event_pr(state):
    data, event, inventories, _, _ = state
    assert route.select_bridge(data.__getitem__, lambda _, e: inventories[e], lambda pr: pr["test_issue"],
                               lambda *_: [(22, route.PARITY_ISSUE)], route.REPO, event, route.SOURCE, MAIN) is None


@pytest.mark.parametrize("route_state", ["ordinary-main", "temporary-refused", "develop"])
def test_current_dispatch_preserves_normal_verifier_without_loading_pin(route_state, state, monkeypatch, tmp_path):
    data, event, inventories, _, _ = state
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    targets = [(21, route.PARITY_ISSUE)] if route_state == "temporary-refused" else [(19, 20)]
    if route_state == "temporary-refused":
        inventories[f"issues/{route.PARITY_ISSUE}/comments"].clear()
    runner = SimpleNamespace(api=data.__getitem__, pages=lambda _, e: inventories[e],
                             linked_issue=lambda pr: pr["test_issue"], resolve_targets=lambda *_: targets)
    monkeypatch.setattr(route, "load_runner", lambda p: runner if p == route.ROOT else pytest.fail("unexpected pin"))
    monkeypatch.setattr(route, "run_child", lambda *_: pytest.fail("unexpected privileged route"))
    monkeypatch.setenv("GITHUB_REF", "refs/heads/develop" if route_state == "develop" else route.SOURCE)
    monkeypatch.setenv("GITHUB_WORKFLOW_SHA", MAIN)
    commands = []
    monkeypatch.setattr(route.subprocess, "run", lambda cmd, **_: commands.append(cmd) or SimpleNamespace(returncode=3))
    args = SimpleNamespace(repo=route.REPO, event=event_path, pinned=tmp_path, packet_root=None)
    assert route.run_current(args) == 3
    assert commands == [[sys.executable, "-B", str(route.ROOT / "scripts/verify_session_review.py"),
                         "--repo", route.REPO, "--event", str(event_path)]]


@pytest.mark.parametrize("kind", ["valid", "detached-child-digest", "revoked-before-child"])
def test_pinned_cli_reloads_authority_before_running_verifier(kind, state, monkeypatch, tmp_path):
    data, event, inventories, _, target = state
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    calls = []
    runner = SimpleNamespace(
        api=data.__getitem__, pages=lambda _, endpoint: inventories[endpoint],
        linked_issue=lambda pr: pr["test_issue"], resolve_targets=lambda *_: [(21, route.PARITY_ISSUE)],
        evaluate=lambda *args: calls.append(args) or 0,
    )
    monkeypatch.setattr(route, "prove_checkout", lambda path: None)
    monkeypatch.setattr(route, "load_runner", lambda path: runner)
    monkeypatch.setattr(route, "git", lambda *_: MAIN)
    monkeypatch.setenv("GITHUB_REF", route.SOURCE)
    monkeypatch.setenv("GITHUB_WORKFLOW_SHA", MAIN)
    digest = "0" * 64 if kind == "detached-child-digest" else target.comment_digest
    if kind == "revoked-before-child":
        inventories[f"issues/{route.PARITY_ISSUE}/comments"].clear()
    monkeypatch.setattr(sys, "argv", ["dispatch_session_review.py", "--repo", route.REPO,
                                    "--event", str(event_path), "--pinned", str(tmp_path),
                                    "--number", "21", "--issue", str(route.PARITY_ISSUE), "--head", HEAD,
                                    "--main-sha", MAIN, "--enrollment-id", str(ENROLL_COMMENT),
                                    "--enrollment-digest", digest])
    assert route.main() == (0 if kind == "valid" else 2)
    assert calls == ([(route.REPO, 21, route.PARITY_ISSUE, None)] if kind == "valid" else [])


@pytest.mark.parametrize("mode", ["ok", "graphql-error", "not-authenticated", "truncated"])
def test_edit_history_transport_uses_fixed_read_query_and_fails_closed(mode, monkeypatch):
    node = {"id": "IC_fixture83", "body": "fixture", "lastEditedAt": None,
            "includesCreatedEdit": False, "__typename": "IssueComment"}

    def run(command, **kwargs):
        assert command == ["gh", "api", "--hostname", "github.com", "graphql", "--input", "-"]
        request = json.loads(kwargs["input"])
        assert request == {"query": route.COMMENT_QUERY, "variables": {"id": "IC_fixture83"}}
        assert request["query"].startswith("query(")
        response = {"data": {"node": node}}
        if mode == "graphql-error":
            response["errors"] = [{"message": "fixture-only diagnostic"}]
        return SimpleNamespace(returncode=(1 if mode == "not-authenticated" else 0),
                               stdout=(b" " * 16385 if mode == "truncated" else json.dumps(response).encode()))

    monkeypatch.setattr(route.subprocess, "run", run)
    if mode == "ok":
        assert route.comment_edit_state("IC_fixture83") == node
    else:
        with pytest.raises(ValueError, match="edit history unavailable"):
            route.comment_edit_state("IC_fixture83")


@pytest.mark.parametrize("kind", ["same", "other-check", "base-drift", "other-write", "deleted-enrollment",
                                  "edited-enrollment", "replaced-enrollment", "drift-preview"])
def test_scoped_verifier_rereads_pins_before_any_check_write(kind, state):
    data, _, inventories, edit, target = state
    check_path = f"{PREFIX}/check-runs/78"
    data[check_path] = {"head_sha": HEAD, "app": {"id": 15368}, "name": "Verify session review (exact SHA)"}
    target_path = check_path
    writes = []
    if kind == "other-check":
        data[check_path]["head_sha"] = "f" * 40
    if kind == "base-drift":
        data[f"{PREFIX}/pulls/21"]["base"]["sha"] = "f" * 40
    if kind == "other-write":
        target_path = f"{PREFIX}/issues/21/comments"
    if kind == "deleted-enrollment":
        inventories[f"issues/{route.PARITY_ISSUE}/comments"].clear()
    if kind == "edited-enrollment":
        edit["lastEditedAt"] = data[COMMENT_PATH]["created_at"]
    if kind == "replaced-enrollment":
        # Same valid routing body but a different original issue comment.
        alternate = {**data[COMMENT_PATH], "id": ENROLL_COMMENT + 1,
                     "url": f"https://api.github.com{PREFIX}/issues/comments/{ENROLL_COMMENT + 1}"}
        data[f"{PREFIX}/issues/comments/{ENROLL_COMMENT + 1}"] = alternate
        inventories[f"issues/{route.PARITY_ISSUE}/comments"] = [alternate]
    if kind == "drift-preview":
        data[f"{PREFIX}/pulls/21"]["merge_commit_sha"] = None

    def api(path, *, method="GET", data=None):
        if method != "GET":
            writes.append((method, path, data))
        return copy.deepcopy(responses.get(path, {}))

    responses = data
    guarded = route.scoped_api(api, lambda _, endpoint: inventories[endpoint],
                               lambda pr: pr["test_issue"], target)
    if kind == "same":
        guarded(target_path, method="PATCH", data={"status": "completed"})
        assert len(writes) == 1
    else:
        with pytest.raises(ValueError):
            guarded(target_path, method="PATCH", data={"status": "completed"})
        assert not writes


def test_pristine_checkout_checks_head_tree_and_extra_files(tmp_path, monkeypatch):
    responses = (route.DEVELOP_PIN, route.DEVELOP_TREE, "")
    calls = []

    def git(root, *args):
        assert root == tmp_path
        calls.append(args)
        return responses[len(calls) - 1]

    monkeypatch.setattr(route, "git", git)
    route.prove_checkout(tmp_path)
    assert calls[-1] == ("status", "--porcelain", "--untracked-files=all", "--ignored")
    responses = (route.DEVELOP_PIN, route.DEVELOP_TREE, "!! other.py")
    calls.clear()
    with pytest.raises(ValueError, match="not pristine"):
        route.prove_checkout(tmp_path)
