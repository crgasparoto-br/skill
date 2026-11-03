#!/usr/bin/env python3
"""Fail-closed event routing to live PRs; webhook fields are locator hints only."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "entregar-issue" / "scripts"))

import verify_session_review as session_runner
from solo_audit_contract import canonical_issue_reference
from solo_audit_source import ALLOWED_BRANCHES, SHA_RE, require


def _open_pull_requests(repo: str) -> list[dict[str, Any]]:
    return session_runner.pages(repo, "pulls?state=open&sort=updated&direction=desc")


def resolve_targets(repo: str, event: dict[str, Any], event_name: str) -> list[tuple[int, int | None]]:
    """Use webhook values only to locate a live PR; current REST data is authority."""
    require(isinstance(event, dict) and isinstance(event.get("repository"), dict)
            and event["repository"].get("full_name") == repo,
            "event repository differs from trusted repository")
    require(event_name in {"pull_request_target", "pull_request_review", "issue_comment", "issues", "workflow_run", "push"},
            "unsupported event for solo audit gate")
    numbers: list[int] = []
    target_issue: int | None = None
    if event_name in {"pull_request_target", "pull_request_review"}:
        pull = event.get("pull_request")
        number = pull.get("number") if isinstance(pull, dict) else None
        require(type(number) is int and number > 0, "PR event number is malformed")
        numbers = [number]
    elif event_name == "issue_comment":
        issue = event.get("issue")
        if not isinstance(issue, dict) or not isinstance(issue.get("pull_request"), dict):
            return []
        number = issue.get("number")
        require(type(number) is int and number > 0, "PR comment event number is malformed")
        numbers = [number]
    elif event_name == "issues":
        issue = event.get("issue")
        if not isinstance(issue, dict) or isinstance(issue.get("pull_request"), dict):
            return []
        target_issue = issue.get("number")
        require(type(target_issue) is int and target_issue > 0, "issue event number is malformed")
        for pr in _open_pull_requests(repo):
            number = pr.get("number")
            if type(number) is not int or number < 1:
                continue
            try:
                linked = canonical_issue_reference(pr.get("body"))
            except ValueError:
                continue
            if linked == target_issue:
                numbers.append(number)
    elif event_name == "workflow_run":
        run = event.get("workflow_run")
        require(isinstance(run, dict) and run.get("event") == "pull_request",
                "workflow completion is not a pull_request run")
        if (run.get("head_repository") or {}).get("full_name") != repo:
            return []
        links = run.get("pull_requests")
        if isinstance(links, list):
            for pull in links:
                number = pull.get("number") if isinstance(pull, dict) else None
                if type(number) is int and number > 0:
                    numbers.append(number)
        if not numbers:
            head_sha = run.get("head_sha")
            require(isinstance(head_sha, str) and SHA_RE.fullmatch(head_sha),
                    "workflow completion HEAD is malformed")
            associated = session_runner.pages(repo, f"commits/{head_sha}/pulls")
            numbers = [item["number"] for item in associated
                       if type(item.get("number")) is int and item["number"] > 0
                       and (item.get("head") or {}).get("repo", {}).get("full_name") == repo]
    else:
        ref = event.get("ref")
        require(ref in {"refs/heads/develop", "refs/heads/main"}, "push is outside protected branches")
        numbers = [pr["number"] for pr in _open_pull_requests(repo)
                   if type(pr.get("number")) is int and pr["number"] > 0]

    output: list[tuple[int, int | None]] = []
    for number in sorted(set(numbers)):
        pr = session_runner.api(f"/repos/{repo}/pulls/{number}")
        if not isinstance(pr, dict) or pr.get("state") != "open":
            continue
        base = pr.get("base")
        if not isinstance(base, dict) or base.get("ref") not in ALLOWED_BRANCHES:
            continue
        if target_issue is not None:
            try:
                linked = canonical_issue_reference(pr.get("body"))
            except ValueError:
                # A malformed link on a candidate found during the issue event
                # cannot be treated as a successful binding; evaluate and fail it.
                output.append((number, target_issue))
                continue
            if linked != target_issue:
                continue
            output.append((number, target_issue))
        else:
            output.append((number, None))
    return output
