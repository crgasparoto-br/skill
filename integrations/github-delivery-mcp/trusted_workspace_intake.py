"""Trusted develop-head verification before persisting a workspace request.

This is an intake stage, not a runnable executor. The trusted server supplies
the branch resolver; it must authenticate to GitHub independently of the caller.
No GitHub credential, token, or resolver is exposed to MCP tool arguments.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from delivery_job_submission import enqueue_prepare_workspace
from policy import PolicyDeniedError, VerifiedPrincipal

if TYPE_CHECKING:
    from collections.abc import Callable

_SHA = re.compile(r"^[0-9a-f]{40}$")


def intake_prepare_workspace(
    *, database_path: str, principal: VerifiedPrincipal | None,
    allowed_subjects: frozenset[str], allowed_repositories: frozenset[str],
    repository: str, issue_number: int, idempotency_key: str,
    trusted_develop_head: Callable[[str], str],
) -> dict[str, object]:
    """Resolve base HEAD from the trusted GitHub client, not from user inputs."""
    if repository not in allowed_repositories:
        raise PolicyDeniedError("repository not authorized")
    if (principal is None or not principal.oauth_verified
            or principal.subject not in allowed_subjects
            or "entregar-issue" not in principal.profiles):
        raise PolicyDeniedError("delivery identity not authorized")
    if not callable(trusted_develop_head):
        raise PolicyDeniedError("trusted develop resolver unavailable")
    sha = trusted_develop_head(repository)
    if not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise PolicyDeniedError("trusted develop HEAD invalid")
    return enqueue_prepare_workspace(
        database_path=database_path, principal=principal,
        allowed_subjects=allowed_subjects,
        allowed_repositories=allowed_repositories, repository=repository,
        issue_number=issue_number, base_sha=sha,
        idempotency_key=idempotency_key,
    )
