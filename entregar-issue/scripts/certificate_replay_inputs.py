#!/usr/bin/env python3
"""Authenticate the immutable preparation, its complete snapshots and original rejection."""
from __future__ import annotations

import os
import re
from pathlib import Path

from certificate_replay_io import (
    MAX_INVENTORY_BYTES,
    digest,
    read_artifact,
    read_object,
    relative_path,
    safe_read,
)
from certificate_replay_source import HEX_SHA, postcondition_items

HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def declared_snapshots(value: dict) -> dict[str, str]:
    entries = value.get("prepared_files")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 512:
        raise ValueError("prepared snapshot inventory is empty or exceeds its bound")
    declared = {}
    for item in entries:
        if not isinstance(item, dict) or set(item) != {"name", "sha256"}:
            raise ValueError("invalid prepared file inventory")
        name = relative_path(item["name"])
        if not name.startswith("prepared/") or name in declared or not HEX_DIGEST.fullmatch(str(item["sha256"])):
            raise ValueError("unsafe, duplicate or unhashed prepared snapshot")
        declared[name] = item["sha256"]
    return declared


def snapshot_inventory(preparation: Path, declared: dict[str, str]) -> None:
    folder = preparation.parent / "prepared"
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("prepared snapshot directory is missing or unsafe")
    pending, found, total, directories = [folder], set(), 0, 1
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise ValueError("prepared snapshot contains a symlink")
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                    directories += 1
                    if directories > 512:
                        raise ValueError("prepared directory inventory exceeds its bound")
                    continue
                path = Path(entry.path)
                name = path.relative_to(preparation.parent).as_posix()
                if name not in declared:
                    raise ValueError("unlisted prepared snapshot")
                raw = safe_read(path)
                total += len(raw)
                if total > MAX_INVENTORY_BYTES or digest(raw) != declared[name]:
                    raise ValueError("prepared snapshot digest or size differs")
                found.add(name)
    if found != set(declared):
        raise ValueError("prepared snapshot is missing")


def prepared_inventory(preparation: Path, value: dict) -> None:
    declared = declared_snapshots(value)
    snapshot_inventory(preparation, declared)
    artifacts = value.get("prepared_artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError("preparation lacks its complete semantic artifact map")
    for item in artifacts.values():
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or declared.get(item["name"]) != item.get("sha256"):
            raise ValueError("prepared artifact is not bound to a snapshot")
        _, _, actual = read_artifact(preparation.parent / item["name"])
        if any(actual.get(key) != item[key] for key in ("sha256", "logical_sha256", "logical_size", "artifact_transport") if key in item):
            raise ValueError("prepared artifact transport differs from authenticated metadata")
    for name, expected in declared.items():
        if digest(safe_read(preparation.parent / name)) != expected:
            raise ValueError("prepared snapshot changed after validation")


def preparation_inputs(preparation: Path, event: Path, expected_base: str) -> tuple[dict, bytes, bytes, dict]:
    value, raw = read_object(preparation)
    payload, event_raw = read_object(event)
    if value.get("schema_version") != 2 or value.get("phase") != "preparation" or value.get("status") != "prepared" or "artifacts" in value:
        raise ValueError("postcondition requires an explicitly unpublishable preparation")
    subject, identity = value.get("subject"), value.get("identity")
    pr = payload.get("pull_request")
    if not all(isinstance(item, dict) for item in (subject, identity, pr)):
        raise ValueError("preparation/event identity must be objects")
    repository = subject.get("repository")
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(repository))
            or not re.fullmatch(r"[A-Za-z0-9_./+-]+", str(subject.get("base_ref")))
            or any(type(subject.get(key)) is not int or subject[key] < 1 for key in ("issue_number", "pull_request_number"))
            or type(pr.get("number")) is not int):
        raise ValueError("preparation/event subject has invalid types or identifiers")
    if (not HEX_SHA.fullmatch(str(identity.get("material_head_sha"))) or not HEX_SHA.fullmatch(str(expected_base))
            or identity.get("base_sha") != expected_base or pr.get("base", {}).get("sha") != expected_base
            or pr.get("head", {}).get("sha") != identity.get("material_head_sha")
            or payload.get("repository", {}).get("full_name") != repository
            or pr.get("head", {}).get("repo", {}).get("full_name") != repository
            or pr.get("number") != subject.get("pull_request_number")
            or pr.get("base", {}).get("ref") != subject.get("base_ref")):
        raise ValueError("preparation/event does not match the authenticated material and base")
    prepared_inventory(preparation, value)
    bound = {"material_head_sha": identity["material_head_sha"], "base_sha": expected_base,
             **{key: subject[key] for key in ("repository", "issue_number", "pull_request_number", "base_ref")}}
    return value, raw, event_raw, bound


def source_item(preparation: Path, value: dict, command: str, anchor: str, kind: str, identifier: str) -> Path:
    item = value["prepared_artifacts"].get("audit_source_result") or {}
    path = preparation.parent / relative_path(item.get("name"))
    source, _, _ = read_artifact(path)
    matches = [row for row in postcondition_items(source) if (row["source_kind"], row["source_id"]) == (kind, identifier)]
    identity = source.get("identity") or {}
    audited = source.get("head_sha") or identity.get("head_sha")
    if (len(matches) != 1 or matches[0]["command"] != command or source.get("trusted_anchor_sha") != anchor
            or identity.get("base_sha") != anchor or identity.get("repository") != value["subject"]["repository"]
            or matches[0]["original_subject_sha"] != audited or identity.get("head_sha", audited) != audited):
        raise ValueError("replay does not match the original postcondition, repository and trust anchor")
    return path
