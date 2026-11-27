#!/usr/bin/env python3
"""Run material tests without sharing the hosted Actions control plane."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import stat
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

DOCKER = "/usr/bin/docker"
# Docker Official Python 3.12.16-bookworm, immutable linux/amd64 manifest.
IMAGE = "docker.io/library/python@sha256:3c3ba8ad4c85eb63b7568f806434f14e33370056985da7fdf2673621cb1d7e93"
# Fixed test families; candidate content cannot choose the invocation or broaden the lane.
TEST_TARGETS = (
    "tests/test_main_native_session_route.py", "tests/test_session_review_runner.py",
    "tests/test_verify_independent_pr_audit.py", "tests/test_native_audit_workflows.py",
    "tests/test_session_review_workflows.py", "tests/test_versioning.py",
    "entregar-issue/tests/test_validate_native_actions_evidence.py",
    "tests/test_main_evidence_isolation.py", "tests/test_session_review_parity_dispatch.py",
    "auditar-issue/tests/test_controller_audit_result.py",
    "tests/test_catalog_governance.py::test_catalog_is_valid_and_matches_skill_metadata",
    "tests/test_catalog_governance.py::test_documentation_references_are_current",
    "tests/test_catalog_governance.py::test_shared_files_are_byte_identical_to_canonical",
    "tests/test_catalog_governance.py::test_shared_file_drift_is_detected",
    "tests/test_context_budget.py::test_shipped_context_budget_is_valid",
    "tests/test_context_budget.py::test_shipped_allowance_blocks_growth",
    # Discover only these fixed names at this directory level.
    # Keep the existing native target explicit.
    "-o", "'python_files=test_validate_native_actions_evidence.py test_issue_acceptance_criteria_reconciliation.py test_publish_actions_handoff.py'",
    "-o", "'norecursedirs=*'", "entregar-issue/tests",
)
TEST_COMMAND = ("python -m pytest -vv --basetemp=/work/pytest --junitxml=/result/pytest-exact-head.xml "
                + " ".join(TEST_TARGETS))
MAX_BYTES = 8 * 1024 * 1024
MAX_CONTAINER_FILE_BYTES = 64 * 1024 * 1024  # larger pinned wheel executables; host export stays 8 MiB
MAX_SECONDS = 14 * 60
MAX_RESULT_BYTES = 12 * 1024 * 1024
MAX_RESULT_INODES = 32
XML = "pytest-exact-head.xml"
LOG = "pytest-exact-head.log"
PROBE = """from pathlib import Path
import os
assert os.geteuid() == 65534
assert not any(k.startswith(("GITHUB_", "ACTIONS_", "RUNNER_")) for k in os.environ)
assert not Path("/var/run/docker.sock").exists()
assert set(p.name for p in Path("/sys/class/net").iterdir()) == {"lo"}
assert not any(os.access(p, os.W_OK) for p in ("/source", "/wheelhouse", "/locks"))
"""
CONTAINER_COMMAND = """
set -eu
python -c "$CONTAINMENT_PROBE"
mkdir -p /work/repo /work/home
cp -R /source/. /work/repo/
cd /work/repo
test "$(git rev-parse HEAD)" = "$MATERIAL_SHA"
python -m venv /work/venv
. /work/venv/bin/activate
python -m pip --isolated install --no-index --find-links /wheelhouse \
  --require-hashes --only-binary=:all: -r /locks/requirements.lock.txt \
  -r /locks/entregar-issue/requirements-dev.lock.txt -r /locks/auditar-issue/requirements-dev.lock.txt
