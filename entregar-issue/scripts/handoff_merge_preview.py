"""Bind GitHub's event-authenticated test merge to an exact PR identity."""
from __future__ import annotations

import json
import re
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")


def require_event_merge_preview(event_path: Path, repository: str, number: int,
                                head: str, base: str) -> str:
    """Do not certify a PR with a missing, stale or unbound merge preview."""
    event = json.loads(event_path.read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    if (not isinstance(pr, dict) or (event.get("repository") or {}).get("full_name") != repository
            or pr.get("number") != number or (pr.get("head") or {}).get("sha") != head
            or (pr.get("base") or {}).get("sha") != base):
        raise ValueError("authenticated PR event identity differs from expected material/base")
    preview = pr.get("merge_commit_sha")
    if not isinstance(preview, str) or SHA.fullmatch(preview) is None:
        raise ValueError("authenticated PR event lacks a valid merge preview SHA")
    return preview
