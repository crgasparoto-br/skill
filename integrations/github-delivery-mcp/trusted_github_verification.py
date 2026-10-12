"""Protected-store read path for read-only GitHub evidence verification.

This does not mint tokens, accept MCP parameters or finalize delivery. The
caller must run as a trusted verifier with access to a protected SQLite store
and a read-only token from the separate GitHub App broker.
"""
from __future__ import annotations

from pathlib import Path

from github_evidence_reader import fetch_and_validate_github
from app_token_broker import ALLOWED_REPOSITORIES, mint_token
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

def verify_with_github_app(*, database_path: str, job_id: str, actor: str,
                           required_checks: frozenset[str]) -> str:
    """Trusted broker-only entry point; the token never leaves this process.

    Never expose this entry point to the MCP server or sandbox. Server-side
    authorization, protected DB ownership and local UID separation are required
    operational preconditions, not established by this function.
    """
    job = JobStore(database_path).read(job_id, actor)
    if job.repo not in ALLOWED_REPOSITORIES:
        raise PermissionError("repository outside GitHub App installation policy")
    if job.status != "prepared":
        raise PermissionError("job is not prepared")
    # The binding must already be present in protected state; no caller PR id.
    PRBindingStore(database_path).read(job_id=job_id, actor=actor)
    token = mint_token(repository=job.repo, operation="read-checks",
                       server_authorized=True)
    return verify_bound_job(
        database_path=database_path, job_id=job_id, actor=actor,
        token=token, required_checks=required_checks)
