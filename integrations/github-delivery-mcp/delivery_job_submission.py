"""Authorized job enqueue boundary; does NOT clone, execute or publish.

The verified principal is supplied by trusted OAuth middleware, never by
MCP tool parameters. Dispatch remains disabled until the rootless worker and
GitHub installation-token handoff are integrated and independently audited.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict

from jobs import JobStore
from policy import DeliveryPolicy, PolicyDeniedError, VerifiedPrincipal

_SHA = re.compile(r"^[0-9a-f]{40}$")


def enqueue_prepare_workspace(
    *, database_path: str, principal: VerifiedPrincipal | None,
    allowed_subjects: frozenset[str], allowed_repositories: frozenset[str],
    repository: str, issue_number: int, base_sha: str,
    idempotency_key: str,
) -> dict[str, object]:
    """Persist an authorized intent only; no code execution side effects."""
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number <= 0:
        raise PolicyDeniedError("invalid issue number")
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
        raise PolicyDeniedError("invalid idempotency key")
    if not isinstance(base_sha, str) or not _SHA.fullmatch(base_sha):
        raise PolicyDeniedError("verified develop SHA required")
    branch = f"feat/{issue_number}-delivery"
    policy = DeliveryPolicy(allowed_users=allowed_subjects, allowed_repos=allowed_repositories)
    policy.authorize(principal, "prepare_workspace", repository, branch, expected_head=base_sha)
    # Caller must obtain base_sha from GitHub's trusted branch lookup and
    # verify the same SHA in the future worker immediately before cloning.
    payload = {
        "repository": repository, "issue_number": issue_number,
        "branch": branch, "base": "develop", "base_sha": base_sha,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    job = JobStore(database_path).create(
        actor=principal.subject, key=idempotency_key, payload_hash=digest,
        repo=repository, issue_number=issue_number, branch=branch,
        base_sha=base_sha, expected_head=base_sha,
    )
    return asdict(job)
