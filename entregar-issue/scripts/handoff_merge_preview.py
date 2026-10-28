"""Resolve an authenticated, parent-verified GitHub PR test merge for exact-SHA handoff."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
MAX_PREVIEW_READS = 4


def _read_json(path: str) -> dict:
    """Read a GitHub REST resource with the hosted runner's read-only token."""
    token = os.environ.get("GITHUB_TOKEN")
    api_url = os.environ.get("GITHUB_API_URL", "")
    if not token or not api_url.startswith("https://"):
        raise ValueError("authenticated GitHub API context is unavailable")
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/{path}",
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ValueError("authenticated GitHub merge-preview read failed") from exc
    if not isinstance(payload, dict):
        raise ValueError("authenticated GitHub merge-preview response is malformed")
    return payload


def _check_live_identity(pr: dict, repository: str, number: int,
                         head: str, base: str, base_ref: str) -> None:
    """A live PR must still be the exact material candidate in the trusted event."""
    if (not isinstance(pr, dict) or not isinstance(pr.get("base"), dict)
            or not isinstance(pr.get("head"), dict)
            or not isinstance(pr["base"].get("repo"), dict)
            or not isinstance(pr["head"].get("repo"), dict)
            or pr.get("number") != number or pr.get("state") != "open" or pr.get("merged") is True
            or (pr.get("base") or {}).get("ref") != base_ref
            or (pr.get("base") or {}).get("sha") != base
            or (pr.get("base") or {}).get("repo", {}).get("full_name") != repository
            or (pr.get("head") or {}).get("sha") != head
            or (pr.get("head") or {}).get("repo", {}).get("full_name") != repository):
        raise ValueError("live GitHub PR identity differs from authenticated event")


def _event_identity(event_path: Path, repository: str, number: int,
                    head: str, base: str) -> tuple[str | None, str]:
    """Bind the current test merge to the exact PR, never certifying an old event SHA.

    GitHub may deliver an old merge_commit_sha in a synchronize event during
    recomputation. The live PR and the merge commit's ordered parents must agree
    on base and HEAD. Retries are bounded and identity drift always blocks.
    """
    if (REPOSITORY.fullmatch(repository) is None or type(number) is not int
            or number <= 0 or not isinstance(head, str) or SHA.fullmatch(head) is None
            or not isinstance(base, str) or SHA.fullmatch(base) is None):
        raise ValueError("invalid merge-preview target identity")
    event = json.loads(event_path.read_text(encoding="utf-8"))
    if not isinstance(event, dict):
        raise ValueError("authenticated PR event shape is malformed")
    pr = event.get("pull_request") or {}
    if (not isinstance(pr, dict)
            or not isinstance(pr.get("head"), dict) or not isinstance(pr.get("base"), dict)
            or not isinstance(pr["head"].get("repo"), dict)):
        raise ValueError("authenticated PR event shape is malformed")
    event_preview = pr.get("merge_commit_sha")
    base_ref = (pr.get("base") or {}).get("ref")
    if ((event.get("repository") or {}).get("full_name") != repository
            or pr.get("number") != number or (pr.get("head") or {}).get("sha") != head
            or (pr.get("head") or {}).get("repo", {}).get("full_name") != repository
            or (pr.get("base") or {}).get("sha") != base
            or not isinstance(base_ref, str) or not base_ref):
        raise ValueError("authenticated PR event identity differs from expected material/base")
    # GitHub can send an explicit null during pull_request.opened while the
    # live test merge is still being computed. Only the authenticated live
    # resolver may replace that null; missing fields and corrupt SHAs fail.
    if ("merge_commit_sha" not in pr or (event_preview is not None
            and (not isinstance(event_preview, str) or SHA.fullmatch(event_preview) is None))):
        raise ValueError("authenticated PR event lacks a valid merge preview SHA")

    return event_preview, base_ref


def _live_preview(repository: str, number: int, head: str, base: str, base_ref: str) -> str:
    path = f"repos/{repository}/pulls/{number}"
    for attempt in range(MAX_PREVIEW_READS):
        live = _read_json(path)
        _check_live_identity(live, repository, number, head, base, base_ref)
        preview = live.get("merge_commit_sha")
        if isinstance(preview, str) and SHA.fullmatch(preview):
            commit = _read_json(f"repos/{repository}/git/commits/{preview}")
            parents = commit.get("parents")
            if (commit.get("sha") != preview or not isinstance(parents, list)
                    or not all(isinstance(parent, dict) for parent in parents)):
                raise ValueError("live merge-preview commit metadata is malformed")
            if [parent.get("sha") for parent in parents] == [base, head]:
                confirmed = _read_json(path)
                _check_live_identity(confirmed, repository, number, head, base, base_ref)
                if confirmed.get("merge_commit_sha") == preview:
                    return preview
        if attempt + 1 < MAX_PREVIEW_READS:
            time.sleep(2)
    raise ValueError("live GitHub merge preview is stale or not bound to exact base/HEAD")

def require_event_merge_preview(event_path: Path, repository: str, number: int,
                                head: str, base: str) -> str:
    """Use a verified live preview for trusted CI; keep historical replays deterministic."""
    event_preview, base_ref = _event_identity(event_path, repository, number, head, base)
    mode = os.environ.get("SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW")
    if mode is None:
        if event_preview is None:
            raise ValueError("authenticated PR event lacks a valid merge preview SHA")
        return event_preview
    if mode != "1":
        raise ValueError("invalid trusted merge-preview verification mode")
    return _live_preview(repository, number, head, base, base_ref)
