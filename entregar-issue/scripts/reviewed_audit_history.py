"""Select reviewed rejection inputs without manufacturing historical evidence."""
from __future__ import annotations

import json
import re
import subprocess
from typing import TYPE_CHECKING

from git_tree_snapshot import git_run, material_parent_blob
from reviewed_phase_decision import digest
from verify_first_audit_escape import (
    ROOT_LEDGER,
    ledger_history,
    prove_first_audit_escape,
    verified_git_ledger,
    verify_rejection_anchor,
)

if TYPE_CHECKING:
    from pathlib import Path

PREVIOUS_ESCAPE = "previous-audit-escape-closure.json"
AUDIT_SOURCE = "audit-source-result.json"
IMMUTABLE_REPORTS = frozenset({AUDIT_SOURCE, PREVIOUS_ESCAPE, "previous-inherited-controls.json"})


def verified_source_bytes(source: Path, name: str, hashes: dict) -> bytes:
    if name not in hashes or not re.fullmatch(r"[0-9a-f]{64}", str(hashes[name])):
        raise ValueError(f"missing SHA-256 declaration for {name}")
    path = source / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != source.resolve():
        raise ValueError(f"unsafe reviewed evidence path: {name}")
    raw = path.read_bytes()
    if not raw or digest(raw) != hashes[name]:
        raise ValueError(f"reviewed evidence digest mismatch: {name}")
    return raw


def committed_report_bytes(root: Path, source: Path, name: str, hashes: dict, head: str) -> bytes:
    raw = verified_source_bytes(source, name, hashes)
    relative = (source / name).relative_to(root).as_posix()
    if material_parent_blob(root, head, relative) != raw:
        raise ValueError(f"historical report differs from exact material Git blob: {name}")
    if not isinstance(json.loads(raw.decode("utf-8")), dict):
        raise ValueError(f"historical report must be a JSON object: {name}")
    return raw


def verified_source(root: Path, source: Path, name: str, hashes: dict) -> dict:
    data = json.loads(verified_source_bytes(source, name, hashes).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"evidence must be a JSON object: {name}")
    return data


def escape_ids(ledger: dict) -> set[str]:
    entries = ledger.get("escapes", [ledger])
    if not isinstance(entries, list) or not entries:
        raise ValueError("previous ledger must contain actual escape entries")
    ids = [entry.get("escape_id") if isinstance(entry, dict) else None for entry in entries]
    if any(not isinstance(item, str) or not item.strip() for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("previous ledger contains missing or duplicate escape IDs")
    return set(ids)


def authenticate_previous_snapshot(root: Path, *, audited_sha: str, material_sha: str,
                                   repository_name: str, issue_number: int,
                                   pull_request_number: int, audit_result: Path,
                                   snapshot: bytes) -> dict:
    """Match a real same-target snapshot and retain IDs across the audited interval."""
    verify_rejection_anchor(root, audited_sha=audited_sha, material_sha=material_sha,
                            repository_name=repository_name, issue_number=issue_number,
                            pull_request_number=pull_request_number, audit_result=audit_result)
    expected = {"repository": repository_name, "issue_number": issue_number,
                "pull_request_number": pull_request_number}
    ledger = json.loads(snapshot.decode("utf-8"))
    subject = ledger.get("subject") if isinstance(ledger, dict) else None
    if not isinstance(subject, dict) or any(subject.get(key) != value for key, value in expected.items()):
        raise ValueError("previous reviewed escape snapshot belongs to a different target")
    report = json.loads(audit_result.read_bytes())
    published = report["identity"].get("published_handoff_head_sha", audited_sha)
    if published != audited_sha:
        if not isinstance(published, str) or not re.fullmatch(r"[0-9a-f]{40}", published):
            raise ValueError("historical published handoff SHA is not exact")
        if git_run(root, "rev-list", "--parents", "-n", "1", published).decode().split() != [published, audited_sha]:
            raise ValueError("historical published handoff is not a direct child of the audited SHA")
        git_run(root, "merge-base", "--is-ancestor", published, material_sha)
    preserved = escape_ids(ledger)
    observed_ids: set[str] = set()
    matching_sources = []
    scoped = f".audit/entregar-issue/issue-{issue_number}/audit-escape-closure.json"
    for path in (scoped, ROOT_LEDGER):
        for sha, raw in ledger_history(root, material_sha, path):
            logical, record = verified_git_ledger(root, sha, raw, path)
            historical = record["subject"]
            if historical.get("repository") != repository_name:
                raise ValueError("historical ledger repository differs from trusted target")
            if historical.get("issue_number") != issue_number:
                if path == scoped:
                    raise ValueError("issue-scoped historical ledger belongs to a different target")
                continue
            observed_ids.update(escape_ids(record))
            if logical == snapshot and historical.get("pull_request_number") == pull_request_number:
                try:
                    git_run(root, "merge-base", "--is-ancestor", sha, published)
                except subprocess.CalledProcessError as exc:
                    if exc.returncode != 1:
                        raise
                else:
                    matching_sources.append({"sha": sha, "path": path})
    if not matching_sources:
        raise ValueError("previous reviewed escape snapshot has no exact authenticated Git source")
    if not observed_ids <= preserved:
        raise ValueError("previous reviewed escape snapshot omits historical escape IDs")
    return {"status": "previous-ledger-present", "sources": matching_sources,
            "snapshot_sha256": digest(snapshot)}


def resolve_reviewed_escape_history(root: Path, source: Path, hashes: dict,
                                    target: dict) -> dict:
    """Use only canonical Git facts to choose first-escape vs historical snapshot."""
    report = json.loads(committed_report_bytes(root, source, AUDIT_SOURCE, hashes, target["head_sha"]))
    args = {"audited_sha": report.get("head_sha"), "material_sha": target["head_sha"],
            "repository_name": target["repository"], "issue_number": target["issue_number"],
            "pull_request_number": target["pull_request_number"],
            "audit_result": source / AUDIT_SOURCE}
    if PREVIOUS_ESCAPE in hashes:
        snapshot = committed_report_bytes(root, source, PREVIOUS_ESCAPE, hashes, target["head_sha"])
        return authenticate_previous_snapshot(root, snapshot=snapshot, **args)
    path = source / PREVIOUS_ESCAPE
    if path.exists() or path.is_symlink():
        raise ValueError("previous reviewed escape snapshot is present but not declared")
    return prove_first_audit_escape(root, **args)
