#!/usr/bin/env python3
"""Fail-closed event routing to live PRs; webhook fields are locator hints only."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "entregar-issue" / "scripts"))

import verify_session_review as session_runner  # noqa: E402 - sys.path ajustado acima antes do import local
from solo_audit_contract import canonical_issue_reference  # noqa: E402 - sys.path ajustado acima antes do import local
from solo_audit_source import ALLOWED_BRANCHES, REPOSITORY_RE, SHA_RE, require  # noqa: E402 - sys.path ajustado acima antes do import local

_SUPPORTED_EVENTS = {
    "pull_request_target",
    "pull_request_review",
    "issue_comment",
    "issues",
    "workflow_run",
    "push",
}


def _open_pull_requests(repo: str) -> list[dict[str, Any]]:
    pulls = session_runner.pages(repo, "pulls?state=open&sort=updated&direction=desc")
    require(isinstance(pulls, list), "open pull-request inventory is malformed")
    for pull in pulls:
        require(isinstance(pull, dict), "open pull-request inventory entry is malformed")
        _positive_number(pull.get("number"), "open pull-request number is malformed")
    return pulls


def _is_positive_number(value: Any) -> bool:
    return type(value) is int and value > 0


def _positive_number(value: Any, message: str) -> int:
    require(_is_positive_number(value), message)
    return value


def _validate_event(repo: str, event: dict[str, Any], event_name: str) -> None:
    require(
        isinstance(event, dict)
        and isinstance(event.get("repository"), dict)
        and event["repository"].get("full_name") == repo,
        "event repository differs from trusted repository",
    )
    require(event_name in _SUPPORTED_EVENTS, "unsupported event for solo audit gate")


def _trusted_api_base() -> str:
    base = os.environ.get("GITHUB_API_URL")
    require(isinstance(base, str) and bool(base), "trusted GitHub API base is unavailable")
    parsed = urlsplit(base)
    require(
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment,
        "trusted GitHub API base is malformed",
    )
    return base.rstrip("/")


def _pull_request_event_numbers(event: dict[str, Any]) -> list[int]:
    pull = event.get("pull_request")
    number = pull.get("number") if isinstance(pull, dict) else None
    return [_positive_number(number, "PR event number is malformed")]


def _issue_comment_event_numbers(event: dict[str, Any]) -> list[int]:
    issue = event.get("issue")
    require(isinstance(issue, dict), "issue-comment issue object is malformed")
    number = _positive_number(issue.get("number"), "issue-comment issue number is malformed")
    if "pull_request" not in issue:
        return []
    require(isinstance(issue["pull_request"], dict), "issue-comment pull-request link is malformed")
    return [number]


def _issue_event_numbers(repo: str, event: dict[str, Any]) -> tuple[list[int], int | None]:
    issue = event.get("issue")
    require(isinstance(issue, dict), "issue event issue object is malformed")
    target_issue = _positive_number(issue.get("number"), "issue event number is malformed")
    if "pull_request" in issue:
        pull_request = issue["pull_request"]
        require(isinstance(pull_request, dict), "issue event pull-request link is malformed")
        expected_url = f"{_trusted_api_base()}/repos/{repo}/pulls/{target_issue}"
        require(pull_request.get("url") == expected_url, "issue event pull-request URL is malformed")
        return [], None
    numbers: list[int] = []
    for pr in _open_pull_requests(repo):
        number = pr["number"]
        linked = canonical_issue_reference(pr.get("body"))
        if linked == target_issue:
            numbers.append(number)
    return numbers, target_issue


def _workflow_link_numbers(links: Any) -> list[int]:
    require(isinstance(links, list), "workflow completion pull-request links are malformed")
    numbers: list[int] = []
    for pull in links:
        require(isinstance(pull, dict), "workflow completion pull-request link is malformed")
        numbers.append(_positive_number(pull.get("number"), "workflow completion PR number is malformed"))
    return numbers


def _same_repository_head(item: Any, repo: str) -> bool:
    require(isinstance(item, dict), "workflow-associated PR entry is malformed")
    _positive_number(item.get("number"), "workflow-associated PR number is malformed")
    head = item.get("head")
    require(isinstance(head, dict), "workflow-associated PR head is malformed")
    head_repo = head.get("repo")
    require(isinstance(head_repo, dict), "workflow-associated PR head repository is malformed")
    full_name = head_repo.get("full_name")
    require(isinstance(full_name, str) and REPOSITORY_RE.fullmatch(full_name) is not None,
            "workflow-associated PR head repository identity is malformed")
    return full_name == repo


def _workflow_associated_numbers(repo: str, head_sha: str) -> list[int]:
    associated = session_runner.pages(repo, f"commits/{head_sha}/pulls")
    require(isinstance(associated, list), "workflow-associated PR response is malformed")
    return [item["number"] for item in associated if _same_repository_head(item, repo)]


def _workflow_event_numbers(repo: str, event: dict[str, Any]) -> list[int]:
    run = event.get("workflow_run")
    require(
        isinstance(run, dict) and run.get("event") == "pull_request",
        "workflow completion is not a pull_request run",
    )
    head_repository = run.get("head_repository")
    require(isinstance(head_repository, dict), "workflow completion head repository is malformed")
    full_name = head_repository.get("full_name")
    require(isinstance(full_name, str) and REPOSITORY_RE.fullmatch(full_name) is not None,
            "workflow completion head repository identity is malformed")
    head_sha = run.get("head_sha")
    require(isinstance(head_sha, str) and SHA_RE.fullmatch(head_sha), "workflow completion HEAD is malformed")
    numbers = _workflow_link_numbers(run.get("pull_requests"))
    if full_name != repo:
        return []
    if numbers:
        return numbers
    return _workflow_associated_numbers(repo, head_sha)


def _push_event_numbers(repo: str, event: dict[str, Any]) -> list[int]:
    ref = event.get("ref")
    require(isinstance(ref, str) and ref in {"refs/heads/develop", "refs/heads/main"},
            "push is outside protected branches")
    return [pr["number"] for pr in _open_pull_requests(repo)]


def _event_numbers(repo: str, event: dict[str, Any], event_name: str) -> tuple[list[int], int | None]:
    if event_name in {"pull_request_target", "pull_request_review"}:
        return _pull_request_event_numbers(event), None
    if event_name == "issue_comment":
        return _issue_comment_event_numbers(event), None
    if event_name == "issues":
        return _issue_event_numbers(repo, event)
    if event_name == "workflow_run":
        return _workflow_event_numbers(repo, event), None
    return _push_event_numbers(repo, event), None


def _live_pr_routing_fields(repo: str, number: int, pr: Any) -> tuple[str, str]:
    require(isinstance(pr, dict), "live PR response is malformed")
    returned_number = _positive_number(pr.get("number"), "live PR number is malformed")
    require(returned_number == number, "live PR response identity differs from requested PR")
    state = pr.get("state")
    require(isinstance(state, str) and state in {"open", "closed"}, "live PR state is malformed")
    base = pr.get("base")
    require(isinstance(base, dict), "live PR base is malformed")
    base_repo = base.get("repo")
    require(isinstance(base_repo, dict), "live PR base repository is malformed")
    base_name = base_repo.get("full_name")
    require(isinstance(base_name, str) and REPOSITORY_RE.fullmatch(base_name) is not None,
            "live PR base repository identity is malformed")
    require(base_name == repo, "live PR base repository differs from trusted repository")
    base_ref = base.get("ref")
    require(isinstance(base_ref, str) and bool(base_ref), "live PR base ref is malformed")
    base_sha = base.get("sha")
    require(isinstance(base_sha, str) and SHA_RE.fullmatch(base_sha), "live PR base SHA is malformed")
    draft = pr.get("draft")
    merged = pr.get("merged")
    require(type(draft) is bool and type(merged) is bool, "live PR draft/merged flags are malformed")
    require(isinstance(pr.get("body"), str), "live PR body is malformed")
    head = pr.get("head")
    require(isinstance(head, dict), "live PR head is malformed")
    head_sha = head.get("sha")
    require(isinstance(head_sha, str) and SHA_RE.fullmatch(head_sha), "live PR head SHA is malformed")
    head_ref = head.get("ref")
    require(isinstance(head_ref, str) and bool(head_ref), "live PR head ref is malformed")
    head_repo = head.get("repo")
    require(isinstance(head_repo, dict), "live PR head repository is malformed")
    head_name = head_repo.get("full_name")
    require(isinstance(head_name, str) and REPOSITORY_RE.fullmatch(head_name) is not None,
            "live PR head repository identity is malformed")
    return state, base_ref


def _authoritative_targets(
    repo: str,
    numbers: list[int],
    target_issue: int | None,
) -> list[tuple[int, int | None]]:
    output: list[tuple[int, int | None]] = []
    for number in sorted(set(numbers)):
        pr = session_runner.api(f"/repos/{repo}/pulls/{number}")
        state, base_ref = _live_pr_routing_fields(repo, number, pr)
        if state != "open":
            continue
        if base_ref not in ALLOWED_BRANCHES:
            continue
        if target_issue is None:
            output.append((number, None))
            continue
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
    return output


def resolve_targets(repo: str, event: dict[str, Any], event_name: str) -> list[tuple[int, int | None]]:
    """Use webhook values only to locate a live PR; current REST data is authority."""
    _validate_event(repo, event, event_name)
    numbers, target_issue = _event_numbers(repo, event, event_name)
    return _authoritative_targets(repo, numbers, target_issue)
