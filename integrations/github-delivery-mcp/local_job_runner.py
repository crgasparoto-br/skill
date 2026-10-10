"""Local-only proof of integration: SQLite job state + approved offline smoke check.

NOT an MCP endpoint. No GitHub credentials or arbitrary command execution.
The operator chooses the database path; production must put the store in a
protected, dedicated location and authorize requests before using this module.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from jobs import JobStore
from offline_executor import run_allowed_check


@dataclass(frozen=True)
class LocalJobOutcome:
    job_id: str
    status: str
    exit_code: int | None
    output: str


def submit_offline_smoke(database_path: str, *, actor: str,
                         idempotency_key: str) -> LocalJobOutcome:
    if actor != "local-smoke-operator":
        raise PermissionError("only local smoke operator is allowed")
    if not idempotency_key or len(idempotency_key) > 128:
        raise ValueError("invalid idempotency key")
    store = JobStore(database_path)
    payload = {"check": "smoke-v1", "repo": "crgasparoto-br/training-system"}
    payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    job = store.create(
        actor=actor, key=idempotency_key, payload_hash=payload_hash,
        repo=payload["repo"], issue_number=88, branch="develop",
        base_sha="offline-smoke-no-repo-operation",
        expected_head="offline-smoke-no-repo-operation",
    )
    # Never replay a previously created job. A retry returns its state.
    if job.status != "queued":
        return LocalJobOutcome(job.job_id, job.status, None, "existing job; not replayed")
    # This standalone demo is single-controller only. Production requires
    # durable leases, crash-safe reconciliation, and guarded job ownership.
    try:
        job = store.transition(job.job_id, actor, "queued", "running")
    except Exception:
        raise
    try:
        result = run_allowed_check("smoke-v1")
        status = "timed_out" if result.timed_out else ("succeeded" if result.exit_code == 0 else "failed")
        output = result.stdout[:4096] if status == "succeeded" else result.stderr[:4096]
        exit_code = result.exit_code
    except Exception as exc:
        status = "failed"
        output = "execution or cleanup failed: " + type(exc).__name__
        exit_code = None
    store.transition(job.job_id, actor, "running", status)
    return LocalJobOutcome(job.job_id, status, exit_code, output)
