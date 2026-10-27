"""Real frozen-gate execution; the minimal preparation here is not a certificate."""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import certificate_postcondition_replay as replay
import certificate_replay_io as replay_io
import pytest
from audit_artifact_io import artifact_metadata
from certificate_replay_io import digest, json_bytes

grounding_fixture = importlib.import_module("entregar-issue.tests.test_codebase_grounding")
audit_fixture = importlib.import_module("entregar-issue.tests.test_audit_remediation_gate_replay")
# Frozen trusted gate bytes; executed only after committing them to the synthetic Git base.
LEGACY_BYTES = rb'''#!/usr/bin/env python3
"""Independently enforce that a collected Actions artifact is *certified*.

A successful technical collection is never interpreted as certified handoff.
The privileged publisher performs a separate trusted revalidation before writing.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")


def load(directory: Path, name: str) -> dict:
    path = directory / name
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise ValueError(f"missing or unsafe certified artifact: {name}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"certified artifact must be a JSON object: {name}")
    return result


def verify(evidence: Path, event_path: Path, base_ref: str) -> None:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    head = (pr.get("head") or {}).get("sha")
    if (not SHA.fullmatch(str(head)) or (pr.get("base") or {}).get("ref") != base_ref
            or (pr.get("head") or {}).get("repo", {}).get("full_name")
            != (event.get("repository") or {}).get("full_name")):
        raise ValueError("event does not identify a same-repository exact-SHA PR")
    identity = load(evidence, "handoff-preflight.json").get("identity") or {}
    if (identity.get("material_head_sha") != head
            or identity.get("pull_request_number") != pr.get("number")
            or identity.get("repository") != event["repository"]["full_name"]):
        raise ValueError("evidence identity is not bound to this PR and SHA")
    status = load(evidence, "handoff-certification-status.json")
    if status.get("material_head_sha") != head:
        raise ValueError("certificate receipt belongs to a different material SHA")
    if status.get("status") != "certificate-generated":
        raise ValueError(f"semantic certification BLOCKED: {status.get('reason', 'unverified')}")
    if status.get("terminal_ready") is not False or status.get("certificate_published") is not False:
        raise ValueError("certificate receipt falsely claims final publication")
    cert = load(evidence, ".audit/entregar-issue/handoff-ready.json")
    subject = cert.get("subject") or {}
    if (cert.get("schema_version") != 2 or cert.get("status") != "ready"
            or (cert.get("identity") or {}).get("material_head_sha") != head
            or subject.get("repository") != identity["repository"]
            or subject.get("issue_number") != identity["issue_number"]
            or subject.get("pull_request_number") != identity["pull_request_number"]
            or subject.get("base_ref") != base_ref):
        raise ValueError("certificate body does not bind the canonical issue and material SHA")
    if (cert.get("certificate_commit_policy") or {}).get("mode") != "result-only-child":
        raise ValueError("certificate does not require result-only publication")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--base-ref", default="develop")
    args = parser.parse_args()
    try:
        verify(args.evidence_dir.resolve(), args.event, args.base_ref)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2
    print("CERTIFICATE VERIFIED: candidate prepared; trusted publication and independent audit still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def make_replay_case(tmp_path: Path) -> dict:
    """Shared real Git/source/event setup; integration tests replace P with the builder's P."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git = grounding_fixture.git
    git(repo, "init", "-q")
    gate = repo / replay.GATE_PATH
    gate.parent.mkdir(parents=True)
    gate.write_bytes(LEGACY_BYTES)
    assert digest(gate.read_bytes()) == "344a4abc59de5d732482c8965af92a00e0ca609fe6fbef1bc4bb4280431ea509"
    (repo / "README.md").write_text("Base documentation.\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "trusted base with frozen historical gate")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("Material candidate documentation.\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "material candidate")
    head = git(repo, "rev-parse", "HEAD")
    literal = tmp_path / "fresh-replay"
    command = " ".join([sys.executable, str(literal / "trusted" / replay.GATE_PATH),
                        "--evidence-dir", str(literal / "evidence"),
                        "--event", str(literal / "event.json"), "--base-ref", "develop"])
    audit = tmp_path / "audit-source-result.json"
    source = audit_fixture.audit(base)
    source.update({"trusted_anchor_sha": base,
                   "identity": {"repository": "owner/repo", "base_sha": base, "head_sha": base}})
    source["findings"][0]["failed_gate"].update({"name": "exact-SHA handoff preparation", "command": command})
    write_json(audit, source)
    preparation = tmp_path / "evidence" / ".audit" / "entregar-issue" / "postcondition" / "preparation.json"
    snapshot = preparation.parent / "prepared" / audit.name
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(audit.read_bytes())
    metadata = {**artifact_metadata(snapshot), "name": "prepared/" + audit.name}
    write_json(preparation, {"schema_version": 2, "status": "prepared", "phase": "preparation",
        "identity": {"material_head_sha": head, "base_sha": base},
        "subject": {"repository": "owner/repo", "issue_number": 127,
                    "pull_request_number": 128, "base_ref": "develop"},
        "prepared_artifacts": {"audit_source_result": metadata},
        "prepared_files": [{"name": metadata["name"], "sha256": metadata["sha256"]}]})
    event = preparation.parent / "replay-event.json"
    write_json(event, {"repository": {"full_name": "owner/repo"}, "pull_request": {
        "number": 128, "head": {"sha": head, "repo": {"full_name": "owner/repo"}},
        "base": {"sha": base, "ref": "develop"}}})
    plan = preparation.parent / "plan.json"
    write_json(plan, replay.recognize_postconditions(audit, repo, head, expected_base=base))
    output = preparation.parent / "replay" / "0"
    output.parent.mkdir()
    return {"repo": repo, "base": base, "head": head, "audit": audit, "plan": plan,
            "preparation": preparation, "event": event, "command": command, "output": output,
            "literal": literal, "source_kind": "finding", "source_id": "F-GATE-001"}


@pytest.fixture
def replay_case(tmp_path):
    return make_replay_case(tmp_path)


def execute(case: dict) -> dict:
    return replay.execute_replay(case["repo"], case["preparation"], case["event"], case["command"], case["base"],
        output_dir=case["output"], source_kind=case["source_kind"], source_id=case["source_id"], expected_base=case["base"])


def expected(case: dict) -> dict:
    return {"expected_command": case["command"], "expected_anchor": case["base"],
            "expected_material": case["head"], "expected_base": case["base"],
            "expected_source_kind": case["source_kind"], "expected_source_id": case["source_id"]}


def replace_source(case: dict, source: dict) -> None:
    """Rebind a deliberate hostile input, so its rejection cannot rely on a stale hash."""
    write_json(case["audit"], source)
    value = json.loads(case["preparation"].read_bytes())
    snapshot = case["preparation"].parent / value["prepared_artifacts"]["audit_source_result"]["name"]
    snapshot.write_bytes(case["audit"].read_bytes())
    metadata = {**artifact_metadata(snapshot), "name": snapshot.relative_to(case["preparation"].parent).as_posix()}
    value["prepared_artifacts"]["audit_source_result"] = metadata
    value["prepared_files"] = [{"name": metadata["name"], "sha256": metadata["sha256"]}]
    write_json(case["preparation"], value)


def replace_command(case: dict, command: str) -> None:
    case["command"] = command
    source = json.loads(case["audit"].read_bytes())
    source["findings"][0]["failed_gate"]["command"] = command
    replace_source(case, source)


def verify(case: dict) -> dict:
    return replay.verify_replay(case["repo"], case["preparation"], case["event"],
                                case["output"] / "receipt.json", **expected(case))


def test_literal_replay_executes_frozen_gate_and_reverifies_real_output(replay_case):
    case = replay_case
    before = {key: case[key].read_bytes() for key in ("audit", "preparation", "event")}
    result = execute(case)
    assert result["execution"]["exit_code"] == 0
    assert not case["literal"].exists()
    raw = (case["output"] / "raw.log").read_bytes()
    assert raw == b"CERTIFICATE VERIFIED: candidate prepared; trusted publication and independent audit still required\n"
    assert result["execution"]["raw_log_sha256"] == digest(raw)
    verified = replay.verify_replay(case["repo"], case["preparation"], case["event"],
                                    case["output"] / "receipt.json", **expected(case))
    assert verified["receipt_sha256"] == digest((case["output"] / "receipt.json").read_bytes())
    assert verified["command"] == case["command"] and verified["argv"] == case["command"].split()
    assert {key: case[key].read_bytes() for key in before} == before


def test_postcondition_plan_recomputes_immutable_source_and_external_base(replay_case):
    case = replay_case
    plan = replay.verify_postcondition_plan(case["plan"], case["audit"], case["head"], case["repo"], expected_base=case["base"])
    assert plan["items"][0]["gate_source_sha256"] == digest(LEGACY_BYTES)
    changed = json.loads(case["plan"].read_bytes())
    changed["items"][0]["source_id"] = "F-SUBSTITUTED"
    write_json(case["plan"], changed)
    with pytest.raises(ValueError, match="plan differs"):
        replay.verify_postcondition_plan(case["plan"], case["audit"], case["head"], case["repo"], expected_base=case["base"])


@pytest.mark.parametrize("boundary", ["repository", "candidate-anchor", "event-base"])
def test_replay_rejects_unauthorized_source_before_execution(replay_case, boundary):
    case = replay_case
    source = json.loads(case["audit"].read_bytes())
    anchor = case["base"]
    if boundary == "repository":
        source["identity"]["repository"] = "another/repository"
        replace_source(case, source)
    elif boundary == "candidate-anchor":
        anchor = case["head"]
        source["trusted_anchor_sha"] = source["identity"]["base_sha"] = anchor
        source["head_sha"] = source["identity"]["head_sha"] = anchor
        source["findings"][0]["failed_gate"]["subject_sha"] = anchor
        replace_source(case, source)
    else:
        event = json.loads(case["event"].read_bytes())
        event["pull_request"]["base"]["sha"] = case["head"]
        write_json(case["event"], event)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        replay.execute_replay(case["repo"], case["preparation"], case["event"], case["command"], anchor,
            output_dir=case["output"], source_kind=case["source_kind"], source_id=case["source_id"], expected_base=case["base"])
    assert not case["literal"].exists() and not case["output"].exists()


@pytest.mark.parametrize("boundary", ["collision", "system-path", "parent-symlink", "interpreter"])
def test_replay_rejects_unsafe_layout_without_overwriting(replay_case, boundary):
    case = replay_case
    original = case["literal"].parent / "original.txt"
    original.write_bytes(b"preserve these original bytes")
    argv = case["command"].split()
    if boundary == "collision":
        case["literal"].mkdir()
        (case["literal"] / "original.txt").write_bytes(original.read_bytes())
    elif boundary == "system-path":
        argv[5] = "/etc/solverit-replay-must-not-be-created.json"
    elif boundary == "parent-symlink":
        target = case["literal"].parent / "actual"
        target.mkdir()
        link = case["literal"].parent / "linked"
        link.symlink_to(target, target_is_directory=True)
        argv = [arg.replace(str(case["literal"]), str(link / "fresh")) for arg in argv]
    else:
        argv[0] = "/bin/sh"
    replace_command(case, " ".join(argv))
    with pytest.raises((ValueError, OSError)):
        execute(case)
    assert original.read_bytes() == b"preserve these original bytes"
    assert not case["output"].exists()
    if boundary == "collision":
        assert (case["literal"] / "original.txt").read_bytes() == original.read_bytes()
    if boundary == "parent-symlink":
        assert list(target.iterdir()) == []


@pytest.mark.parametrize("boundary", ["snapshot-symlink", "snapshot-hash", "unlisted", "missing", "oversize"])
def test_replay_authenticates_bounded_prepared_inventory(replay_case, boundary):
    case = replay_case
    snapshot = case["preparation"].parent / "prepared" / case["audit"].name
    if boundary == "snapshot-symlink":
        snapshot.unlink()
        snapshot.symlink_to(case["audit"])
    elif boundary == "snapshot-hash":
        snapshot.write_bytes(snapshot.read_bytes() + b" ")
    elif boundary == "unlisted":
        (snapshot.parent / "unlisted.json").write_text("{}", encoding="utf-8")
    elif boundary == "missing":
        snapshot.unlink()
    else:
        with snapshot.open("wb") as stream:
            stream.truncate(replay_io.MAX_FILE_BYTES + 1)
    with pytest.raises((ValueError, OSError)):
        execute(case)
    assert not case["literal"].exists() and not case["output"].exists()


@pytest.mark.parametrize(("field", "value"), [
    (("command",), "/usr/bin/true"), (("source_id",), "F-OTHER"),
    (("identity", "material_head_sha"), "0" * 40), (("preparation_sha256",), "0" * 64),
    (("trusted_source", "sha256"), "0" * 64), (("execution", "exit_code"), False),
    (("execution", "raw_log_sha256"), "0" * 64), (("layout", "created_paths"), []),
], ids=["command", "source-id", "material", "preparation", "trusted-blob", "boolean-exit", "log-hash", "layout"])
def test_replay_proof_rejects_substitution(replay_case, field, value):
    case = replay_case
    execute(case)
    path = case["output"] / "receipt.json"
    receipt = json.loads(path.read_bytes())
    target = receipt
    for key in field[:-1]:
        target = target[key]
    target[field[-1]] = value
    path.chmod(0o600)
    write_json(path, receipt)
    with pytest.raises(ValueError):
        verify(case)


def test_semantic_reexecution_rejects_fabricated_success_log(replay_case):
    case = replay_case
    execute(case)
    receipt = case["output"] / "receipt.json"
    log = case["output"] / "raw.log"
    log.chmod(0o600)
    log.write_bytes(b"An invented success log with a consistent digest.\n")
    value = json.loads(receipt.read_bytes())
    value["execution"]["raw_log_sha256"] = digest(log.read_bytes())
    receipt.chmod(0o600)
    write_json(receipt, value)
    replay.verify_replay_receipt(case["preparation"], case["event"], receipt, **expected(case))
    with pytest.raises(ValueError, match="semantic reexecution"):
        verify(case)


def test_failed_literal_gate_records_real_failure_without_promoting_preparation(replay_case, monkeypatch):
    original_view = replay.replay_view
    def blocked_status(*args):
        view = original_view(*args)
        value = json.loads(view["handoff-certification-status.json"])
        value["status"] = "blocked"
        view["handoff-certification-status.json"] = json_bytes(value)
        return view
    monkeypatch.setattr(replay, "replay_view", blocked_status)
    result = execute(replay_case)
    assert result["execution"]["exit_code"] == 2
    assert b"semantic certification BLOCKED" in (replay_case["output"] / "raw.log").read_bytes()
    with pytest.raises(ValueError, match="successful authenticated execution"):
        verify(replay_case)
    assert json.loads(replay_case["preparation"].read_bytes())["status"] == "prepared"


@pytest.mark.parametrize("boundary", ["preparation-change", "unknown-cleanup-file"])
def test_replay_detects_changes_and_preserves_unowned_paths(replay_case, monkeypatch, boundary):
    case = replay_case
    original_run = replay.run_gate
    unknown = case["literal"] / "unowned.txt"
    def changed_inputs(argv):
        result = original_run(argv)
        if boundary == "preparation-change":
            case["preparation"].write_bytes(case["preparation"].read_bytes() + b" ")
        else:
            unknown.write_bytes(b"do not recursively remove this file")
        return result
    monkeypatch.setattr(replay, "run_gate", changed_inputs)
    with pytest.raises(ValueError):
        execute(case)
    assert not case["output"].exists()
    if boundary == "unknown-cleanup-file":
        assert unknown.read_bytes() == b"do not recursively remove this file"


def test_literal_replay_uses_only_trusted_runtime_and_clean_environment(replay_case, monkeypatch):
    case = replay_case
    poison = case["literal"].parent / "poison"
    poison.mkdir()
    marker = poison / "executed"
    (poison / "sitecustomize.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(poison))
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-enter-replay")
    seen = []
    original_popen = replay_io.subprocess.Popen
    def observe(*args, **kwargs):
        seen.append(kwargs.get("env", {}))
        return original_popen(*args, **kwargs)
    monkeypatch.setattr(replay_io.subprocess, "Popen", observe)
    argv = case["command"].split()
    argv[0] = str(case["literal"] / "runtime" / "bin" / "python")
    replace_command(case, " ".join(argv))
    assert execute(case)["execution"]["exit_code"] == 0
    assert verify(case)["argv"][0] == argv[0]
    assert not marker.exists() and not case["literal"].exists()
    assert seen and all("GITHUB_TOKEN" not in env and "PYTHONPATH" not in env for env in seen)


def test_replay_log_is_bounded_during_actual_process_execution():
    with pytest.raises(ValueError, match="log exceeds"):
        replay_io.run_gate([sys.executable, "-c", f"print('x' * {replay_io.MAX_LOG_BYTES + 1})"])


def test_replay_rejects_non_regular_input_without_waiting(tmp_path):
    fifo = tmp_path / "non-regular-input"
    os.mkfifo(fifo)
    code = "import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from certificate_replay_io import safe_read;safe_read(Path(sys.argv[2]))"
    result = subprocess.run([sys.executable, "-c", code, str(Path(__file__).parents[1] / "scripts"), str(fifo)],
                            capture_output=True, text=True, check=False, timeout=2)
    assert result.returncode != 0 and "bounded regular file" in result.stderr


def test_replay_rejects_foreign_venv_before_startup_code(replay_case):
    case = replay_case
    prefix = case["literal"].parent / "foreign-runtime"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(prefix)], check=True, capture_output=True)
    python = prefix / "bin" / "python"
    assert python.resolve() == Path(sys.executable).resolve()
    packages = prefix / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    marker = prefix / "startup-executed"
    (packages / "untrusted.pth").write_text(f"import pathlib; pathlib.Path({str(marker)!r}).touch()\n", encoding="utf-8")
    # Prove the alternate prefix executes its startup code despite the clean environment.
    subprocess.run([str(python), "-c", "pass"], env=replay_io.clean_environment(), check=True, capture_output=True)
    assert marker.exists()
    marker.unlink()
    argv = case["command"].split()
    argv[0] = str(python)
    replace_command(case, " ".join(argv))
    with pytest.raises(ValueError, match="trusted running Python"):
        execute(case)
    assert not marker.exists() and not case["literal"].exists() and not case["output"].exists()
