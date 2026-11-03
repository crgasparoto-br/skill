#!/usr/bin/env python3
"""Exact-HEAD evidence checks and per-target Check Run lifecycle."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import verify_session_review as session_runner
from solo_audit_contract import ACCEPTED_TEXT, CHECK_NAME, require
from solo_audit_github import github_token
from solo_audit_source import SHA_RE
from verify_independent_pr_audit import (
    APP_ID,
    latest_reviews,
    page_all,
    required_checks_green,
    trusted_workflow_check,
)

if TYPE_CHECKING:
    from collections.abc import Callable


def provisional_external_id(pr_number: int, head: str, run_id: str) -> str:
    require(type(pr_number) is int and pr_number > 0 and SHA_RE.fullmatch(head) is not None
            and run_id.isdecimal() and int(run_id) > 0,
            "invalid provisional Check Run target")
    return f"sa:{run_id}:p{pr_number}:{head}"


def exact_external_id(identity: dict[str, Any], run_id: str) -> str:
    values = (
        identity.get("pull_request"), identity.get("issue"), identity.get("base_ref"),
        identity.get("base_sha"), identity.get("head_sha"), identity.get("merge_preview_sha"),
        identity.get("issue_body_sha256"),
    )
    pr_number, issue, base_ref, base_sha, head, preview, issue_hash = values
    require(type(pr_number) is int and pr_number > 0 and type(issue) is int and issue > 0,
            "invalid exact Check Run PR/issue identity")
    require(base_ref in {"develop", "main"} and all(
        isinstance(value, str) and SHA_RE.fullmatch(value)
        for value in (base_sha, head, preview)
    ), "invalid exact Check Run branch/SHA identity")
    require(isinstance(issue_hash, str) and len(issue_hash) == 64
            and all(char in "0123456789abcdef" for char in issue_hash),
            "invalid exact Check Run issue-body fingerprint")
    require(run_id.isdecimal() and int(run_id) > 0, "invalid Check Run Actions run ID")
    result = f"sa:{run_id}:p{pr_number}:i{issue}:r{base_ref}:{base_sha}:{head}:{preview}:{issue_hash}"
    require(len(result) <= 255, "exact Check Run target exceeds GitHub external_id bound")
    return result


def required_evidence(repo: str, identity: dict[str, Any]) -> list[int]:
    token = github_token()
    checks = session_runner.pages(
        repo, f"commits/{identity['head_sha']}/check-runs?filter=all", field="check_runs"
    )
    check_inventory = {"total_count": len(checks), "check_runs": checks}
    trusted = lambda name, check: trusted_workflow_check(
        repo, identity["pull_request"], name, check, identity["head_sha"], identity["base_sha"], token
    )
    required_checks_green(check_inventory, identity["head_sha"], identity["base_ref"], trusted)

    reviews = page_all(repo, f"pulls/{identity['pull_request']}/reviews", token)
    active = latest_reviews(reviews)
    require(not any(review.get("state") == "CHANGES_REQUESTED" for review in active.values()),
            "an outstanding GitHub request for changes blocks the solo check")
    required_names = {"Structure and tests", "Offline authorization tests"}
    if identity["base_ref"] == "develop":
        required_names.add("collect / Require certified semantic handoff (exact SHA)")
    matching = [item for item in checks if item.get("name") in required_names
                and item.get("head_sha") == identity["head_sha"] and (item.get("app") or {}).get("id") == APP_ID]
    return sorted(item["id"] for item in matching if type(item.get("id")) is int)


def begin_check(repo: str, head: str, pr_number: int, run_id: str) -> int:
    provisional_id = provisional_external_id(pr_number, head, run_id)
    # Never adopt or reopen a pre-existing check based on mutable metadata: all
    # workflows share the Actions app ID, so a candidate run could forge it.
    body = {
        "name": CHECK_NAME,
        "status": "in_progress",
        "external_id": provisional_id,
        "details_url": f"https://github.com/{repo}/actions/runs/{run_id}",
        "output": {
            "title": "Solo-context audit is being revalidated",
            "summary": "No third-party human approval is claimed; success is withheld pending live checks.",
            "text": "The trusted workflow is validating the exact PR, issue, signed comment, and required checks.",
        },
    }
    result = session_runner.api(f"/repos/{repo}/check-runs", method="POST", data={**body, "head_sha": head})
    status, conclusion = result.get("status"), result.get("conclusion")
    fail_closed = status in {"queued", "in_progress"} and conclusion is None
    require(result.get("head_sha") == head and result.get("name") == CHECK_NAME
            and result.get("external_id") == provisional_id
            and result.get("details_url") == f"https://github.com/{repo}/actions/runs/{run_id}"
            and (result.get("app") or {}).get("id") == APP_ID
            and type(result.get("id")) is int and result["id"] > 0 and fail_closed,
            "solo check did not enter a fail-closed state")
    return result["id"]


def publish_check(repo: str, head: str, pr_number: int, check_id: int | None,
                  run_id: str, conclusion: str, receipt: dict[str, Any],
                  identity: dict[str, Any] | None = None,
                  before_patch: Callable[[], None] | None = None) -> None:
    require(conclusion in {"success", "failure"} and run_id.isdecimal(), "invalid solo check publication")
    require(type(pr_number) is int and pr_number > 0, "invalid solo Check Run PR number")
    require(type(check_id) is int and check_id > 0,
            "trusted Check Run ID is unavailable; refusing to create a replacement")
    provisional_id = provisional_external_id(pr_number, head, run_id)
    target_id = exact_external_id(identity, run_id) if identity is not None else provisional_id
    if conclusion == "success":
        require(identity is not None and receipt.get("head_sha") == head
                and receipt.get("pull_request") == pr_number,
                "success receipt does not bind exact HEAD/PR")
        require(target_id == exact_external_id(identity, run_id), "success target identity is malformed")
        require(callable(before_patch), "success publication requires last-moment authority revalidation")
    summary = ACCEPTED_TEXT if conclusion == "success" else "Solo audit gate blocked; no third-party human approval is claimed."
    title = ACCEPTED_TEXT if conclusion == "success" else "Solo-context audit blocked"
    body = {
        "name": CHECK_NAME,
        "status": "completed",
        "conclusion": conclusion,
        "external_id": target_id,
        "details_url": f"https://github.com/{repo}/actions/runs/{run_id}",
        "output": {"title": title, "summary": summary,
                   "text": json.dumps(receipt, ensure_ascii=False, sort_keys=True)},
    }
    def verify_current_run() -> None:
        current = session_runner.api(f"/repos/{repo}/check-runs/{check_id}")
        require(current.get("id") == check_id and current.get("head_sha") == head
                and current.get("name") == CHECK_NAME
                and current.get("external_id") in {provisional_id, target_id}
                and current.get("details_url") == f"https://github.com/{repo}/actions/runs/{run_id}"
                and (current.get("app") or {}).get("id") == APP_ID
                and current.get("status") in {"queued", "in_progress"}
                and current.get("conclusion") is None,
                "solo Check Run belongs to another PR/target or publisher")

    verify_current_run()
    if conclusion == "success":
        before_patch()
        verify_current_run()
    result = session_runner.api(f"/repos/{repo}/check-runs/{check_id}", method="PATCH", data=body)
    require(result.get("head_sha") == head and result.get("name") == CHECK_NAME
            and result.get("external_id") == target_id
            and result.get("details_url") == f"https://github.com/{repo}/actions/runs/{run_id}"
            and (result.get("app") or {}).get("id") == APP_ID
            and result.get("status") == "completed" and result.get("conclusion") == conclusion,
            "solo Check Run publication was not confirmed as terminal")
