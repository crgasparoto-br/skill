#!/usr/bin/env python3
"""Literal preparation-postcondition execution and independently recomputed proof."""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

from certificate_replay_inputs import (
    HEX_DIGEST,
    preparation_inputs,
    prepared_inventory,
    source_item,
)
from certificate_replay_io import (
    MAX_LOG_BYTES,
    digest,
    fresh_layout,
    json_bytes,
    open_directory,
    read_object,
    run_gate,
    safe_read,
)
from certificate_replay_source import (
    GATE_PATH,
    HEX_SHA,
    parse_command,
    postcondition_items,
    recognize_postconditions,
    trusted_gate,
    verify_postcondition_plan,
)

__all__ = [
    "execute_replay",
    "parse_command",
    "postcondition_items",
    "recognize_postconditions",
    "replay_view",
    "verify_postcondition_plan",
    "verify_replay",
    "verify_replay_receipt",
]
CERTIFICATE = ".audit/entregar-issue/handoff-ready.json"
KIND = "certificate-postcondition-literal-replay"


def replay_view(preparation: dict, preparation_sha256: str) -> dict[str, bytes]:
    subject = preparation["subject"]
    identity = {**preparation["identity"], **{key: subject[key] for key in ("repository", "issue_number", "pull_request_number")}}
    marker = {"phase": "preparation", "release_authority": False, "preparation_sha256": preparation_sha256}
    return {
        "handoff-preflight.json": json_bytes({**marker, "identity": identity}),
        "handoff-certification-status.json": json_bytes({**marker, "status": "certificate-generated",
            "material_head_sha": identity["material_head_sha"], "terminal_ready": False, "certificate_published": False}),
        CERTIFICATE: json_bytes({**marker, "schema_version": 2, "status": "ready",
            "identity": preparation["identity"], "subject": subject,
            "certificate_commit_policy": {"mode": "result-only-child", "allowed_paths": []},
            "prepared_artifacts": preparation["prepared_artifacts"]}),
    }


def write_result(output_dir: Path, report: dict, raw: bytes) -> None:
    parent = open_directory(output_dir.parent)
    try:
        os.mkdir(output_dir.name, mode=0o700, dir_fd=parent)
        directory = os.open(output_dir.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            for name, data in (("raw.log", raw), ("receipt.json", json_bytes(report))):
                descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=directory)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                if safe_read(output_dir / name) != data:
                    raise ValueError("replay output changed during publication")
        finally:
            os.close(directory)
    finally:
        os.close(parent)


