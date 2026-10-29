#!/usr/bin/env python3
"""Recognize the bounded certificate-preparation postcondition from immutable audit data."""
from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
from pathlib import Path

from certificate_replay_io import clean_environment, digest, read_artifact, read_object

GATE_PATH = "entregar-issue/scripts/require_actions_handoff_certificate.py"
HEX_SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_GATE_BYTES = 128 * 1024


def parse_command(command: str) -> list[str]:
    if not isinstance(command, str) or len(command) > 16384 or any(ord(c) < 32 for c in command):
        raise ValueError("invalid literal certificate postcondition command")
    argv = shlex.split(command)
    if (len(argv) != 8 or " ".join(argv) != command
            or argv[2::2] != ["--evidence-dir", "--event", "--base-ref"]
            or not argv[1].endswith("/" + GATE_PATH)
            or not re.fullmatch(r"[A-Za-z0-9_./+-]+", argv[7])):
        raise ValueError("unsupported literal certificate postcondition command")
    paths = [Path(argv[index]) for index in (0, 1, 3, 5)]
    if (any(not path.is_absolute() or ".." in path.parts or str(path) != argv[index]
            for path, index in zip(paths, (0, 1, 3, 5), strict=True))
            or len(set(paths)) != len(paths)
            or any(path.is_relative_to(other) for path in paths for other in paths if path != other)):
        raise ValueError("literal postcondition paths overlap or are noncanonical")
    return argv


def git(repo: Path, *args: str) -> bytes:
    env = {**clean_environment(), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_NO_LAZY_FETCH": "1"}
    return subprocess.run(["git", "--no-replace-objects", "-c", "protocol.allow=never", "-C", str(repo), *args],
                          check=True, capture_output=True, env=env, timeout=30).stdout


def trusted_gate(repo: Path, anchor: str, material: str, base: str) -> tuple[dict, bytes]:
    if any(not isinstance(value, str) or not HEX_SHA.fullmatch(value) for value in (anchor, material, base)):
        raise ValueError("replay trust requires exact Git commit SHAs")
    for head in {material, base}:
        git(repo, "cat-file", "-e", head + "^{commit}")
        git(repo, "merge-base", "--is-ancestor", anchor, head)
    entry = git(repo, "ls-tree", "-z", anchor, "--", GATE_PATH)
    metadata, name = entry.removesuffix(b"\0").split(b"\t", 1)
    mode, kind, blob = metadata.decode("ascii").split()
    if name.decode() != GATE_PATH or mode not in {"100644", "100755"} or kind != "blob":
        raise ValueError("trusted postcondition gate is not a regular canonical Git blob")
    size = int(git(repo, "cat-file", "-s", blob))
    if size < 1 or size > MAX_GATE_BYTES:
        raise ValueError("trusted postcondition gate exceeds its size bound")
    raw = git(repo, "cat-file", "blob", blob)
    actual_blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0" + raw, usedforsecurity=False).hexdigest()
    if len(raw) != size or actual_blob != blob:
        raise ValueError("trusted gate changed during Git read")
    return {"anchor": anchor, "path": GATE_PATH, "git_blob": blob, "sha256": digest(raw)}, raw


def postcondition_items(source: dict) -> list[dict]:
    """Pure strict detector; unrelated deterministic gates retain their normal requirements."""
    result = []
    for kind, rows in (("finding", source.get("findings", [])), ("recommendation", source.get("recommendations", []))):
        if not isinstance(rows, list):
            raise ValueError("audit postcondition inventory must be an array")
        for row in rows:
            if not isinstance(row, dict) or row.get("status") == "closed" or row.get("actionable") is False:
                continue
            gate = row.get("failed_gate")
            if not isinstance(gate, dict) or gate.get("deterministic") is not True:
                continue
            command = gate.get("command", "")
            if not isinstance(command, str) or Path(GATE_PATH).name not in command:
                continue
            argv = parse_command(command)
            subject = gate.get("subject_sha", gate.get("head_sha"))
            code = gate.get("observed_exit_code", gate.get("exit_code"))
            identifier = row.get("id")
            if (not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", identifier)
                    or not isinstance(subject, str) or not HEX_SHA.fullmatch(subject)
                    or type(code) is not int or code == 0):
                raise ValueError("original postcondition lacks exact failure identity")
            source_kind = "recommendation" if row.get("disposition") == "recommendation" else kind
            result.append({"source_kind": source_kind, "source_id": identifier, "command": command,
                           "argv": argv, "original_subject_sha": subject, "original_exit_code": code})
    keys = [(item["source_kind"], item["source_id"]) for item in result]
    if len(set(keys)) != len(keys) or len(result) > 32:
        raise ValueError("duplicate or excessive certificate postconditions")
    return result


def recognize_postconditions(audit_result_path: Path, repo: Path, material_sha: str, *, expected_base: str) -> dict:
    source, raw, _ = read_artifact(audit_result_path)
    items = postcondition_items(source)
    identity = source.get("identity") or {}
    anchor = source.get("trusted_anchor_sha")
    plan = {"schema_version": 1, "type": "certificate-preparation-postconditions",
            "material_head_sha": material_sha, "base_sha": expected_base, "audit_report_sha256": digest(raw),
            "rejection_id": source.get("rejection_id"), "trusted_anchor_sha": anchor,
            "repository": identity.get("repository"), "items": []}
    if not items:
        return plan
    audited = source.get("head_sha") or identity.get("head_sha")
    if (anchor != identity.get("base_sha") or not plan["rejection_id"] or not plan["repository"]
            or any(item["original_subject_sha"] != audited for item in items)):
        raise ValueError("postcondition is not bound to the original audit and trusted base")
    descriptor, _ = trusted_gate(repo, anchor, material_sha, expected_base)
    git(repo, "merge-base", "--is-ancestor", anchor, audited)
    plan["items"] = [{**item, "gate_path": descriptor["path"], "gate_blob_sha": descriptor["git_blob"],
                      "gate_source_sha256": descriptor["sha256"]} for item in items]
    return plan


def verify_postcondition_plan(plan_path: Path, audit_result_path: Path, head_sha: str, repository: Path, *, expected_base: str) -> dict:
    plan, _ = read_object(plan_path)
    expected = recognize_postconditions(audit_result_path, repository, head_sha, expected_base=expected_base)
    if plan != expected:
        raise ValueError("postcondition plan differs from the authenticated audit source")
    return expected
