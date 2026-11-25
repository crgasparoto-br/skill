#!/usr/bin/env python3
"""Bridge one inspected protected-base parity transition without candidate execution."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = "crgasparoto-br/skill"
DEVELOP_PIN = "2b93611605dd1b9e905f9eda949333ed22e79cf9"
DEVELOP_TREE = "1124edbc243752e3b8c06fc64222d4198af243ee"
MAIN_PRE_INSTALL = "fb71aed75bc432f529e6511ec17399f4747a6f98"
INSTALLER_PR = 221
PARITY_ISSUE = 198
PARITY_BRANCH = "chore/198-sync-main-session-parity"
ROOT = Path(__file__).resolve().parents[1]
WAKE_PATHS = frozenset({
    ".github/workflows/validate.yml", ".github/workflows/github-audit-mcp.yml",
    ".github/workflows/handoff-evidence.yml", ".github/workflows/main-native-evidence.yml",
})
SOURCE = "refs/heads/main"
CHECK_NAME = "Verify session review (exact SHA)"
SHA = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True)
class ParityTarget:
    number: int
    issue: int
    head: str
    main: str


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], encoding="utf-8", timeout=25).strip()


def require_pr(pr: dict, target: ParityTarget, linked_issue) -> None:
    head, base = pr["head"], pr["base"]
    require(pr.get("number") == target.number and pr.get("state") == "open" and pr.get("draft") is False
            and head["sha"] == target.head and head["repo"]["full_name"] == REPO and head["ref"] == PARITY_BRANCH
            and base["ref"] == "develop" and base["sha"] == DEVELOP_PIN and base["repo"]["full_name"] == REPO,
            "protected develop parity PR changed")
    require(target.issue == PARITY_ISSUE and linked_issue(pr) == PARITY_ISSUE,
            "parity PR canonical issue changed")


def protected_tip(api, branch: str) -> str:
    row = api(f"/repos/{REPO}/branches/{branch}")
    require(row["name"] == branch and row["protected"] is True
            and isinstance(row["commit"]["sha"], str) and SHA.fullmatch(row["commit"]["sha"]) is not None,
            "protected branch identity missing")
    return row["commit"]["sha"]


def commit_tree(api, sha: str) -> str:
    row = api(f"/repos/{REPO}/git/commits/{sha}")
    require(row["sha"] == sha and isinstance(row["tree"]["sha"], str)
            and SHA.fullmatch(row["tree"]["sha"]) is not None, "authenticated tree unavailable")
    return row["tree"]["sha"]


def prove_installer(api, main: str) -> None:
    pr = api(f"/repos/{REPO}/pulls/{INSTALLER_PR}")
    head, base = pr["head"], pr["base"]
    require(pr.get("number") == INSTALLER_PR and pr.get("state") == "closed" and pr.get("merged") is True
            and pr.get("merge_commit_sha") == main
            and base.get("ref") == "main" and base["repo"]["full_name"] == REPO
            and head["repo"]["full_name"] == REPO and SHA.fullmatch(head["sha"]) is not None,
            "protected main is not the recorded merged installer")
    merged = api(f"/repos/{REPO}/git/commits/{main}")
    require(merged["sha"] == main and [item["sha"] for item in merged["parents"]] == [MAIN_PRE_INSTALL, head["sha"]],
            "installer merge lacks exact ordered main and approved installer parents")
    require(merged["tree"]["sha"] == commit_tree(api, head["sha"]),
            "installer merge tree differs from the reviewed installer HEAD")


def require_global_enrollment(pages, number: int) -> None:
    rows = pages(REPO, "pulls?state=open&base=develop")
    matches = [row["number"] for row in rows if row["state"] == "open"
               and row["head"]["ref"] == PARITY_BRANCH
               and (row["head"].get("repo") or {}).get("full_name") == REPO]
    require(matches == [number], "the exact same-repo parity branch has no unique open PR")


def prove_parity(api, pages, linked_issue, target: ParityTarget) -> None:
    require(protected_tip(api, "develop") == DEVELOP_PIN and protected_tip(api, "main") == target.main,
            "protected parity branches changed")
    prove_installer(api, target.main)
    require_global_enrollment(pages, target.number)
    require_pr(api(f"/repos/{REPO}/pulls/{target.number}"), target, linked_issue)
    require(commit_tree(api, DEVELOP_PIN) == DEVELOP_TREE, "protected develop tooling tree mismatch")
    material = api(f"/repos/{REPO}/git/commits/{target.head}")
    require(material["sha"] == target.head and [item["sha"] for item in material["parents"]] == [DEVELOP_PIN]
            and material["tree"]["sha"] == commit_tree(api, target.main),
            "transition PR must have exactly the protected main tree and sole pinned develop parent")


def require_wake(event: dict, repo: str) -> None:
    require(event.get("repository", {}).get("full_name") == repo, "foreign trigger repository")
    run = event.get("workflow_run")
    if run is not None:
        require(run.get("event") == "pull_request"
                and run.get("head_repository", {}).get("full_name") == repo
                and isinstance(run.get("path"), str) and run["path"].split("@", 1)[0] in WAKE_PATHS,
                "foreign workflow wake; not review evidence")


def select_bridge(api, pages, linked_issue, resolve_targets, repo: str, event: dict, ref: str, workflow_sha: str) -> ParityTarget | None:
    require_wake(event, repo)
    if repo != REPO or ref != SOURCE or not (event.get("workflow_run") or event.get("issue", {}).get("pull_request")):
        return None
    targets = resolve_targets(repo, event)
    if len(targets) != 1:
        return None  # existing verifier owns conflict handling, not the bridge
    number, issue = targets[0]
    pr = api(f"/repos/{repo}/pulls/{number}")
    if (issue != PARITY_ISSUE or pr.get("head", {}).get("ref") != PARITY_BRANCH
            or pr.get("base", {}).get("ref") != "develop" or pr.get("base", {}).get("sha") != DEVELOP_PIN):
        return None  # normal byte-equal path after the protected develop merge
    target = ParityTarget(number, issue, pr["head"]["sha"], workflow_sha)
    require(SHA.fullmatch(target.main) is not None and SHA.fullmatch(target.head) is not None,
            "missing exact protected parity SHA")
    if "workflow_run" in event:
        require(event["workflow_run"].get("head_sha") == target.head, "stale parity workflow wake")
    prove_parity(api, pages, linked_issue, target)
    return target


def load_runner(root: Path):
    sys.path.insert(0, str(root / "scripts"))
    return importlib.import_module("verify_session_review")


def prove_checkout(root: Path) -> None:
    require(git(root, "rev-parse", "HEAD") == DEVELOP_PIN and git(root, "rev-parse", "HEAD^{tree}") == DEVELOP_TREE
            and not git(root, "status", "--porcelain", "--untracked-files=all", "--ignored"),
            "pinned develop verifier checkout is unavailable or not pristine")


def scoped_api(api, pages, linked_issue, target: ParityTarget):
    pr_path = f"/repos/{REPO}/pulls/{target.number}"

    def call(path: str, *, method: str = "GET", data=None, **kwargs):
        if method != "GET":
            writer = f"/repos/{REPO}/check-runs"
            allowed_write = ((method == "POST" and path == writer)
                             or (method == "PATCH" and re.fullmatch(re.escape(writer) + r"/[1-9][0-9]*", path)))
            require(bool(allowed_write), "parity verifier is confined to the existing check writer")
            if method == "POST":
                require(isinstance(data, dict) and data.get("head_sha") == target.head
                        and data.get("name") == CHECK_NAME, "foreign parity check head or name")
            else:
                check = api(path)
                app_id = check.get("app", {}).get("id")
                require(check.get("head_sha") == target.head and type(app_id) is int and app_id == 15368
                        and check.get("name") == CHECK_NAME, "foreign parity check receipt")
            prove_parity(api, pages, linked_issue, target)
        response = api(path, method=method, data=data, **kwargs)
        if path == pr_path and method == "GET":
            require_pr(response, target, linked_issue)
        return response

    return call


def run_pinned(args) -> int:
    root = args.pinned.resolve()
    prove_checkout(root)
    runner = load_runner(root)
    target = ParityTarget(args.number, args.issue, args.head, args.main_sha)
    event = json.loads(args.event.read_bytes())
    require_wake(event, REPO)
    require(os.environ.get("GITHUB_REF") == SOURCE and os.environ.get("GITHUB_WORKFLOW_SHA") == target.main,
            "pinned verifier was not invoked by the protected default")
    prove_parity(runner.api, runner.pages, runner.linked_issue, target)
    require(runner.resolve_targets(REPO, event) == [(target.number, target.issue)], "parity target changed")
    runner.api = scoped_api(runner.api, runner.pages, runner.linked_issue, target)
    packet = args.packet_root / f"pr-{target.number}" / "review-packet.json" if args.packet_root else None
    return runner.evaluate(REPO, target.number, target.issue, packet)


def run_current(args) -> int:
    event = json.loads(args.event.read_bytes())
    runner = load_runner(ROOT)
    ref, sha = os.environ.get("GITHUB_REF", ""), os.environ.get("GITHUB_WORKFLOW_SHA", "")
    require_wake(event, args.repo)
    try:
        target = select_bridge(runner.api, runner.pages, runner.linked_issue,
                               runner.resolve_targets, args.repo, event, ref, sha)
    except (ValueError, OSError, KeyError, TypeError):
        target = None  # normal verifier still owns revocation/failure; never load old code
    if target:
        require(git(ROOT, "rev-parse", "HEAD") == target.main, "wrong default workflow checkout")
        result = run_child(args, target)
        if result == 0:
            return result
        # Do not preserve a stale green if the scoped verifier could not finish.
        if args.packet_root:
            return result
    if args.packet_root:
        targets = runner.resolve_targets(args.repo, event)
        if not targets:
            print("BLOCK: no eligible PR for this packet request", file=sys.stderr)
            return 1
        return max(runner.evaluate(args.repo, number, issue,
                                   args.packet_root / f"pr-{number}" / "review-packet.json")
                   for number, issue in targets)
    return subprocess.run([sys.executable, "-B", str(ROOT / "scripts/verify_session_review.py"),
                           "--repo", args.repo, "--event", str(args.event)], check=False).returncode


def run_child(args, target: ParityTarget) -> int:
    command = [sys.executable, "-IB", str(Path(__file__).resolve()), "--repo", args.repo,
               "--event", str(args.event), "--pinned", str(args.pinned),
               "--number", str(target.number), "--issue", str(target.issue),
               "--head", target.head, "--main-sha", target.main]
    if args.packet_root:
        command.extend(("--packet-root", str(args.packet_root)))
    return subprocess.run(command, check=False).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--event", required=True, type=Path)
    parser.add_argument("--pinned", required=True, type=Path)
    parser.add_argument("--packet-root", type=Path)
    parser.add_argument("--number", type=int)
    parser.add_argument("--issue", type=int)
    parser.add_argument("--head")
    parser.add_argument("--main-sha")
    args = parser.parse_args()
    try:
        if args.number is not None:
            require(args.repo == REPO and args.number > 0 and type(args.issue) is int and args.issue > 0
                    and isinstance(args.head, str) and SHA.fullmatch(args.head) is not None
                    and isinstance(args.main_sha, str) and SHA.fullmatch(args.main_sha) is not None,
                    "invalid pinned parity invocation")
            return run_pinned(args)
        return run_current(args)
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        print("BLOCK: protected session review dispatch failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
