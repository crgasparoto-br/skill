"""Prepare local Git commits from a bounded set of authorized worker edits.

Credential-free, never pushes, merges, deletes branches or runs project commands.
The caller must be a trusted worker invoked after OAuth authorization; no MCP
entrypoint. The existing controller lock guards all local Git and SQLite steps.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import workspace_file_edit as editor
from controller_lock import controller_lock
from jobs import JobStore
from policy import DeliveryPolicy
from workspace_file_edit import _assert_owned_dir, _read_head

_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
MAX_CHANGED_FILES = 20


@dataclass(frozen=True)
class CommitResult:
    job_id: str
    head_sha: str
    base_sha: str
    branch: str
    paths: tuple[str, ...]
    replayed: bool


def _git(workspace: Path, *args: str) -> bytes:
    env = {
        "PATH": "/usr/bin:/bin", "HOME": "/home/solverit-worker",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    try:
        return subprocess.run(
            ["/usr/bin/git", "-c", "core.hooksPath=/dev/null",
             "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false",
             "-C", str(workspace), *args],
            env=env, check=True, timeout=30, capture_output=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise PermissionError("trusted local Git operation failed") from exc


def _git_text(workspace: Path, *args: str) -> str:
    return _git(workspace, *args).decode("ascii", "strict").strip()


def _names(workspace: Path, *args: str) -> set[str]:
    raw = _git(workspace, *args)
    if not raw or raw[-1:] != b"\0":
        if raw:
            raise PermissionError("invalid Git file-set framing")
        return set()
    try:
        names = [part.decode("utf-8", "strict") for part in raw[:-1].split(b"\0")]
    except UnicodeDecodeError as exc:
        raise PermissionError("non-UTF8 Git path") from exc
    if len(names) != len(set(names)):
        raise PermissionError("ambiguous Git file set")
    return set(names)


def _verify_files(workspace: Path, expected: dict[str, str]) -> None:
    for relative, digest in expected.items():
        _read_head(workspace, branch=_git_text(
            workspace, "symbolic-ref", "--short", "HEAD"), tracked_path=relative)
        target = workspace
        for part in relative.split("/")[:-1]:
            target = target / part
            _assert_owned_dir(target)
        target = target / relative.split("/")[-1]
        try:
            file = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as exc:
            raise PermissionError("committed file unavailable") from exc
        try:
            info = os.fstat(file)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != editor.WORKER_UID
                    or info.st_nlink != 1 or info.st_mode & 0o022):
                raise PermissionError("untrusted committed file")
            with os.fdopen(file, "rb", closefd=False) as stream:
                blob = stream.read(editor.MAX_CONTENT_BYTES + 1)
        finally:
            os.close(file)
        if len(blob) > editor.MAX_CONTENT_BYTES:
            raise PermissionError("committed file too large")
        if hashlib.sha256(blob).hexdigest() != digest:
            raise PermissionError("candidate file digest changed")


def _verify_git_blobs(workspace: Path, expected: dict[str, str], revision: str) -> None:
    """Git's stage filters may change bytes: validate the real Git object."""
    for relative, digest in expected.items():
        raw = _git(workspace, "show", f"{revision}:{relative}")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise PermissionError("staged or committed blob differs from approval")


def commit_prepared_workspace(
    *, database_path: str, lock_path: str, workspace_root: str, job_id: str,
    actor: str, expected_head: str, approved_files: dict[str, str],
) -> CommitResult:
    """Commit only exact tracked edits; reconcile crash after Git before SQLite."""
    if os.geteuid() != editor.WORKER_UID:
        raise PermissionError("dedicated worker identity required")
    if (not isinstance(expected_head, str) or not _SHA.fullmatch(expected_head)
            or not isinstance(approved_files, dict)
            or not 1 <= len(approved_files) <= MAX_CHANGED_FILES):
        raise ValueError("invalid commit intent")
    for relative, digest in approved_files.items():
        DeliveryPolicy.validate_path(relative)
        if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
            raise ValueError("invalid approved file hash")
    if not Path(database_path).is_file():
        raise FileNotFoundError("job store unavailable")
    root = Path(workspace_root)
    if not root.is_absolute():
        raise PermissionError("workspace root must be absolute")
    _assert_owned_dir(root, require_private=True)
    with controller_lock(lock_path):
        store = JobStore(database_path)
        job = store.read(job_id, actor)
        DeliveryPolicy.validate_branch(job.branch)
        if job.status != "prepared":
            raise PermissionError("job not prepared for local commit")
        identity = uuid.UUID(job.job_id)
        if identity.version != 4 or str(identity) != job.job_id:
            raise PermissionError("invalid job identity")
        workspace = root / ("solverit-issue88-" + identity.hex)
        _assert_owned_dir(workspace, require_private=True)
        _assert_owned_dir(workspace / ".git")
        head = _read_head(workspace, branch=job.branch)
        allowed = set(approved_files)
        if head != expected_head:
            # A previous invocation may have committed before the SQLite CAS.
            parent = _git_text(workspace, "rev-parse", "HEAD^")
            changed = _names(workspace, "diff-tree", "--no-commit-id",
                             "--name-only", "-r", "-z", "HEAD")
            if (parent != expected_head or changed != allowed
                    or job.expected_head not in (expected_head, head)):
                raise PermissionError("stale or unrelated local commit")
            _verify_files(workspace, approved_files)
            if (_names(workspace, "diff", "--name-only", "-z")
                    or _names(workspace, "diff", "--cached", "--name-only", "-z")
                    or _names(workspace, "ls-files", "--others", "--exclude-standard", "-z")):
                raise PermissionError("recovered checkout is not clean")
            _verify_git_blobs(workspace, approved_files, "HEAD")
            store.record_local_head(job_id=job_id, actor=actor,
                                    expected_head=expected_head, new_head=head)
            return CommitResult(job_id, head, expected_head, job.branch,
                                tuple(sorted(allowed)), True)
        if job.expected_head != expected_head:
            raise PermissionError("persisted job HEAD has changed")
        staged = _names(workspace, "diff", "--cached", "--name-only", "-z")
        unstaged = _names(workspace, "diff", "--name-only", "-z")
        untracked = _names(workspace, "ls-files", "--others", "--exclude-standard", "-z")
        if untracked or staged | unstaged != allowed:
            raise PermissionError("workspace has nonauthorized changes")
        _verify_files(workspace, approved_files)
        _git(workspace, "add", "--", *sorted(allowed))
        if _names(workspace, "diff", "--cached", "--name-only", "-z") != allowed:
            raise PermissionError("staged file set changed")
        _verify_git_blobs(workspace, approved_files, "")
        if _read_head(workspace, branch=job.branch) != expected_head:
            raise PermissionError("local HEAD changed before commit")
        _git(workspace, "-c", "user.name=SolverIT Issue Delivery",
             "-c", "user.email=delivery@example.invalid",
             "commit", "-m", f"feat(issue #{job.issue_number}): controlled local changes")
        new_head = _read_head(workspace, branch=job.branch)
        if (new_head == expected_head
                or _git_text(workspace, "rev-parse", "HEAD^") != expected_head
                or _names(workspace, "diff-tree", "--no-commit-id",
                          "--name-only", "-r", "-z", "HEAD") != allowed):
            raise PermissionError("local commit provenance invalid")
        _verify_git_blobs(workspace, approved_files, "HEAD")
        store.record_local_head(job_id=job_id, actor=actor,
                                expected_head=expected_head, new_head=new_head)
        return CommitResult(job_id, new_head, expected_head, job.branch,
                            tuple(sorted(allowed)), False)
