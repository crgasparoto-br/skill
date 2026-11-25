"""The transition is routing only, not a second source of review authority."""
from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
route = importlib.import_module("dispatch_session_review")
HEAD, MAIN, TREE = "a" * 40, "b" * 40, "c" * 40
PREFIX = f"/repos/{route.REPO}"
TARGET = route.ParityTarget(21, route.PARITY_ISSUE, HEAD, MAIN)
INSTALL_HEAD = "f" * 40


def fixture():
    repo = {"full_name": route.REPO}
    pr = {"number": 21, "state": "open", "draft": False, "test_issue": route.PARITY_ISSUE,
          "head": {"sha": HEAD, "repo": repo, "ref": route.PARITY_BRANCH},
          "base": {"ref": "develop", "sha": route.DEVELOP_PIN, "repo": repo}}
    event = {"repository": repo, "workflow_run": {
        "event": "pull_request", "head_repository": repo, "head_sha": HEAD,
        "path": ".github/workflows/handoff-evidence.yml"}}
    data = {f"{PREFIX}/pulls/21": pr,
            f"{PREFIX}/pulls/{route.INSTALLER_PR}": {
                "number": route.INSTALLER_PR, "merged": True, "state": "closed", "merge_commit_sha": MAIN,
                "head": {"sha": INSTALL_HEAD, "repo": repo}, "base": {"ref": "main", "repo": repo}},
            f"{PREFIX}/branches/main": {"name": "main", "protected": True, "commit": {"sha": MAIN}},
            f"{PREFIX}/branches/develop": {"name": "develop", "protected": True, "commit": {"sha": route.DEVELOP_PIN}},
            f"{PREFIX}/git/commits/{route.DEVELOP_PIN}": {"sha": route.DEVELOP_PIN, "tree": {"sha": route.DEVELOP_TREE}},
            f"{PREFIX}/git/commits/{MAIN}": {"sha": MAIN, "tree": {"sha": TREE},
                "parents": [{"sha": route.MAIN_PRE_INSTALL}, {"sha": INSTALL_HEAD}]},
            f"{PREFIX}/git/commits/{INSTALL_HEAD}": {"sha": INSTALL_HEAD, "tree": {"sha": TREE}},
            f"{PREFIX}/git/commits/{HEAD}": {"sha": HEAD, "tree": {"sha": TREE}, "parents": [{"sha": route.DEVELOP_PIN}]}}
    return data, event


@pytest.mark.parametrize("mutation", [None, "main-drift", "develop-drift", "not-protected",
                                      "wrong-old-tree", "wrong-head-tree", "foreign-wake", "stale-wake", "foreign-pr",
                                      "wrong-issue", "multi-global-pr", "unmerged-installer", "wrong-installer-parent",
                                      "wrong-installer-tree", "branch-history"])
def test_routing_requires_protected_pins_and_exact_installed_tree(mutation):
    data, event = fixture()
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
    inventory = [copy.deepcopy(data[f"{PREFIX}/pulls/21"])]
    if mutation == "foreign-pr":
        data[f"{PREFIX}/pulls/21"]["head"]["repo"] = {"full_name": "elsewhere/repo"}
    elif mutation == "wrong-issue":
        data[f"{PREFIX}/pulls/21"]["test_issue"] = 197
    elif mutation == "multi-global-pr":
        inventory.append({**inventory[0], "number": 90, "draft": True})
    elif mutation == "unmerged-installer":
        data[f"{PREFIX}/pulls/{route.INSTALLER_PR}"]["merged"] = False
    elif mutation == "wrong-installer-parent":
        data[f"{PREFIX}/git/commits/{MAIN}"]["parents"].reverse()
    elif mutation == "wrong-installer-tree":
        data[f"{PREFIX}/git/commits/{INSTALL_HEAD}"]["tree"]["sha"] = "4" * 40
    elif mutation == "branch-history":
        data[f"{PREFIX}/git/commits/{HEAD}"]["parents"].append({"sha": "e" * 40})

    def pages(repo, endpoint):
        assert repo == route.REPO and endpoint == "pulls?state=open&base=develop"
        return inventory

    def select():
        return route.select_bridge(data.__getitem__, pages, lambda pr: pr["test_issue"],
                                   lambda *_: [(21, route.PARITY_ISSUE)], route.REPO, event, route.SOURCE, MAIN)

    if mutation:
        with pytest.raises(ValueError):
            select()
    else:
        assert select() == TARGET


def test_new_protected_develop_does_not_use_the_temporary_pin():
    data, event = fixture()
    data[f"{PREFIX}/pulls/21"]["base"]["sha"] = "d" * 40
    assert route.select_bridge(data.__getitem__, lambda *_: [], lambda pr: pr["test_issue"],
                               lambda *_: [(21, route.PARITY_ISSUE)], route.REPO, event, route.SOURCE, MAIN) is None


@pytest.mark.parametrize("kind", ["same", "other-check", "base-drift", "other-write"])
def test_scoped_verifier_rereads_pins_before_any_check_write(kind):
    data, _ = fixture()
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

    def api(path, *, method="GET", data=None):
        if method != "GET":
            writes.append((method, path, data))
        return copy.deepcopy(responses.get(path, {}))

    responses = data
    guarded = route.scoped_api(api, lambda *_: [responses[f"{PREFIX}/pulls/21"]],
                               lambda pr: pr["test_issue"], TARGET)
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
