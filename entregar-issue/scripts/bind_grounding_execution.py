#!/usr/bin/env python3
"""Bind reviewed test decisions to an authenticated exact-SHA pytest execution.

Only execution fields are produced. Scenarios, oracles, dispositions and coverage
remain reviewed inputs; a passing test does not establish semantic equivalence.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

PENDING_REASON = "awaiting-exact-SHA-JUnit"
EXECUTION_PREFIX = ".audit/entregar-issue/execution/"
RESULT_LINE = re.compile(r"^(?P<case>.+\.py::.+) (?P<status>PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)(?:\s+\[\s*\d+%\])?\s*$")


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_path(value: object) -> str:
    if (not isinstance(value, str) or not value or "\\" in value
            or any(ord(char) < 32 for char in value)):
        raise ValueError("invalid reviewed test or execution path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("noncanonical reviewed test or execution path")
    return value


def execution_path(root: Path, relative: str) -> Path:
    """Resolve only a canonical result file, without following any symlinks."""
    canonical_path(relative)
    if not relative.startswith(EXECUTION_PREFIX) or relative == EXECUTION_PREFIX:
        raise ValueError("grounding proof must remain under the execution prefix")
    if not re.fullmatch(r"[A-Za-z0-9_./+-]+", relative):
        raise ValueError("grounding proof is not an allowed result path")
    current = root
    for part in ("", *PurePosixPath(relative).parts):
        current /= part
        if current.is_symlink():
            raise ValueError("grounding execution path contains a symlink")
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError("grounding execution path escapes its root")
    return current


def junit_identity(case: str) -> tuple[str, str]:
    """Match pytest's default nodeid-to-JUnit spelling, including parameters."""
    if not isinstance(case, str) or any(ord(char) < 32 for char in case):
        raise ValueError("invalid reviewed pytest case")
    address, bracket, parameters = case.partition("[")
    parts = address.split("::")
    path = canonical_path(parts[0])
    if len(parts) < 2 or not path.endswith(".py") or not all(parts):
        raise ValueError("reviewed binding must identify a pytest test case")
    parts[0] = path.removesuffix(".py").replace("/", ".")
    parts[-1] += bracket + parameters
    return path, f"{'.'.join(parts[:-1])}::{parts[-1]}"


def execution_sources(out: Path, head: str, index: dict) -> tuple[dict, bytes, str]:
    sources = {}
    for name in ("test-execution-facts.json", "pytest-exact-head.log", "pytest-exact-head.xml"):
        path = out / name
        if path.is_symlink() or not path.is_file() or path.resolve().parent != out.resolve():
            raise ValueError("missing or unsafe exact-SHA execution source")
        sources[name] = path.read_bytes()
    facts = json.loads(sources["test-execution-facts.json"])
    execution = facts.get("execution") or {}
    command = execution.get("command")
    if (not re.fullmatch(r"[0-9a-f]{40}", head) or facts.get("subject_sha") != head
            or index.get("subject_sha") != head or facts.get("verification") != "passed"
            or type(execution.get("exit_code")) is not int or execution["exit_code"] != 0
            or not isinstance(command, str) or not command.strip()
            or any(ord(char) < 32 for char in command)
            or sha256(sources["pytest-exact-head.log"]) != execution.get("log_sha256")
            or sha256(sources["pytest-exact-head.xml"]) != index.get("source", {}).get("sha256")
            or index.get("requirement_mapping") != "UNKNOWN"):
        raise ValueError("grounding execution sources are not authenticated at the exact SHA")
    # The caller already rebuilt this index from JUnit; its digest binds these bytes.
    source_markers = "".join(f"SOURCE_SHA256: {name} {sha256(raw)}\n" for name, raw in sources.items())
    return execution, sources["pytest-exact-head.log"], source_markers


