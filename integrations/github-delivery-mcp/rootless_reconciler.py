"""Best-effort cleanup for an exact, controller-generated rootless container ID.

This module does NOT authorize runs; caller must already pass identity checks.
Never accepts a caller-supplied name or arbitrary Docker flags.
"""
import subprocess

DOCKER = "/usr/bin/docker"

def cleanup_container(container_name, env):
    if not container_name.startswith("solverit-issue88-"):
        raise ValueError("invalid managed container name")
    import re
    if not re.fullmatch(r"solverit-issue88-[0-9a-f]{32}", container_name):
        raise ValueError("invalid managed container identifier")
    arguments = [DOCKER, "rm", "-f", "--", container_name]
    result = subprocess.run(arguments, env=env, text=True,
                            capture_output=True, timeout=20, check=False)
    # An absent container is already cleaned; verify using inspect rather than
    # treating a failed remove as proof of success.
    inspection = subprocess.run(
        [DOCKER, "container", "inspect", "--", container_name],
        env=env, text=True, capture_output=True, timeout=20, check=False,
    )
    if inspection.returncode == 0:
        raise RuntimeError("managed container survived cleanup")
    if result.returncode != 0 and "No such container" not in (result.stderr or ""):
        raise RuntimeError("container cleanup was not verified: remove failed")
