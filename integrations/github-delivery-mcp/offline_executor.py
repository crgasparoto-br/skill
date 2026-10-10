"""Restricted offline check adapter; fixed commands only, no untrusted mounts."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import uuid

from rootless_reconciler import cleanup_container
from sandbox_profile import OFFLINE_CHECK_V1
ROOTLESS_SOCKET = "/run/user/1004/docker.sock"
IMAGE = "alpine:3.20"
CHECKS = {
    "smoke-v1": ("sh", "-ec", 'test "$(id -u)" = 65532; test "$(cat /sys/fs/cgroup/memory.max)" = 536870912; echo CHECK_OK'),
}

@dataclass(frozen=True)
class CheckResult:
    check: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool

def run_allowed_check(check: str) -> CheckResult:
    OFFLINE_CHECK_V1.validate()
    if check not in CHECKS:
        raise ValueError("unknown check profile")
    if os.geteuid() != 1004:
        raise PermissionError("dedicated worker identity required")
    if not Path(ROOTLESS_SOCKET).exists():
        raise RuntimeError("rootless daemon socket unavailable")

    container_name = "solverit-issue88-" + uuid.uuid4().hex
    env = {"PATH": "/usr/bin:/bin",
           "DOCKER_HOST": "unix://" + ROOTLESS_SOCKET,
           "HOME": "/home/solverit-worker"}
    args = [
        "/usr/bin/docker", "run", "--rm", "--pull=never",
        "--name", container_name,
        "--network", "none", "--memory", "512m", "--memory-swap", "512m",
        "--cpus", "1", "--pids-limit", "64", "--user", "65532:65532",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        IMAGE, *CHECKS[check],
    ]
    try:
        completed = subprocess.run(
            args, env=env, capture_output=True, text=True,
            timeout=60, check=False,
        )
        return CheckResult(check, completed.returncode,
                           completed.stdout[:4096], completed.stderr[:4096], False)
    except subprocess.TimeoutExpired:
        # Fail closed: no next job until exact managed container is confirmed gone.
        cleanup_container(container_name, env)
        return CheckResult(check, 124, "", "execution timed out; container removed", True)
