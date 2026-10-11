"""Read-only, identity-bound job lookup. Not a public MCP tool.

Never accept actor, profile, or repository permission from tool arguments.
The trusted dispatcher must supply VerifiedPrincipal built from OAuth JWT.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict

from jobs import Job
from policy import DeliveryPolicy, PolicyDeniedError, VerifiedPrincipal


def get_authorized_job_status(
    *, database_path: str, job_id: str, principal: VerifiedPrincipal | None,
    allowed_subjects: frozenset[str],
    allowed_repositories: frozenset[str],
) -> dict[str, object]:
    if (principal is None or not principal.oauth_verified
            or principal.subject not in allowed_subjects
            or "entregar-issue" not in principal.profiles):
        raise PolicyDeniedError("delivery identity not authorized")
    if not isinstance(job_id, str) or len(job_id) != 36:
        raise PolicyDeniedError("invalid job identifier")
    import uuid
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError("noncanonical job identifier")
    except ValueError as exc:
        raise PolicyDeniedError("invalid job identifier") from exc
    # Read-only SQLite URI: no implicit DB creation, schema mutations or
    # recovery side effects from a public status request.
    from pathlib import Path
    import urllib.parse
    path = Path(database_path).resolve(strict=True)
    uri = "file:" + urllib.parse.quote(str(path)) + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=3) as connection:
            connection.row_factory = sqlite3.Row
            record = connection.execute(
                """SELECT job_id, repo, issue_number, branch, base_sha,
                          expected_head, correlation_id, status, created_at,
                          updated_at FROM jobs WHERE job_id=? AND actor=?""",
                (job_id, principal.subject),
            ).fetchone()
    except sqlite3.Error as exc:
        raise RuntimeError("job store unavailable") from exc
    if record is None:
        raise KeyError("job not found")
    if record["repo"] not in allowed_repositories:
        raise PolicyDeniedError("repository not authorized")
    return asdict(Job(**dict(record)))
