"""Reconcile native Vitest v2 JUnit and JSON output from one run.

This adapter is not a receipt validator. The caller must authenticate the runner,
workspace root, commit, invocation, exit code, and both raw report digests.
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

MAX_REPORT_BYTES = 16 * 1024 * 1024
Case = tuple[str, str]
Inventory = dict[Case, tuple[str, ...]]


class _ReportTree(ET.TreeBuilder):
    def doctype(self, *_args: object) -> None:
        raise ValueError("unexpected document type in Vitest JUnit")


def _unique_keys(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, entry in pairs:
        if key in value:
            raise ValueError("duplicate JSON report key")
        value[key] = entry
    return value


def _invalid_constant(_value: str) -> None:
    raise ValueError("invalid JSON report constant")


def _label(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        raise ValueError("invalid Vitest case label")
    return value


def _path(value: object, *, absolute: bool) -> PurePosixPath:
    text = _label(value)
    path = PurePosixPath(text)
    if (path.as_posix() != text or path.is_absolute() != absolute or
            str(path) in {".", "/", "//"} or ".." in path.parts or "\\" in text):
        raise ValueError("noncanonical Vitest source path")
    return path


def _counts(node: ET.Element, key: str, expected: int) -> None:
    if node.get(key) != str(expected):
        raise ValueError("inconsistent Vitest JUnit totals")


def _xml_cases(raw: bytes) -> dict[str, list[tuple[str, str]]]:
    root = ET.fromstring(raw.decode("utf-8"), parser=ET.XMLParser(target=_ReportTree()))
    if root.tag != "testsuites" or root.get("name") != "vitest tests":
        raise ValueError("unexpected Vitest JUnit format")
    files = {}
    for suite in root:
        if suite.tag != "testsuite":
            raise ValueError("unexpected Vitest JUnit suite")
        path = _path(suite.get("name"), absolute=False).as_posix()
        if path in files:
            raise ValueError("repeated Vitest JUnit suite path")
        cases = []
        for test in suite:
            if (test.tag != "testcase" or test.get("classname") != path
                    or test.get("file", path) != path):
                raise ValueError("Vitest JUnit case source disagrees with suite")
            tags = [child.tag for child in test]
            if (any(tag not in {"system-out", "system-err", "skipped"} for tag in tags)
                    or tags.count("skipped") > 1):
                raise ValueError("unexpected or failed Vitest JUnit case")
            cases.append((_label(test.get("name")), "skipped" if "skipped" in tags else "passed"))
        _counts(suite, "tests", len(cases))
        _counts(suite, "skipped", sum(status == "skipped" for _, status in cases))
        _counts(suite, "errors", 0)
        _counts(suite, "failures", 0)
        files[path] = cases
    _counts(root, "tests", sum(map(len, files.values())))
    _counts(root, "errors", 0)
    _counts(root, "failures", 0)
    return files


def _json_cases(raw: bytes, runner_root: PurePosixPath) -> dict[str, list[tuple[str, str]]]:
    report = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys,
                        parse_constant=_invalid_constant)
    if (not isinstance(report, dict) or report.get("success") is not True
            or not isinstance(report.get("testResults"), list)):
        raise ValueError("unexpected or unsuccessful Vitest JSON report")
    files = {}
    for suite in report["testResults"]:
        if (not isinstance(suite, dict) or suite.get("status") != "passed"
                or not isinstance(suite.get("assertionResults"), list)):
            raise ValueError("unexpected or unsuccessful Vitest JSON suite")
        path = _path(suite.get("name"), absolute=True).relative_to(runner_root).as_posix()
        if path == "." or path in files:
            raise ValueError("repeated or missing Vitest JSON source file")
        cases = []
        for test in suite["assertionResults"]:
            if not isinstance(test, dict) or not isinstance(test.get("ancestorTitles"), list):
                raise ValueError("unexpected Vitest JSON case")
            parts = [_label(parent) for parent in test["ancestorTitles"]] + [_label(test.get("title"))]
            status = test.get("status")
            if status not in ("passed", "skipped", "todo"):
                raise ValueError("unexpected or nonfinal Vitest JSON case")
            cases.append((" > ".join(parts), "skipped" if status == "todo" else status))
        files[path] = cases
    total = sum(map(len, files.values()))
    passed = sum(status == "passed" for cases in files.values() for _, status in cases)
    for key, expected in (("numTotalTests", total), ("numPassedTests", passed), ("numFailedTests", 0)):
        if type(report.get(key)) is not int or report[key] != expected:
            raise ValueError("inconsistent Vitest JSON totals")
    return files


def collect_vitest_observations(*, junit: bytes, runner_json: bytes, runner_root: str) -> Inventory:
    """Return observations by structured (source, testcase) key; preserve duplicates."""
    if any(not 0 < len(data) <= MAX_REPORT_BYTES for data in (junit, runner_json)):
        raise ValueError("invalid Vitest report size")
    root = _path(runner_root, absolute=True)
    xml_cases = _xml_cases(junit)
    json_cases = _json_cases(runner_json, root)
    if xml_cases != json_cases or not any(xml_cases.values()):
        raise ValueError("Vitest native reports disagree or are empty")
    observations: dict[Case, list[str]] = {}
    for path, cases in xml_cases.items():
        for name, status in cases:
            observations.setdefault((path, name), []).append(status)
    return {key: tuple(statuses) for key, statuses in observations.items()}


def require_unique_vitest_pass(inventory: Inventory, path: str, name: str) -> None:
    """Neither a missing, skipped, nor an ambiguously repeated case is evidence."""
    key = _path(path, absolute=False).as_posix(), _label(name)
    if inventory.get(key) != ("passed",):
        raise ValueError("Vitest grounding requires one unambiguous passed case")
