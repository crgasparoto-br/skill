"""Fail-closed validation boundary for eventual delivery finalization.

This is deliberately a *read-only gate*, not a success transition. GitHub CI,
publication and independent audit MUST be fetched through a trusted verifier,
never supplied by an MCP caller or worker. Until such a verifier exists the gate
always rejects; no bool or self-asserted payload may authorize completion.
"""
from __future__ import annotations

from jobs import JobStore


class DeliveryNotVerifiedError(PermissionError):
    pass


def require_verified_delivery(database_path: str, *, job_id: str, actor: str) -> None:
    """Read a persisted job, then deny until trusted external verification exists."""
    job = JobStore(database_path).read(job_id, actor)
    if job.status not in ("prepared", "running"):
        raise DeliveryNotVerifiedError("job not ready for delivery verification")
    if job.repo == "" or job.issue_number <= 0:
        raise DeliveryNotVerifiedError("invalid delivery identity")
    # Intentionally no trusted GitHub/auditor verification adapter yet.
    raise DeliveryNotVerifiedError(
        "trusted PR publication, exact-HEAD CI and independent audit not verified"
    )
