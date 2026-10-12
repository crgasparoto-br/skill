"""Protected-store read path for read-only GitHub evidence verification.

This does not mint tokens, accept MCP parameters or finalize delivery. The
caller must run as a trusted verifier with access to a protected SQLite store
and a read-only token from the separate GitHub App broker.
"""
from __future__ import annotations

from pathlib import Path

from github_evidence_reader import fetch_and_validate_github
from jobs import JobStore
from pr_binding import PRBindingStore


def verify_bound_job(*, database_path: str, job_id: str, actor: str,
                     token: str, required_checks: frozenset[str]) -> str:
    if not Path(database_path).is_file():
        raise FileNotFoundError("protected job database missing")
    job = JobStore(database_path).read(job_id, actor)
    if job.status != "prepared":
        raise PermissionError("only prepared jobs can be verified")
    binding = PRBindingStore(database_path).read(job_id=job_id, actor=actor)
    return fetch_and_validate_github(
        job=job, pr_number=binding.pr_number, binding=binding,
        token=token, required_checks=required_checks,
    )
