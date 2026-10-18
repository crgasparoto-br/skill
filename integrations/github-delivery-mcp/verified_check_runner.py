"""Internal trusted-controller adapter from rootless checks to durable evidence.

Never network-facing. The controller must authenticate the actor, own the
exclusive job lock and provide a trusted snapshot bound to the job's Git SHA.
No result, image or check outcome is accepted from an MCP tool caller.
"""
from __future__ import annotations

import os

from check_evidence import _CHECKS, _IMAGES, CheckEvidenceStore
from workspace_container_check import inspect_workspace_in_container


def run_and_record_checks(*, database_path: str, job_id: str, actor: str,
                          snapshot_dir: str):
    if os.geteuid() != 1004:
        raise PermissionError("dedicated worker required")
    store = CheckEvidenceStore(database_path)
    job = store.jobs.read(job_id, actor)
    if job.status != "prepared":
        raise PermissionError("job not prepared")
    if store.list_for_owner(job_id, actor):
        # No silent replay or overwrite of completed or incomplete attempts.
        raise PermissionError("previous evidence requires reconciliation")
    for check in ("integrity-v1", "posix-shell-syntax-v1", "bash-syntax-v1"):
        if check not in _CHECKS:
            raise RuntimeError("unknown mandatory check")
        try:
            passed = inspect_workspace_in_container(snapshot_dir, job.base_sha,
                                                     check=check)
        except Exception:
            # Never turn an execution error, including timeout, into a pass.
            store.record(job_id=job_id, actor=actor, check=check,
                         base_sha=job.base_sha, image=_IMAGES[check],
                         passed=False)
            raise
        if passed is not True:
            store.record(job_id=job_id, actor=actor, check=check,
                         base_sha=job.base_sha, image=_IMAGES[check],
                         passed=False)
            raise RuntimeError("rootless check did not pass")
        store.record(job_id=job_id, actor=actor, check=check,
                     base_sha=job.base_sha, image=_IMAGES[check], passed=True)
    store.require_checks(job_id, actor)
    return store.list_for_owner(job_id, actor)
