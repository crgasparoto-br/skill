"""Single-controller offline workspace dispatch with durable status transitions.

Not network-facing. Caller must hold controller_lock, verify OAuth authorization
before enqueue, and supply a mirror already synchronized by a trusted process.
This module cannot fetch GitHub credentials or execute repository code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from jobs import JobStore
from offline_workspace import prepare_offline_workspace


@dataclass(frozen=True)
class WorkspaceDispatchResult:
    job_id: str
    status: str
    workspace: str | None


def dispatch_queued_workspace(
    *, database_path: str, job_id: str, actor: str, repository: str,
    mirror_path: str, workspace_root: str,
) -> WorkspaceDispatchResult:
    """Dispatch one already authorized job, with no automatic replay."""
    if os.geteuid() != 1004:
        raise PermissionError("dedicated worker identity required")
    if not Path(database_path).is_file():
        raise FileNotFoundError("job store unavailable")
    store = JobStore(database_path)
    job = store.read(job_id, actor)
    if job.repo != repository:
        raise PermissionError("job repository mismatch")
    if job.status != "queued":
        return WorkspaceDispatchResult(job.job_id, job.status, None)
    # The trusted controller serializes this call with controller_lock.
    store.transition(job.job_id, actor, "queued", "running")
    try:
        workspace = prepare_offline_workspace(
            repository=job.repo, expected_sha=job.base_sha,
            mirror_path=mirror_path, workspace_root=workspace_root,
        )
    except Exception:
        # Failed workspace remains available for controller-led reconciliation.
        store.transition(job.job_id, actor, "running", "failed")
        raise
    # Preparing a workspace is not completing issue implementation, CI or audit.
    store.transition(job.job_id, actor, "running", "prepared")
    return WorkspaceDispatchResult(job.job_id, "prepared", workspace)
