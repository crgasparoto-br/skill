"""Local discriminants for the host evidence boundary (no Docker daemon required)."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_main_evidence_tests.py"
sys.path.insert(0, str(SCRIPT.parent))
runner = importlib.import_module("run_main_evidence_tests")
HEAD = "1" * 40


def test_forced_network_privilege_and_mount_boundary(tmp_path):
    inputs = [tmp_path / name for name in ("material", "locks", "wheelhouse", "result")]
    args = runner.docker_args(*inputs, HEAD)

    def options(flag):
        return [args[i + 1] for i, item in enumerate(args) if item == flag]

    assert options("--network") == ["none"]
    assert options("--user") == ["65534:65534"]
    assert "--read-only" in args and options("--cap-drop") == ["ALL"]
    assert options("--security-opt") == ["no-new-privileges"]
    assert options("--pull") == ["never"]
    assert options("--tmpfs") == ["/work:rw,exec,nosuid,nodev,size=1600m,mode=1777",
                                 "/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777"]
    assert runner.MAX_CONTAINER_FILE_BYTES > runner.MAX_BYTES
    assert len(options("--mount")) == 4
    assert [mount.split("dst=")[1] for mount in options("--mount")] == [
        "/source,readonly", "/locks,readonly", "/wheelhouse,readonly", "/result",
    ]
    assert {x.split("=")[0] for x in options("--env")} == {"HOME", "MATERIAL_SHA", "CONTAINMENT_PROBE"}
    assert runner.IMAGE in args and runner.TEST_COMMAND in args[-1]
    assert "test_semantic_mutation_saturation_gate.py" not in runner.TEST_COMMAND


@pytest.mark.parametrize("kind", ["ordinary", "symlink", "large"])
def test_only_bounded_ordinary_result_crosses_boundary(tmp_path, monkeypatch, kind):
    source, destination = tmp_path / "result.xml", tmp_path / "host.xml"
    monkeypatch.setattr(runner, "MAX_BYTES", 19)
    if kind == "symlink":
        other = tmp_path / "private"
        other.write_bytes(b"internal")
        source.symlink_to(other)
    else:
        source.write_bytes(b"fixture" if kind == "ordinary" else b"X" * 20)
    if kind == "ordinary":
        runner.export_xml(source, destination)
        assert destination.read_bytes() == b"fixture"
    else:
        with pytest.raises((ValueError, OSError)):
            runner.export_xml(source, destination)
        assert not destination.exists()


@pytest.mark.parametrize("change", [None, "log", "lane", "number", "head", "missing"])
def test_host_receipt_validation_through_workflow_cli(tmp_path, change):
    (tmp_path / runner.LOG).write_bytes(b"pytest fixture, not independent evidence")
    (tmp_path / runner.XML).write_bytes(b"<testsuite/>")
    metadata = runner.receipt(tmp_path, HEAD)
    if change == "log":
        (tmp_path / runner.LOG).write_bytes(b"different")
    elif change == "lane":
        metadata["lane"] = ["different"]
    elif change == "number":
        metadata["exit_code"] = 0.0
    elif change == "head":
        metadata["material_head_sha"] = "3" * 40
    if change != "missing":
        (tmp_path / "main-test-containment.json").write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
    command = [sys.executable, "-I", str(SCRIPT), "--head", HEAD, "--evidence", str(tmp_path), "--verify"]
    observed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert observed.returncode == (0 if change is None else 2)


@pytest.mark.parametrize("state", ["exact", "failed", "oom", "launcher"])
def test_host_requires_runner_exit_and_engine_exit_before_packaging(tmp_path, monkeypatch, state):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    container_id = "a" * 64
    calls = []

    def create(args, **_):
        result = next(value for value in args if value.endswith("dst=/result"))
        path = result.split("src=")[1].split(",dst=")[0]
        (Path(path) / runner.XML).write_bytes(b"<testsuite><testcase name='control'/></testsuite>")
        return container_id

    def capture(subject, log):
        assert subject == container_id
        log.write_bytes(b"offline host-exit fixture")
        return 1 if state == "launcher" else 0

    def engine(*args):
        calls.append(args[0])
        assert args[-1] == container_id
        return json.dumps({
            "ExitCode": 1 if state == "failed" else 0, "Status": "exited", "OOMKilled": state == "oom",
        })

    monkeypatch.setattr(runner, "result_mount", lambda _: nullcontext())
    monkeypatch.setattr(runner.subprocess, "check_output", create)
    monkeypatch.setattr(runner, "capture", capture)
    monkeypatch.setattr(runner, "docker", engine)
    if state == "exact":
        runner.run(tmp_path, tmp_path, tmp_path, evidence, HEAD)
        runner.require_receipt(evidence, HEAD)
    else:
        with pytest.raises(ValueError, match="did not exit successfully"):
            runner.run(tmp_path, tmp_path, tmp_path, evidence, HEAD)
        assert not (evidence / "main-test-containment.json").exists()
    assert calls == ["inspect", "rm"]


@pytest.mark.parametrize("state", ["bounded", "large", "wide", "wrong-filesystem", "exec"])
def test_result_mount_probe_checks_aggregate_bounds_and_flags(tmp_path, monkeypatch, state):
    from types import SimpleNamespace

    kind = "ext4" if state == "wrong-filesystem" else "tmpfs"
    flags = "rw,nosuid,nodev" if state == "exec" else "rw,nosuid,nodev,noexec"
    blocks = runner.MAX_RESULT_BYTES // 4096 + (state == "large")
    files = runner.MAX_RESULT_INODES + (state == "wide")
    monkeypatch.setattr(runner.os, "statvfs", lambda _: SimpleNamespace(
        f_frsize=4096, f_blocks=blocks, f_files=files))
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *_args, **_opts: f"{kind} {flags}")
    if state == "bounded":
        runner.verify_result_mount(tmp_path)
    else:
        with pytest.raises(ValueError, match="not aggregate-bounded"):
            runner.verify_result_mount(tmp_path)


def test_result_mount_cleanup_survives_rejected_probe(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", lambda command, **_: calls.append(command))

    def reject(_):
        raise ValueError("bounded result mount required")

    monkeypatch.setattr(runner, "verify_result_mount", reject)
    with pytest.raises(ValueError, match="bounded result"), runner.result_mount(tmp_path):
        pytest.fail("must not run material on an unbounded result filesystem")
    assert calls[0][0:5] == ["/usr/bin/sudo", "-n", "/usr/bin/mount", "-t", "tmpfs"]
    assert calls[1] == ["/usr/bin/sudo", "-n", "/usr/bin/umount", str(tmp_path)]
