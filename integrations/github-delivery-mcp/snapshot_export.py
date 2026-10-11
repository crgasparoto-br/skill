"""Export a bounded read-only snapshot of tracked Git files at a pinned commit.

This is a staging primitive, not permission to execute repository code.
Only regular tracked blobs are accepted. Symlinks, submodules, special files,
credential-named paths and oversized repositories fail closed.
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path

from policy import DeliveryPolicy

_SHA = re.compile(r"^[0-9a-f]{40}$")
# Deliberately narrow: only configuration files reviewed as safe to export.
_ALLOWED_DOTFILES = frozenset({".gitignore", ".gitattributes", ".editorconfig"})
MAX_FILES = 5000
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024


def export_pinned_snapshot(*, mirror_path: str, root_path: str, expected_sha: str) -> str:
    if os.geteuid() != 1004:
        raise PermissionError("worker identity required")
    if not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha):
        raise ValueError("invalid pinned commit")
    mirror = Path(mirror_path)
    root = Path(root_path)
    if mirror.is_symlink() or root.is_symlink():
        raise PermissionError("symlink root denied")
    mirror = mirror.resolve(strict=True)
    root = root.resolve(strict=True)
    if (not mirror.is_dir() or not root.is_dir()
            or mirror.stat().st_uid != 1004 or root.stat().st_uid != 1004
            or mirror.stat().st_mode & 0o022 or root.stat().st_mode & 0o022):
        raise PermissionError("untrusted snapshot source or root")
    env = {"PATH": "/usr/bin:/bin", "HOME": "/home/solverit-worker",
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_TERMINAL_PROMPT": "0", "GIT_ALLOW_PROTOCOL": "file"}

    def git(*args, input_bytes=None):
        return subprocess.run(
            ["/usr/bin/git", "-c", "core.hooksPath=/dev/null",
             "--git-dir", str(mirror), *args],
            input=input_bytes, capture_output=True, timeout=30,
            check=True, env=env,
        ).stdout

    ref = git("rev-parse", "--verify", "refs/heads/develop^{commit}").decode().strip()
    if ref != expected_sha:
        raise ValueError("mirror develop HEAD mismatch")
    entries = git("ls-tree", "-rz", "--full-tree", expected_sha).split(b"\0")
    if entries and entries[-1] == b"":
        entries.pop()
    if len(entries) > MAX_FILES:
        raise ValueError("too many tracked files")
    vetted = []
    total = 0
    for record in entries:
        metadata, sep, raw_path = record.partition(b"\t")
        fields = metadata.split(b" ")
        if not sep or len(fields) != 3:
            raise ValueError("invalid Git tree entry")
        mode, kind, oid = fields
        if mode not in (b"100644", b"100755") or kind != b"blob":
            raise ValueError("unsafe tracked entry type")
        try:
            name = raw_path.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise ValueError("non-UTF8 path rejected") from exc
        parts = name.split("/")
        if (not name or any(part in ("", ".", "..") for part in parts)
                or any(part.startswith(".") for part in parts[:-1])
                or (parts[-1].startswith(".") and parts[-1] not in _ALLOWED_DOTFILES)
                or any(part.lower() in ("secrets", ".github", ".git", ".ssh") for part in parts)):
            raise ValueError("unsafe tracked path")
        DeliveryPolicy.validate_path(name)
        size_str = git("cat-file", "-s", oid.decode()).decode().strip()
        size = int(size_str)
        if size > MAX_FILE_BYTES:
            raise ValueError("tracked file too large")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise ValueError("snapshot exceeds size limit")
        vetted.append((parts, oid.decode()))
    # Restrict exported contents to plain data and code under trusted paths.
    snapshot = root / ("solverit-issue88-" + uuid.uuid4().hex)
    snapshot.mkdir(mode=0o700)
    try:
        for parts, oid in vetted:
            parent = snapshot.joinpath(*parts[:-1])
            parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            destination = parent / parts[-1]
            data = git("cat-file", "blob", oid)
            if len(data) > MAX_FILE_BYTES:
                raise ValueError("file grew during export")
            with destination.open("xb") as out:
                out.write(data)
            destination.chmod(0o644)
        marker = snapshot / ".solverit-expected-sha"
        marker.write_text(expected_sha + "\n", encoding="ascii")
        marker.chmod(0o644)
        snapshot.chmod(0o755)
        return str(snapshot)
    except Exception:
        # Do not recursively remove a possibly manipulated workspace.
        # Leave it for trusted reconciler cleanup and do not claim success.
        raise