""" + 'exec ' + TEST_COMMAND


def docker_args(material: Path, locks: Path, wheels: Path, result: Path, head: str) -> list[str]:
    args = [DOCKER, "create", "--pull", "never", "--platform", "linux/amd64", "--network", "none",
            "--read-only", "--user", "65534:65534", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "160", "--memory", "3g", "--cpus", "2",
            "--ulimit", f"fsize={MAX_CONTAINER_FILE_BYTES}:{MAX_CONTAINER_FILE_BYTES}", "--init",
            "--tmpfs", "/work:rw,exec,nosuid,nodev,size=1600m,mode=1777",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777",
            "--env", "HOME=/work/home", "--env", f"MATERIAL_SHA={head}",
            "--env", "CONTAINMENT_PROBE=" + PROBE]
    for path, target, read_only in ((material, "/source", True), (locks, "/locks", True),
                                    (wheels, "/wheelhouse", True), (result, "/result", False)):
        spec = f"type=bind,src={path.resolve()},dst={target}" + (",readonly" if read_only else "")
        args += ["--mount", spec]
    return [*args, IMAGE, "/bin/sh", "-c", CONTAINER_COMMAND]


def docker(*args: str) -> str:
    return subprocess.check_output([DOCKER, *args], text=True, stderr=subprocess.DEVNULL, timeout=120).strip()


def capture(container: str, log: Path) -> int:
    deadline = time.monotonic() + MAX_SECONDS
    with log.open("xb") as out, subprocess.Popen([DOCKER, "start", "-a", container],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process, selectors.DefaultSelector() as stream:
        try:
            stream.register(process.stdout, selectors.EVENT_READ)
            total = 0
            while time.monotonic() < deadline and stream.select(max(0, deadline - time.monotonic())):
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    return process.wait(timeout=max(0.1, deadline - time.monotonic()))
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("isolated test log exceeds the evidence limit")
                out.write(chunk)
            raise ValueError("isolated test execution timed out")
        finally:
            if process.poll() is None:
                process.kill()


def export_xml(source: Path, destination: Path) -> None:
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or not 0 < info.st_size <= MAX_BYTES:
            raise ValueError("isolated XML result must be a bounded ordinary file")
        with destination.open("xb") as out:
            shutil.copyfileobj(stream, out)


def verify_result_mount(path: Path) -> None:
    output = subprocess.check_output(
        ["/usr/bin/findmnt", "--noheadings", "--mountpoint", str(path), "--output", "FSTYPE,OPTIONS"],
        encoding="utf-8", stderr=subprocess.DEVNULL, timeout=15).strip()
    kind, options = output.split(maxsplit=1)
    bound = os.statvfs(path)
    if (kind != "tmpfs" or not {"rw", "nosuid", "nodev", "noexec"} <= set(options.split(","))
            or not 0 < bound.f_frsize * bound.f_blocks <= MAX_RESULT_BYTES
            or not 0 < bound.f_files <= MAX_RESULT_INODES):
        raise ValueError("writable result mount is not aggregate-bounded")


@contextmanager
def result_mount(path: Path):
    command = ["/usr/bin/sudo", "-n", "/usr/bin/mount", "-t", "tmpfs", "-o",
               f"size={MAX_RESULT_BYTES},nr_inodes={MAX_RESULT_INODES},mode=1777,nosuid,nodev,noexec",
               "tmpfs", str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=25)
    try:
        verify_result_mount(path)
        yield
    finally:
        subprocess.run(["/usr/bin/sudo", "-n", "/usr/bin/umount", str(path)],
                       check=True, capture_output=True, timeout=25)


def collect_isolated(material: Path, locks: Path, wheels: Path,
                     result: Path, evidence: Path, head: str) -> None:
    container = subprocess.check_output(docker_args(material, locks, wheels, result, head),
                                        text=True, stderr=subprocess.DEVNULL, timeout=30).strip()
    if not re.fullmatch("[0-9a-f]{64}", container):
        raise ValueError("isolated test container identity is invalid")
    try:
        cli_code = capture(container, evidence / LOG)
        state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
        if (cli_code != 0 or state.get("Status") != "exited" or state.get("OOMKilled") is not False
                or type(state.get("ExitCode")) is not int or state["ExitCode"] != 0):
            raise ValueError("isolated material tests did not exit successfully")
    finally:
        docker("rm", "-f", container)
    export_xml(result / XML, evidence / XML)


def run(material: Path, locks: Path, wheels: Path, evidence: Path, head: str) -> None:
    if not re.fullmatch("[0-9a-f]{40}", head):
        raise ValueError("invalid exact test subject")
    with tempfile.TemporaryDirectory(prefix="solverit-main-results-") as directory:
        result = Path(directory) / "result"
        result.mkdir()
        with result_mount(result):
            collect_isolated(material, locks, wheels, result, evidence, head)
    with (evidence / "main-test-containment.json").open("x", encoding="utf-8") as out:
        json.dump(receipt(evidence, head), out, sort_keys=True)


def receipt(evidence: Path, head: str) -> dict:
    return {"schema_version": 1, "material_head_sha": head, "image": IMAGE, "lane": list(TEST_TARGETS),
            "isolation": "no-network-readonly-mounts-no-runner-control-files",
            "result_bounds": {"bytes": MAX_RESULT_BYTES, "inodes": MAX_RESULT_INODES},
            "exit_code": 0, "log_sha256": hashlib.sha256((evidence / LOG).read_bytes()).hexdigest(),
            "junit_sha256": hashlib.sha256((evidence / XML).read_bytes()).hexdigest()}


def require_receipt(evidence: Path, head: str) -> None:
    check = evidence / "main-test-containment.json"
    if any(path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES
           for path in (check, evidence / LOG, evidence / XML)):
        raise ValueError("host-owned main containment evidence is missing or not a bounded regular file")
    expected = json.dumps(receipt(evidence, head), sort_keys=True)
    if check.read_text(encoding="utf-8") != expected:
        raise ValueError("main containment receipt differs from host policy or recorded outputs")


def main() -> int:
    parser = argparse.ArgumentParser()
    for arg in ("material", "locks", "wheelhouse"):
        parser.add_argument("--" + arg, type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify:
            require_receipt(args.evidence, args.head)
        elif args.material is None or args.locks is None or args.wheelhouse is None:
            raise ValueError("missing isolated staging input")
        else:
            run(args.material, args.locks, args.wheelhouse, args.evidence, args.head)
    except (OSError, ValueError, subprocess.SubprocessError):
        print("BLOCK: isolated exact-main test execution or output validation failed")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
