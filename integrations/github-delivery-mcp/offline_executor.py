"""Restricted offline check adapter (not an exposed MCP tool).

Only fixed, reviewed checks; no caller-supplied commands, images or Docker flags.
Invoke solely from a trusted controller after server-side authorization.
The controller host must be isolated from the untrusted repository code.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from sandbox_profile import OFFLINE_CHECK_V1

ROOTLESS_SOCKET = "/run/user/1004/docker.sock"
IMAGE = "alpine:3.20"
CHECKS = {
    "smoke-v1": ("sh", "-ec", "test \"$(id -u)\" = 65532; test \"$(cat /sys/fs/cgroup/memory.max)\" = 536870912; echo CHECK_OK"),
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
    if os.geteuid() == 0 or os.geteuid() != 1004:
        raise PermissionError("dedicated worker identity required")
    if not os.path.exists(ROOTLESS_SOCKET):
        raise RuntimeError("rootless daemon socket unavailable")
    args = [
        "/usr/bin/docker", "run", "--rm", "--pull=never",
        "--network", "none", "--memory", "512m", "--memory-swap", "512m",
        "--cpus", "1", "--pids-limit", "64", "--user", "65532:65532",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
        IMAGE, *CHECKS[check],
    ]
    env = {"PATH": "/usr/bin:/bin",
           "DOCKER_HOST": "unix://" + ROOTLESS_SOCKET,
           "HOME": "/home/solverit-worker"}
    try:
        completed = subprocess.run(
            args, env=env, capture_output=True, text=True,
            timeout=60, check=False,
        )
        return CheckResult(check, completed.returncode,
                           completed.stdout[:4096], completed.stderr[:4096], False)
    except subprocess.TimeoutExpired:
        # Timeout does not guarantee that a detached/container-side process is gone.
        # The caller must reconcile and enforce runtime cleanup before running jobs.
        return CheckResult(check, 124, "", "execution timed out; reconciliation required", True)
