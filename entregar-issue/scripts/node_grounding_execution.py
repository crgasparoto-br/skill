#!/usr/bin/env python3
"""Cross-check two native Node reporters captured by one trusted invocation.

Caller obligations (not inferred here): authenticated source bytes, pinned
runner, execution exit code, artifact/run identity, and material SHA.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

MAX_REPORT_BYTES = 16 * 1024 * 1024
NODE_LINE_KEYS = {"schema_version", "runner", "file", "entry_file", "classname", "name", "status"}


def _absolute_path(value: object) -> PurePosixPath:
    if (not isinstance(value, str) or not value.startswith("/") or value.startswith("//")
            or "\\" in value or any(ord(char) < 32 for char in value)):
        raise ValueError("Node report source is not a canonical runner path")
    path = PurePosixPath(value)
    if path.as_posix() != value or ".." in path.parts:
        raise ValueError("Node report source is not a canonical runner path")
    return path


def _case_key(workspace: PurePosixPath, file: object, suite: object,
              name: object) -> tuple[str, str, str]:
    source = _absolute_path(file)
    if not source.is_relative_to(workspace) or source == workspace:
        raise ValueError("Node test source is outside the checked-out repository")
    for value in (suite, name):
        if not isinstance(value, str) or not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("Node test case misses a valid class or name")
    return source.relative_to(workspace).as_posix(), suite, name


def _put_case(cases: dict, key: tuple[str, str, str], status: str) -> None:
    if key in cases:
        raise ValueError("Node reporters do not uniquely identify a repeated test within one file")
    cases[key] = status


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict:
    data = {}
    for key, value in pairs:
        if key in data:
            raise ValueError("Node execution record repeats a field")
        data[key] = value
    return data


def _logged_cases(workspace: PurePosixPath, raw: bytes) -> dict:
    cases = {}
    for line in raw.decode("utf-8").removesuffix("\n").split("\n"):
        item = json.loads(line, object_pairs_hook=_unique_json_object)
        if (not isinstance(item, dict) or set(item) != NODE_LINE_KEYS
                or type(item["schema_version"]) is not int or item["schema_version"] != 1
                or item["runner"] != "node:test" or item["status"] not in ("passed", "failure", "skipped")
                or item["file"] != item["entry_file"]):
            raise ValueError("Node execution record is malformed or not from the executed file")
        key = _case_key(workspace, item["file"], item["classname"], item["name"])
        _put_case(cases, key, item["status"])
    return cases


def _junit_cases(workspace: PurePosixPath, raw: bytes) -> dict:
    if b"\0" in raw or re.search(rb"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.IGNORECASE):
        raise ValueError("Node JUnit must be plain UTF-8 XML")
    try:
        root = ET.fromstring(raw.decode("utf-8"))
    except ET.ParseError as error:
        raise ValueError("Node JUnit is not valid XML") from error
    if root.tag != "testsuites":
        raise ValueError("Node JUnit must have a testsuites root")
    cases = {}
    for item in root.iter("testcase"):
        outcomes = [node.tag for node in item if node.tag in ("failure", "error", "skipped")]
        if len(outcomes) > 1:
            raise ValueError("Node JUnit has contradictory testcase outcomes")
        key = _case_key(workspace, item.get("file"), item.get("classname"), item.get("name"))
        status = "failure" if outcomes == ["error"] else outcomes[0] if outcomes else "passed"
        _put_case(cases, key, status)
    return cases


def verify_node_reporters(workspace_root: str, junit_xml: bytes, execution_jsonl: bytes) -> dict:
    """Return filesystem-relative case/status mapping only on full report agreement."""
    workspace = _absolute_path(workspace_root)
    if workspace == PurePosixPath("/"):
        raise ValueError("Node report needs an explicit checkout root")
    if not all(0 < len(raw) <= MAX_REPORT_BYTES for raw in (junit_xml, execution_jsonl)):
        raise ValueError("Missing or oversized Node report")
    junit = _junit_cases(workspace, junit_xml)
    if not junit or junit != _logged_cases(workspace, execution_jsonl):
        raise ValueError("Node native JUnit and execution log inventories differ")
    return dict(sorted(junit.items()))


def require_node_pass(cases: dict, *, source_file: str, classname: str, name: str) -> None:
    """Validate an exact source/class/name tuple from a reconciled inventory."""
    if cases.get((source_file, classname, name)) != "passed":
        raise ValueError("Node reports do not prove a passing execution for the selected case")
