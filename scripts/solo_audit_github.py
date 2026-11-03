#!/usr/bin/env python3
"""Authenticated GitHub identity, configuration, and signed-report bindings."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "entregar-issue" / "scripts"))

import verify_session_review as session_runner
from handoff_merge_preview import require_event_merge_preview
from solo_audit_contract import (
    VARIABLE_NAMES,
    TrustedConfig,
    canonical_issue_reference,
    parse_report_comment_body,
    parse_trusted_config,
    select_report_comment,
)
from solo_audit_source import ALLOWED_BRANCHES, SHA_RE, require, sha256
from verify_independent_pr_audit import is_authorized_reviewer


def github_token() -> str:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    require(isinstance(token, str) and bool(token), "authenticated GitHub token unavailable")
    return token


def load_config(repo: str) -> TrustedConfig:
    variables = session_runner.pages(repo, "actions/variables", field="variables")
    names = [item.get("name") for item in variables]
    require(len(names) == len(set(names)), "Actions variable inventory contains duplicate names")
    values: dict[str, object] = {}
    for item in variables:
        if item.get("name") in VARIABLE_NAMES:
            values[item["name"]] = item.get("value")
    return parse_trusted_config(values, repo)


def current_target(repo: str, number: int, expected_issue: int | None = None,
                   *, pr: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve all report bindings from live authenticated GitHub sources."""
    pr = session_runner.api(f"/repos/{repo}/pulls/{number}") if pr is None else pr
    require(isinstance(pr, dict) and pr.get("number") == number, "live PR response is malformed")
    require(pr.get("state") == "open" and pr.get("merged") is not True,
            "solo attestation requires an open PR")
    require(pr.get("draft") is False, "draft PR cannot receive a solo audit attestation")
    base, head = pr.get("base"), pr.get("head")
    require(isinstance(base, dict) and isinstance(head, dict), "live PR base/head is malformed")
    require(isinstance(base.get("repo"), dict) and isinstance(head.get("repo"), dict)
            and base["repo"].get("full_name") == repo and head["repo"].get("full_name") == repo,
            "cross-repository candidate is not supported by the solo gate")
    base_ref, base_sha, head_sha = base.get("ref"), base.get("sha"), head.get("sha")
    require(base_ref in ALLOWED_BRANCHES and isinstance(base_sha, str) and SHA_RE.fullmatch(base_sha)
            and isinstance(head_sha, str) and SHA_RE.fullmatch(head_sha),
            "live PR branch identity is unsupported or malformed")
    issue_number = canonical_issue_reference(pr.get("body"))
    if expected_issue is not None:
        require(issue_number == expected_issue, "PR canonical issue changed during event routing")
    issue = session_runner.api(f"/repos/{repo}/issues/{issue_number}")
    require(isinstance(issue, dict) and issue.get("number") == issue_number
            and "pull_request" not in issue and isinstance(issue.get("body"), str),
            "canonical issue body is unavailable")

    # Reuse the authenticated merge-preview resolver used by handoff certification.
    synthetic_event = {
        "repository": {"full_name": repo},
        "pull_request": {
            "number": number,
            "merge_commit_sha": pr.get("merge_commit_sha"),
            "base": {"ref": base_ref, "sha": base_sha, "repo": {"full_name": repo}},
            "head": {"sha": head_sha, "repo": {"full_name": repo}},
        },
    }
    prior_mode = os.environ.get("SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW")
    os.environ["SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW"] = "1"
    try:
        with tempfile.TemporaryDirectory(prefix="solo-audit-preview-") as temporary:
            event_path = Path(temporary) / "live-pr-event.json"
            event_path.write_bytes(session_runner.canonical(synthetic_event))
            preview_sha = require_event_merge_preview(event_path, repo, number, head_sha, base_sha)
    finally:
        if prior_mode is None:
            os.environ.pop("SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW", None)
        else:
            os.environ["SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW"] = prior_mode

    identity = {
        "repository": repo,
        "pull_request": number,
        "issue": issue_number,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "merge_preview_sha": preview_sha,
        "issue_body_sha256": sha256(issue["body"].encode("utf-8")),
    }
    return identity, pr


def require_unique_open_pr_head(repo: str, number: int, head_sha: str) -> None:
    """Fail closed when a commit-scoped GitHub check could ambiguously cover PRs."""
    associated = session_runner.pages(repo, f"commits/{head_sha}/pulls")
    open_numbers = {
        item.get("number") for item in associated
        if item.get("state") == "open" and item.get("head", {}).get("sha") == head_sha
        and type(item.get("number")) is int and item["number"] > 0
    }
    require(number in open_numbers, "live commit-to-PR inventory omitted the current PR")
    require(open_numbers == {number},
            "multiple open PRs share one HEAD; commit-scoped solo check is ambiguous")


def report_comment(repo: str, number: int, config: TrustedConfig) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    comments = session_runner.pages(repo, f"issues/{number}/comments")
    comment = select_report_comment(comments)
    snapshot = session_runner.review_snapshot(comment, repo, number)
    require(snapshot["created_at"] == snapshot["updated_at"],
            "edited audit comment is revoked; publish a new immutable comment")
    user = comment.get("user") or {}
    require(type(user.get("id")) is int and user["id"] == config.operator_id
            and user.get("type") == "User", "comment author does not match the configured solo operator")
    login = user.get("login")
    require(isinstance(login, str) and is_authorized_reviewer(repo, login, github_token()),
            "comment author lacks current write-capable repository permission")
    raw_report, report = parse_report_comment_body(comment.get("body"))
    require(type(report.get("operator_github_id")) is int
            and report.get("operator_github_id") == config.operator_id,
            "signed operator ID does not match trusted configuration")
    require(type(report.get("pull_request")) is int and report["pull_request"] == number,
            "signed report PR number differs from live PR")
    require(type(report.get("issue")) is int and report["issue"] > 0,
            "signed report issue number is malformed")
    return {"comment": comment, "snapshot": snapshot, "raw_report": raw_report,
            "report": report, "author_login": login}, report, raw_report


def validate_signed_report(repo: str, identity: dict[str, Any], config: TrustedConfig,
                           selected: dict[str, Any], raw_report: bytes) -> str:
    """Delegate schema/signature/exact-binding checks to the canonical validators."""
    verifier = ROOT / "scripts" / "verify_web_external_audit.py"
    require(verifier.is_file() and not verifier.is_symlink(), "canonical web report verifier is unavailable")
    with tempfile.TemporaryDirectory(prefix="solo-audit-report-") as temporary:
        directory = Path(temporary)
        report_path, registry_path = directory / "report.json", directory / "registry.json"
        report_path.write_bytes(raw_report)
        registry_path.write_bytes(config.registry_raw)
        comment = selected["comment"]
        user = comment["user"]
        command = [
            sys.executable, str(verifier),
            "--report", str(report_path), "--trusted-auditors", str(registry_path),
            "--repository", repo, "--issue", str(identity["issue"]),
            "--base-ref", identity["base_ref"], "--base-sha", identity["base_sha"],
            "--head-sha", identity["head_sha"], "--merge-preview-sha", identity["merge_preview_sha"],
            "--require-solo", "--pull-request", str(identity["pull_request"]),
            "--issue-body-sha256", identity["issue_body_sha256"],
            "--solo-operator-id", str(config.operator_id), "--solo-key-id", config.key_id,
            "--comment-author-id", str(user["id"]),
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60)
        require(result.returncode == 0, "canonical signed report validation failed")
        return sha256(raw_report)
