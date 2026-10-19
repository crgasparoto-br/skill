"""Controlled, atomic tracked-file replacement in a prepared Issue 88 worker job.

Trusted worker primitive, NOT an MCP endpoint. The authenticated controller
must authorize the request and serialize all worker mutations using the same
persistent lock. No network, credentials, shell commands, creation or deletion.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from controller_lock import controller_lock
from jobs import JobStore
from policy import DeliveryPolicy

WORKER_UID = 1004
MAX_CONTENT_BYTES = 262_144
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EditResult:
    job_id: str
    path: str
    old_sha256: str
    new_sha256: str
    changed: bool


def _assert_owned_dir(directory: Path, *, require_private: bool = False) -> None:
    metadata = os.lstat(directory)
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != WORKER_UID
            or metadata.st_mode & 0o022
            or (require_private and metadata.st_mode & 0o077)):
        raise PermissionError("untrusted workspace directory")


def _read_head(workspace: Path, *, branch: str, tracked_path: str | None = None) -> str:
    env = {
        "PATH": "/usr/bin:/bin", "HOME": "/home/solverit-worker",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file",
        "GIT_OPTIONAL_LOCKS": "0",
    }

    def git(*arguments: str) -> str:
        result = subprocess.run(
            ["/usr/bin/git", "-c", "core.hooksPath=/dev/null",
             "-c", "core.fsmonitor=false", "-C", str(workspace), *arguments],
            env=env, capture_output=True, text=True, timeout=15, check=True,
        )
        return result.stdout.strip()

    try:
        actual_branch = git("symbolic-ref", "--short", "HEAD")
        actual_sha = git("rev-parse", "--verify", "HEAD^{commit}")
        if actual_branch != branch:
            raise PermissionError("workspace is not on the authorized branch")
        if tracked_path is not None:
            git("ls-files", "--error-unmatch", "--", tracked_path)
        return actual_sha
    except (OSError, subprocess.SubprocessError) as exc:
        raise PermissionError("workspace Git identity unavailable") from exc


def apply_prepared_file_edit(
    *, database_path: str, lock_path: str, workspace_root: str,
    job_id: str, actor: str, relative_path: str, expected_head: str,
    expected_sha256: str, content: bytes,
) -> EditResult:
    """Replace one existing tracked regular file; no intermediate partial file.

    The same job/actor/branch/base SHA must still be valid under controller_lock.
    Repeated identical replacement is a no-op; a stale different edit is denied.
    """
    if os.geteuid() != WORKER_UID:
        raise PermissionError("dedicated worker identity required")
    DeliveryPolicy.validate_path(relative_path)
    if (not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256)
            or not isinstance(content, bytes) or len(content) > MAX_CONTENT_BYTES):
        raise ValueError("invalid content or optimistic concurrency token")
    if not Path(database_path).is_file():
        raise FileNotFoundError("job store unavailable")
    if not Path(workspace_root).is_absolute():
        raise PermissionError("workspace root must be absolute")
    root = Path(workspace_root)
    _assert_owned_dir(root, require_private=True)
    with controller_lock(lock_path):
        job = JobStore(database_path).read(job_id, actor)
        if job.status != "prepared" or expected_head != job.base_sha:
            raise PermissionError("job not prepared at expected base HEAD")
        DeliveryPolicy.validate_branch(job.branch)
        try:
            identifier = uuid.UUID(job.job_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise PermissionError("invalid persisted job identity") from exc
        if identifier.version != 4 or str(identifier) != job.job_id:
            raise PermissionError("invalid persisted job identity")
        workspace = root / ("solverit-issue88-" + identifier.hex)
        _assert_owned_dir(workspace, require_private=True)
        git_directory = workspace / ".git"
        _assert_owned_dir(git_directory)
        if _read_head(workspace, branch=job.branch, tracked_path=relative_path) != job.base_sha:
            raise PermissionError("stale or changed workspace HEAD")
        parts = relative_path.split("/")
        parent = workspace
        for part in parts[:-1]:
            parent = parent / part
            _assert_owned_dir(parent)
        target = parent / parts[-1]
        try:
            fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as exc:
            raise PermissionError("tracked file unavailable") from exc
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != WORKER_UID
                    or metadata.st_nlink != 1 or metadata.st_mode & 0o022):
                raise PermissionError("unsafe tracked file identity")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                previous = handle.read(MAX_CONTENT_BYTES + 1)
        finally:
            os.close(fd)
        if len(previous) > MAX_CONTENT_BYTES:
            raise ValueError("tracked file exceeds edit policy")
        old_digest = hashlib.sha256(previous).hexdigest()
        new_digest = hashlib.sha256(content).hexdigest()
        if not hmac.compare_digest(old_digest, expected_sha256):
            if hmac.compare_digest(old_digest, new_digest):
                return EditResult(job.job_id, relative_path, old_digest, new_digest, False)
            raise PermissionError("file changed since authorized inspection")
        if old_digest == new_digest:
            return EditResult(job.job_id, relative_path, old_digest, new_digest, False)
        # Re-check inode and job branch immediately before atomic publication.
        fresh = os.lstat(target)
        if fresh.st_ino != metadata.st_ino or fresh.st_dev != metadata.st_dev:
            raise PermissionError("tracked file identity changed")
        if _read_head(workspace, branch=job.branch) != expected_head:
            raise PermissionError("workspace HEAD changed during edit")
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=".issue88-replacement-", dir=parent)
        try:
            with os.fdopen(tmp_fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
                os.fsync(stream.fileno())
            os.replace(tmp_name, target)
            dir_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        finally:
            if os.path.lexists(tmp_name):
                os.unlink(tmp_name)
        return EditResult(job.job_id, relative_path, old_digest, new_digest, True)
