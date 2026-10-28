"""Bind test-merge identity to GitHub's authenticated current PR, not stale webhook data."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def _actual_runner_event(event_path: Path) -> bool:
    """Only inspect runner state for the real GitHub event, not synthetic tests."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return False
    source = os.environ.get("GITHUB_EVENT_PATH")
    if not source:
        raise ValueError("GitHub Actions event path unavailable")
    return os.path.realpath(source) == os.path.realpath(event_path)



def _github_api_origin(repository: str) -> str:
    """Trust only a runner-provided HTTPS GitHub API origin bound to its server."""
    # GitHub Actions owns both origins. Allow standard dot-api and Enterprise
    # /api/v3, never an arbitrary URL from the PR or the webhook payload.
    api = os.environ.get("GITHUB_API_URL", "").rstrip("/")
    server = os.environ.get("GITHUB_SERVER_URL", "").rstrip("/")
    api_url = urllib.parse.urlsplit(api)
    server_url = urllib.parse.urlsplit(server)
    standard = (api_url.hostname == f"api.{server_url.hostname}"
                and api_url.path in ("", "/"))
    enterprise = (api_url.hostname == server_url.hostname
                  and api_url.path == "/api/v3")
    if (api_url.scheme != "https" or server_url.scheme != "https"
            or not api_url.hostname or not server_url.hostname
            or api_url.username or api_url.password or api_url.query or api_url.fragment
            or server_url.username or server_url.password or server_url.path not in ("", "/")
            or server_url.query or server_url.fragment
            or not (standard or enterprise) or REPO.fullmatch(repository) is None):
        raise ValueError("unexpected GitHub API origin or repository identity")
    return api


def _current_github_preview(repository: str, number: int, head: str,
                            base: str, base_ref: str) -> str:
    """Require runner merge SHA to equal authenticated current GitHub PR state."""
    runner_sha = os.environ.get("GITHUB_SHA")
    if (not isinstance(runner_sha, str) or SHA.fullmatch(runner_sha) is None
            or os.environ.get("GITHUB_REF") != f"refs/pull/{number}/merge"
            or os.environ.get("GITHUB_EVENT_NAME") != "pull_request"):
        raise ValueError("runner context is not an exact pull-request merge ref")
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("read-only GitHub API credential unavailable at certification")
    api = _github_api_origin(repository)
    request = urllib.request.Request(
        f"{api}/repos/{repository}/pulls/{number}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        current = json.load(response)
    if (not isinstance(current, dict) or current.get("state") != "open"
            or (current.get("head") or {}).get("sha") != head
            or (current.get("base") or {}).get("sha") != base
            or (current.get("base") or {}).get("ref") != base_ref
            or current.get("number") != number):
        raise ValueError("authenticated GitHub PR no longer matches event identity")
    if current.get("merge_commit_sha") != runner_sha:
        raise ValueError("GitHub runner merge SHA differs from current PR merge preview")
    return runner_sha


def require_event_merge_preview(event_path: Path, repository: str, number: int,
                                head: str, base: str) -> str:
    """Reject stale/tampered previews; never treat event field as current in CI."""
    event = json.loads(event_path.read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    if (not isinstance(pr, dict) or (event.get("repository") or {}).get("full_name") != repository
            or pr.get("number") != number or (pr.get("head") or {}).get("sha") != head
            or (pr.get("base") or {}).get("sha") != base):
        raise ValueError("authenticated PR event identity differs from expected material/base")
    if _actual_runner_event(event_path):
        return _current_github_preview(repository, number, head, base, pr["base"]["ref"])
    preview = pr.get("merge_commit_sha")
    if not isinstance(preview, str) or SHA.fullmatch(preview) is None:
        raise ValueError("authenticated PR event lacks a valid merge preview SHA")
    return preview
