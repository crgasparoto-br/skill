"""Fixed, read-only workspace inspection in the existing rootless sandbox.

No arbitrary command, image, network, environment or writable repository mount.
Workspace must be a trusted, separately staged read-only snapshot that is
traversable by UID 65532; private 0700 workspaces are rejected, not chmodded.
"""
from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path

from offline_executor import IMAGE, ROOTLESS_SOCKET
from rootless_reconciler import cleanup_container
from sandbox_profile import OFFLINE_CHECK_V1

_SHA = re.compile(r"^[0-9a-f]{40}$")
_FIXED_CHECKS = {
    "integrity-v1": "echo SNAPSHOT_OK",
    # Only scripts explicitly declaring /bin/sh are compatible with Alpine ash.
    # Bash scripts are NOT treated as verified by this profile.
    "posix-shell-syntax-v1": "find /workspace -type f -name '*.sh' -exec sh -c 'for f do IFS= read -r first < \"$f\" || :; case \"$first\" in \"#!/bin/sh\"| \"#!/usr/bin/env sh\") sh -n \"$f\" || exit 1 ;; esac; done' sh {} + && echo SNAPSHOT_OK",
}


def inspect_workspace_in_container(snapshot_dir: str, expected_sha: str, *, check: str = "integrity-v1") -> bool:
    """Check a trusted read-only snapshot marker in rootless Docker."""
    OFFLINE_CHECK_V1.validate()
    if check not in _FIXED_CHECKS:
        raise ValueError("unsupported fixed snapshot check")
    if os.geteuid() != 1004:
        raise PermissionError("worker identity required")
    if not isinstance(expected_sha, str) or not _SHA.fullmatch(expected_sha):
        raise ValueError("invalid pinned SHA")
    path = Path(snapshot_dir)
    if path.is_symlink() or not path.is_absolute():
        raise PermissionError("invalid snapshot path")
    resolved = path.resolve(strict=True)
    if (not resolved.is_dir() or resolved.stat().st_uid != 1004
            or resolved.stat().st_mode & 0o022
            or not resolved.stat().st_mode & 0o005):
        raise PermissionError("snapshot not safely readable")
    if not Path(ROOTLESS_SOCKET).is_socket():
        raise RuntimeError("rootless socket unavailable")
    name = "solverit-issue88-" + uuid.uuid4().hex
    env = {"PATH": "/usr/bin:/bin", "HOME": "/home/solverit-worker",
           "DOCKER_HOST": "unix://" + ROOTLESS_SOCKET}
    cmd = [
        "/usr/bin/docker", "run", "--rm", "--pull=never", "--name", name,
        "--network", "none", "--memory", "512m", "--memory-swap", "512m",
        "--cpus", "1", "--pids-limit", "64", "--user", "65532:65532",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        "--mount", f"type=bind,src={resolved},dst=/workspace,readonly",
        IMAGE, "sh", "-ec",
        ('test "$(id -u)" = 65532 && test "$(cat /workspace/.solverit-expected-sha)" = "$1" && cd /workspace && sha256sum -c .solverit-sha256 >/dev/null && ' + _FIXED_CHECKS[check]),
        "sh", expected_sha,
    ]
    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True,
                                timeout=60, check=False)
    except subprocess.TimeoutExpired:
        cleanup_container(name, env)
        raise RuntimeError("snapshot inspection timed out")
    if result.returncode != 0 or result.stdout.strip() != "SNAPSHOT_OK":
        raise RuntimeError("snapshot inspection failed")
    return True
