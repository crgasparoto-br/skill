"""Prepare a pinned source tree from a trusted local bare mirror.

This stage is run only by a dedicated worker AFTER the controller has fetched
and verified GitHub develop. No network, GitHub token or project command here.
It does not constitute a sandbox for executing repository code.
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path

from policy import DeliveryPolicy

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^(?!\.{1,2}/)[A-Za-z0-9_.-]+/(?!\.{1,2}$)[A-Za-z0-9_.-]+$")


def prepare_offline_workspace(
    *, repository: str, expected_sha: str, mirror_path: str,
    workspace_root: str, job_id: str, branch: str,
) -> str:
    if os.geteuid() != 1004:
        raise PermissionError("dedicated solverit-worker identity required")
    if not _REPO.fullmatch(repository) or not _SHA.fullmatch(expected_sha):
        raise ValueError("invalid repository or pinned SHA")
    DeliveryPolicy.validate_branch(branch)
    try:
        job_identity = uuid.UUID(job_id)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("invalid job identity") from exc
    if str(job_identity) != job_id or job_identity.version != 4:
        raise ValueError("invalid job identity")
    if Path(workspace_root).is_symlink() or Path(mirror_path).is_symlink():
        raise PermissionError("symlink workspace or mirror path forbidden")
    root = Path(workspace_root).resolve(strict=True)
    mirror = Path(mirror_path).resolve(strict=True)
    if not root.is_dir() or root.is_symlink() or root.stat().st_uid != 1004:
        raise PermissionError("untrusted workspace root")
    if root.stat().st_mode & 0o022:
        raise PermissionError("workspace root must not be group/world writable")
    if not mirror.is_dir() or mirror.is_symlink() or mirror.stat().st_uid != 1004:
        raise PermissionError("untrusted mirror")
    if mirror.stat().st_mode & 0o022:
        raise PermissionError("mirror must not be group/world writable")
    # Verify this is a bare mirror rather than accepting an arbitrary directory.
    safe_env = {
        "PATH": "/usr/bin:/bin", "HOME": "/home/solverit-worker",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file",
        "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "protocol.file.allow",
        "GIT_CONFIG_VALUE_0": "always",
    }

    def run(*args, cwd=None):
        return subprocess.run(
            ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args],
            cwd=cwd, env=safe_env, check=True, timeout=60,
            capture_output=True, text=True,
        ).stdout.strip()

    if run("--git-dir", str(mirror), "rev-parse", "--is-bare-repository") != "true":
        raise ValueError("trusted local Git mirror must be bare")
    ref = run("--git-dir", str(mirror), "rev-parse", "--verify", "refs/heads/develop^{commit}")
    if ref != expected_sha:
        raise ValueError("develop SHA changed or mirror not synchronized")
    # The canonical job UUID binds the directory to one persistent job.
    # Re-entry cannot silently reuse an earlier worktree.
    folder = root / ("solverit-issue88-" + job_identity.hex)
    folder.mkdir(mode=0o700)
    try:
        run("clone", "--no-checkout", "--no-hardlinks", "--", str(mirror), str(folder))
        # Explicit pinned SHA, never checkout arbitrary branch supplied by caller.
        run("-C", str(folder), "checkout", "--detach", "--force", expected_sha)
        run("-C", str(folder), "switch", "--no-track", "-c", branch, expected_sha)
        actual = run("-C", str(folder), "rev-parse", "HEAD")
        active_branch = run("-C", str(folder), "symbolic-ref", "--short", "HEAD")
        if actual != expected_sha or active_branch != branch:
            raise RuntimeError("pinned branch checkout mismatch")
        return str(folder)
    except Exception:
        # Preserve failed workspaces for a trusted reconciler; do not delete
        # arbitrary paths or leave an ambiguous successful response.
        raise
