"""Trusted controller's OAuth-authorized boundary for preparing a delivery job.

This function is not a public tool: the transport middleware constructs the
verified principal after cryptographic Keycloak validation. The credential
broker *independently* verifies the same original access token and checks the
open GitHub issue plus current develop SHA, without exposing GitHub credentials.
The controller persists only validated intent; no worker or GitHub write occurs.
"""
from __future__ import annotations

from controller_broker_client import inspect_authorized_issue
from delivery_job_submission import enqueue_prepare_workspace
from policy import PolicyDeniedError, VerifiedPrincipal

PILOT_REPOSITORY = "crgasparoto-br/training-system"
ALLOWED_REPOSITORIES = frozenset({PILOT_REPOSITORY})


def enqueue_verified_delivery(
    *, database_path: str, principal: VerifiedPrincipal | None,
    allowed_subjects: frozenset[str], repository: str, issue_number: int,
    idempotency_key: str, mcp_access_token: str,
) -> dict[str, object]:
    """Fail closed before IPC on ineligible identity/repo/issue/request key."""
    if (principal is None or not principal.oauth_verified
            or not isinstance(principal.subject, str)
            or principal.subject not in allowed_subjects
            or "entregar-issue" not in principal.profiles):
        raise PolicyDeniedError("delivery identity not authorized")
    if repository not in ALLOWED_REPOSITORIES:
        raise PolicyDeniedError("delivery repository not authorized")
    if type(issue_number) is not int or not 1 <= issue_number <= 2_147_483_647:
        raise PolicyDeniedError("invalid issue number")
    if (not isinstance(idempotency_key, str)
            or not 1 <= len(idempotency_key) <= 128):
        raise PolicyDeniedError("invalid idempotency key")
    # Both layers separately verify authorization: principal at controller,
    # original signed bearer again at credential broker through SO_PEERCRED IPC.
    sha = inspect_authorized_issue(
        repository=repository, issue_number=issue_number,
        verified_actor=principal.subject, mcp_access_token=mcp_access_token,
    )
    return enqueue_prepare_workspace(
        database_path=database_path, principal=principal,
        allowed_subjects=allowed_subjects, allowed_repositories=ALLOWED_REPOSITORIES,
        repository=repository, issue_number=issue_number, base_sha=sha,
        idempotency_key=idempotency_key,
    )