def receipt_location(preparation: Path, receipt: Path) -> None:
    if (receipt.name != "receipt.json" or receipt.parent.parent.absolute() != (preparation.parent / "replay").absolute()
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", receipt.parent.name) or ".." in receipt.absolute().parts):
        raise ValueError("replay receipt must occupy its dedicated postcondition replay directory")


def execute_replay(repo: Path, preparation: Path, event: Path, original_command: str, trusted_anchor: str, *,
                   output_dir: Path, source_kind: str, source_id: str, expected_base: str,
                   hosted_prefixes: bool = False) -> dict:
    argv = parse_command(original_command)
    value, prepared_raw, event_raw, bound = preparation_inputs(preparation, event, expected_base)
    if argv[7] != bound["base_ref"]:
        raise ValueError("literal command base ref differs from the authenticated preparation")
    audit = source_item(preparation, value, original_command, trusted_anchor, source_kind, source_id)
    recognize_postconditions(audit, repo, bound["material_head_sha"], expected_base=expected_base)
    source, code = trusted_gate(repo, trusted_anchor, bound["material_head_sha"], expected_base)
    output_dir = output_dir.absolute()
    receipt_location(preparation, output_dir / "receipt.json")
    if (output_dir.exists() or output_dir.is_symlink() or not output_dir.parent.is_dir()
            or any(path.is_symlink() for path in (output_dir.parent, *output_dir.parents))):
        raise ValueError("replay output directory must be new with safe existing parents")
    view = replay_view(value, digest(prepared_raw))
    files = {Path(argv[1]): code, Path(argv[5]): event_raw, **{Path(argv[3]) / name: raw for name, raw in view.items()}}
    runtime_sha = digest(safe_read(Path(sys.executable).resolve()))
    with fresh_layout(files, Path(argv[3]), Path(argv[0]), hosted_prefixes) as layout:
        code_result, raw_log = run_gate(argv)
        if any(safe_read(path) != raw for path, raw in files.items()):
            raise ValueError("literal replay inputs changed during execution")
        created = [str(path) for path, _, _ in layout.created]
        data_root = str(layout.data_root)
    if safe_read(preparation) != prepared_raw or safe_read(event) != event_raw:
        raise ValueError("preparation or event changed during replay")
    prepared_inventory(preparation, value)
    if digest(safe_read(Path(sys.executable).resolve())) != runtime_sha:
        raise ValueError("trusted Python changed during replay")
    report = {"schema_version": 1, "kind": KIND, "source_kind": source_kind, "source_id": source_id,
              "command": original_command, "argv": argv, "identity": bound, "trusted_source": source,
              "preparation_sha256": digest(prepared_raw), "event_sha256": digest(event_raw),
              "input_sha256": {name: digest(raw) for name, raw in view.items()}, "equivalence": "exact-command-replay",
              "execution": {"exit_code": code_result, "raw_log_path": "raw.log", "raw_log_sha256": digest(raw_log)},
              "layout": {"mode": "fresh-paths", "data_root": data_root, "created_paths": created, "cleanup": "completed"},
              "runtime": {"python_version": sys.version.split()[0], "executable_sha256": runtime_sha}}
    write_result(output_dir, report, raw_log)
    return report


def receipt_layout(layout: dict, argv: list[str]) -> None:
    data_root = os.path.commonpath([str(Path(argv[index]).parent) for index in (1, 5)] + [argv[3]])
    required = {argv[1], argv[5], *(str(Path(argv[3]) / name) for name in ("handoff-preflight.json", "handoff-certification-status.json", CERTIFICATE))}
    created = layout.get("created_paths")
    if (set(layout) != {"mode", "data_root", "created_paths", "cleanup"} or layout.get("mode") != "fresh-paths"
            or layout.get("cleanup") != "completed" or layout.get("data_root") != data_root
            or not isinstance(created, list) or not 1 <= len(created) <= 1024
            or not all(isinstance(name, str) and Path(name).is_absolute() and str(Path(name)) == name and ".." not in Path(name).parts for name in created)
            or len(set(created)) != len(created) or not required.issubset(created)):
        raise ValueError("literal replay fresh layout is inconsistent")


def receipt_execution(report: dict, argv: list[str], expected_anchor: str) -> dict:
    source, execution, layout, runtime = (report.get(key) for key in ("trusted_source", "execution", "layout", "runtime"))
    if not all(isinstance(item, dict) for item in (source, execution, layout, runtime)):
        raise ValueError("replay execution metadata must be objects")
    if (set(source) != {"anchor", "path", "git_blob", "sha256"}
            or source.get("anchor") != expected_anchor or source.get("path") != GATE_PATH
            or not HEX_SHA.fullmatch(str(source.get("git_blob"))) or not HEX_DIGEST.fullmatch(str(source.get("sha256")))
            or set(execution) != {"exit_code", "raw_log_path", "raw_log_sha256"}
            or type(execution.get("exit_code")) is not int or execution["exit_code"] != 0
            or execution.get("raw_log_path") != "raw.log" or not HEX_DIGEST.fullmatch(str(execution.get("raw_log_sha256")))):
        raise ValueError("literal replay is not a completed successful authenticated execution")
    receipt_layout(layout, argv)
    if (set(runtime) != {"python_version", "executable_sha256"}
            or not re.fullmatch(r"\d+\.\d+\.\d+[0-9a-z.+-]*", str(runtime.get("python_version")))
            or not HEX_DIGEST.fullmatch(str(runtime.get("executable_sha256")))):
        raise ValueError("literal replay lacks its trusted runtime identity")
    return execution


def verify_replay_receipt(preparation: Path, event: Path, receipt: Path, *, expected_command: str,
                          expected_anchor: str, expected_material: str, expected_base: str,
                          expected_source_kind: str, expected_source_id: str) -> dict:
    value, prepared_raw, event_raw, bound = preparation_inputs(preparation, event, expected_base)
    receipt_location(preparation, receipt)
    source_item(preparation, value, expected_command, expected_anchor, expected_source_kind, expected_source_id)
    report, receipt_raw = read_object(receipt)
    expected = {"schema_version": 1, "kind": KIND, "source_kind": expected_source_kind, "source_id": expected_source_id,
                "command": expected_command, "argv": parse_command(expected_command), "identity": bound,
                "preparation_sha256": digest(prepared_raw), "event_sha256": digest(event_raw),
                "input_sha256": {name: digest(raw) for name, raw in replay_view(value, digest(prepared_raw)).items()},
                "equivalence": "exact-command-replay"}
    if (bound["material_head_sha"] != expected_material or expected["argv"][7] != bound["base_ref"]
            or set(report) != set(expected) | {"trusted_source", "execution", "layout", "runtime"}
            or any(report.get(key) != item for key, item in expected.items())):
        raise ValueError("replay receipt differs from its authenticated inputs or postcondition")
    execution = receipt_execution(report, expected["argv"], expected_anchor)
    log = safe_read(receipt.parent / "raw.log", MAX_LOG_BYTES)
    if not log or digest(log) != execution.get("raw_log_sha256"):
        raise ValueError("literal replay raw log digest differs")
    if safe_read(receipt) != receipt_raw:
        raise ValueError("literal replay receipt changed during validation")
    return {**report, "receipt_sha256": digest(receipt_raw)}


def verify_replay(repo: Path, preparation: Path, event: Path, receipt: Path, **expected) -> dict:
    report = verify_replay_receipt(preparation, event, receipt, **expected)
    source, raw_code = trusted_gate(repo, expected["expected_anchor"], expected["expected_material"], expected["expected_base"])
    if source != report["trusted_source"]:
        raise ValueError("replay source differs from the independently resolved trusted Git blob")
    value, prepared_raw = read_object(preparation)
    event_raw = safe_read(event)
    if digest(prepared_raw) != report["preparation_sha256"] or digest(event_raw) != report["event_sha256"]:
        raise ValueError("replay inputs changed after receipt authentication")
    audit = source_item(preparation, value, expected["expected_command"], expected["expected_anchor"],
                        expected["expected_source_kind"], expected["expected_source_id"])
    recognize_postconditions(audit, repo, expected["expected_material"], expected_base=expected["expected_base"])
    with tempfile.TemporaryDirectory(prefix="semantic-certificate-replay-") as folder:
        root = Path(folder)
        script, current_event, evidence = root / "gate.py", root / "event.json", root / "evidence"
        files = {script: raw_code, current_event: event_raw,
                 **{evidence / name: raw for name, raw in replay_view(value, digest(prepared_raw)).items()}}
        for path, raw in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        argv = [sys.executable, str(script), "--evidence-dir", str(evidence), "--event", str(current_event),
                "--base-ref", report["identity"]["base_ref"]]
        code_result, raw_log = run_gate(argv)
        if any(safe_read(path) != raw for path, raw in files.items()):
            raise ValueError("semantic replay inputs changed during execution")
    if code_result != 0 or digest(raw_log) != report["execution"]["raw_log_sha256"]:
        raise ValueError("independent semantic reexecution does not confirm the literal replay")
    if verify_replay_receipt(preparation, event, receipt, **expected) != report:
        raise ValueError("replay proof changed during independent reexecution")
    return report
