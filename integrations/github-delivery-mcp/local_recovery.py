"""Conservative restart recovery for local Issue 88 offline jobs.

Run with the dedicated solverit-worker identity while no other controller
instance is dispatching work. Recovery does not replay jobs or GitHub writes.
If Docker enumeration, cleanup or inspection fails, do not change SQLite.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from jobs import JobStore
from rootless_reconciler import cleanup_container

SOCKET = "/run/user/1004/docker.sock"
NAME_PATTERN = re.compile(r"^solverit-issue88-[0-9a-f]{32}$")


def recover_local_jobs(database_path: str) -> int:
    if os.geteuid() != 1004:
        raise PermissionError("dedicated worker identity required")
    if not Path(SOCKET).exists():
        raise RuntimeError("rootless socket unavailable")
    env = {"PATH": "/usr/bin:/bin",
           "DOCKER_HOST": "unix://" + SOCKET,
           "HOME": "/home/solverit-worker"}
    # Enumerate names, including stopped containers. Fail closed on Docker errors.
    listing = subprocess.run(
        ["/usr/bin/docker", "ps", "-a", "--format", "{{.Names}}"],
        env=env, capture_output=True, text=True, check=True, timeout=20,
    )
    names = listing.stdout.splitlines()
    managed = [name for name in names if NAME_PATTERN.fullmatch(name)]
    # A partial cleanup failure halts state recovery; retry remains possible.
    for name in managed:
        cleanup_container(name, env)
    # Double-check that no managed container survives, including containers
    # newly listed since the first query. No concurrent dispatch is allowed.
    verify = subprocess.run(
        ["/usr/bin/docker", "ps", "-a", "--format", "{{.Names}}"],
        env=env, capture_output=True, text=True, check=True, timeout=20,
    )
    if any(NAME_PATTERN.fullmatch(name) for name in verify.stdout.splitlines()):
        raise RuntimeError("managed containers remain; database not reconciled")
    return JobStore(database_path).recover_interrupted()
