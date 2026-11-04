#!/usr/bin/env python3
"""Protected-source identity and immutable dependency inventory for the solo gate."""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
WORKFLOW_PATH = ".github/workflows/solo-audit-attestation.yml"
DEFAULT_BRANCH = "main"
ALLOWED_BRANCHES = frozenset({"develop", "main"})

TRUSTED_PATHS = (
    WORKFLOW_PATH,
    "scripts/solo_audit_contract.py",
    "scripts/solo_audit_source.py",
    "scripts/solo_audit_github.py",
    "scripts/solo_audit_events.py",
    "scripts/solo_audit_check_runs.py",
    "scripts/verify_solo_audit_attestation.py",
    "scripts/verify_web_external_audit.py",
    "scripts/verify_independent_pr_audit.py",
    "scripts/verify_session_review.py",
    "scripts/session_review.py",
    "entregar-issue/scripts/handoff_merge_preview.py",
    "entregar-issue/scripts/verify_github_completion.py",
    "entregar-issue/scripts/validate_finding_completion.py",
    "auditar-issue/scripts/audit_signature.py",
    "auditar-issue/scripts/validate_external_audit_report.py",
    "auditar-issue/requirements.lock.txt",
    "auditar-issue/schemas/external-audit.schema.json",
    "auditar-issue/schemas/trusted-auditors.schema.json",
)


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _session_runner():
    # Import after the trusted script path has been selected by the launcher.
    import verify_session_review as runner
    return runner


def default_branch_head(repo: str) -> str:
    runner = _session_runner()
    metadata = runner.api(f"/repos/{repo}")
    require(isinstance(metadata, dict) and metadata.get("default_branch") == DEFAULT_BRANCH,
            "repository default branch is not the trusted main branch")
    ref = runner.api(f"/repos/{repo}/git/ref/heads/{DEFAULT_BRANCH}")
    object_info = ref.get("object") if isinstance(ref, dict) else None
    head = object_info.get("sha") if isinstance(object_info, dict) else None
    require(isinstance(head, str) and SHA_RE.fullmatch(head), "trusted default-branch SHA is unavailable")
    return head


def verify_execution_source(repo: str, base_sha: str, workflow_sha: str) -> dict[str, Any]:
    """Bind the checked-out controller/dependencies to github.workflow_sha and protected base."""
    runner = _session_runner()
    require(REPOSITORY_RE.fullmatch(repo) is not None, "invalid trusted repository")
    require(SHA_RE.fullmatch(base_sha) is not None and SHA_RE.fullmatch(workflow_sha) is not None,
            "trusted workflow/base SHA is malformed")
    require(os.environ.get("GITHUB_WORKFLOW_SHA") == workflow_sha,
            "workflow SHA differs from GitHub's trusted execution context")
    require(os.environ.get("GITHUB_REF_PROTECTED") == "true",
            "GitHub does not report the workflow ref as protected")
    local_head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=False, timeout=15,
    )
    require(local_head.returncode == 0 and local_head.stdout.decode("ascii", "strict").strip() == workflow_sha,
            "checkout does not match github.workflow_sha")
    workflow_ref = os.environ.get("GITHUB_WORKFLOW_REF", "")
    expected_ref = re.compile(
        rf"{re.escape(repo)}/{re.escape(WORKFLOW_PATH)}@refs/heads/(?:develop|main)\Z"
    )
    require(expected_ref.fullmatch(workflow_ref) is not None, "workflow source is not a protected branch ref")

    trusted_files: list[dict[str, str]] = []
    local_files: list[dict[str, str]] = []
    for relative in TRUSTED_PATHS:
        local = ROOT / relative
        require(local.is_file() and not local.is_symlink(), "trusted workflow dependency is not a regular file")
        local_bytes = local.read_bytes()
        trusted_bytes, blob_sha = runner.content(repo, relative, base_sha)
        require(trusted_bytes == local_bytes, "workflow dependency differs from protected PR base")
        trusted_files.append({"path": relative, "blob_sha": blob_sha, "sha256": sha256(local_bytes)})
        local_files.append({"path": relative, "sha256": sha256(local_bytes)})
    return {
        "workflow_sha": workflow_sha,
        "base_sha": base_sha,
        "default_branch_sha": default_branch_head(repo),
        "trusted_files_sha256": sha256(runner.canonical(trusted_files)),
        "local_files_sha256": sha256(runner.canonical(local_files)),
    }


def revalidate_execution_source(repo: str, base_sha: str, state: dict[str, Any]) -> None:
    runner = _session_runner()
    require(state.get("base_sha") == base_sha, "trusted base identity changed")
    require(default_branch_head(repo) == state.get("default_branch_sha"),
            "trusted default branch changed during verification")
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=False, timeout=15,
    )
    require(result.returncode == 0 and result.stdout.decode("ascii", "strict").strip() == state.get("workflow_sha"),
            "trusted workflow checkout changed during verification")
    current: list[dict[str, str]] = []
    for relative in TRUSTED_PATHS:
        local = ROOT / relative
        require(local.is_file() and not local.is_symlink(), "trusted workflow dependency disappeared")
        current.append({"path": relative, "sha256": sha256(local.read_bytes())})
    require(sha256(runner.canonical(current)) == state.get("local_files_sha256"),
            "trusted workflow dependencies changed during verification")