def verified_reached_cases(root: Path, item: dict, entries: object,
                           observed: dict, statuses: dict) -> list[str]:
    """Confirm one reviewed decision and every required replacement path."""
    path = canonical_path(item["path"])
    if item.get("decision") in {"not-testable", "blocked", "not-testable/blocked"}:
        raise ValueError("a blocked or not-testable decision cannot acquire passed execution")
    expected = item.get("replacement_tests") if item["operation"] == "deleted" else [path]
    if not isinstance(expected, list) or not expected:
        raise ValueError("deleted test requires explicit replacement test paths")
    expected = {canonical_path(value) for value in expected}
    if not isinstance(entries, list) or not entries:
        raise ValueError("pending test decision lacks reviewed case bindings")
    cases, covered_paths = set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"case", "test_case_id"}:
            raise ValueError("invalid reviewed grounding case binding")
        case, identity = entry["case"], entry["test_case_id"]
        test_path, actual_identity = junit_identity(case)
        if (test_path not in expected or identity != actual_identity or case in cases
                or observed.get(case) != "PASSED" or statuses.get(identity) != "passed"):
            raise ValueError("grounding binding is absent, ambiguous, skipped, nonpassing or mismatched")
        source = root / test_path
        if source.is_symlink() or not source.is_file() or source.resolve() != root.resolve() / test_path:
            raise ValueError("reviewed reached test path is missing or unsafe")
        cases.add(case)
        covered_paths.add(test_path)
    if covered_paths != expected:
        raise ValueError("grounding binding does not reach every replacement test path")
    return sorted(cases)


def bind_grounding_execution(root: Path, out: Path, report: dict,
                             bindings: object, head: str, index: dict) -> dict:
    """Fill only explicitly requested execution facts after source verification."""
    bound = copy.deepcopy(report)
    pending = [item for item in bound.get("test_decisions", [])
               if item.get("verification") == {"status": "unknown", "reason": PENDING_REASON}]
    if not pending and bindings in (None, {}):
        return bound  # Preserve attested reports and unrelated UNKNOWN decisions.
    if (not isinstance(bindings, dict) or set(bindings) != {item["path"] for item in pending}
            or len(pending) != len(bindings)):
        raise ValueError("reviewed grounding bindings must cover exactly the pending test decisions")
    execution, log, source_markers = execution_sources(out, head, index)
    statuses = {item["id"]: item["status"] for item in index["tests"]}
    observed = {}
    for line in log.decode("utf-8").splitlines():
        match = RESULT_LINE.fullmatch(line)
        if match:
            case, status = match.group("case", "status")
            if case in observed:
                raise ValueError("ambiguous repeated pytest case in execution log")
            observed[case] = status
    reached = {item["path"]: verified_reached_cases(root, item, bindings[item["path"]], observed, statuses)
               for item in pending}
    cases = sorted({case for values in reached.values() for case in values})
    raw = (f"HEAD: {head}\nCOMMAND: {execution['command']}\nEXIT_CODE: 0\n" + source_markers
           + "".join(f"REACHED: {case}\nJUNIT: {junit_identity(case)[1]}\nRESULT: PASSED\n" for case in cases)).encode()
    proof_hash = sha256(raw)
    relative = f"{EXECUTION_PREFIX}ground-tests-{head[:12]}-{proof_hash[:16]}.log"
    destinations = {execution_path(root, relative), execution_path(out, relative)}
    for destination in destinations:
        if destination.exists() and (not destination.is_file() or destination.read_bytes() != raw):
            raise ValueError("grounding proof destination already contains different evidence")
    # Validate all mappings and destinations before writing any proof or status.
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    for item in pending:
        item["verification"] = {
            "status": "passed", "command": execution["command"], "exit_code": 0,
            "subject_sha": head, "reached_tests": reached[item["path"]],
            "evidence_path": relative, "evidence_sha256": proof_hash,
        }
    return bound


def grounding_result_paths(root: Path, out: Path, report: dict) -> list[str]:
    """Authorize only already validated execution proofs with identical copies."""
    paths = set()
    for item in report.get("test_decisions", []):
        proof = item.get("verification") or {}
        if proof.get("status") != "passed":
            continue
        relative = proof.get("evidence_path")
        if not isinstance(relative, str) or not relative.startswith(EXECUTION_PREFIX):
            continue  # Existing attested evidence outside this producer keeps its contract.
        source, artifact = execution_path(root, relative), execution_path(out, relative)
        if not source.is_file() or not artifact.is_file():
            raise ValueError("grounding execution proof is missing from checkout or artifact")
        raw = source.read_bytes()
        if artifact.read_bytes() != raw or sha256(raw) != proof.get("evidence_sha256"):
            raise ValueError("grounding execution proof digest differs between checkout and artifact")
        paths.add(relative)
    return sorted(paths)
