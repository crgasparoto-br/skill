"""Prove the first rejection has no SAME-TARGET escape ledger in trusted Git.

The repository must be supplied by the delivery's authenticated GitHub bundle /
trusted connector checkout. A JSON absence claim is not a substitute for Git.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from audit_artifact_io import load_json_artifact
from git_tree_snapshot import git_run, material_parent_blob

ROOT_LEDGER = ".audit/entregar-issue/audit-escape-closure.json"


def verified_global_subject(repository: Path, source_sha: str, raw: bytes) -> dict:
    """Decode source Git blobs, including sharded manifests, before target selection."""
    try:
        data = json.loads(raw.decode("utf-8"))
        if data.get("artifact_format") == "base64-shards-v1":
            with TemporaryDirectory() as directory:
                target = Path(directory) / "audit-escape-closure.json"
                target.write_bytes(raw)
                for part in data.get("parts", []):
                    if not isinstance(part, dict) or not isinstance(part.get("path"), str):
                        raise ValueError("malformed previous ledger shard")
                    relative = part["path"]
                    if not re.fullmatch(r"audit-escape-closure\.parts/part-[0-9]{3}\.b64", relative):
                        raise ValueError("unsafe previous ledger shard path")
                    blob = material_parent_blob(repository, source_sha, ".audit/entregar-issue/" + relative)
                    if blob is None:
                        raise ValueError("previous global ledger shard missing")
                    output = Path(directory) / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(blob)
                data = load_json_artifact(target, require_object=True)
        if not isinstance(data, dict) or not isinstance(data.get("subject"), dict):
            raise ValueError("previous global ledger lacks subject")
        return data["subject"]
    except (UnicodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ValueError("previous global ledger cannot be validated") from exc


def prove_first_audit_escape(
    repository: Path, *, audited_sha: str, material_sha: str,
    repository_name: str, issue_number: int, pull_request_number: int | None,
    audit_result: Path,
) -> dict:
    """Reject unknown provenance, malformed foreign history, or erased same-target history."""
    if not all(re.fullmatch(r"[0-9a-f]{40}", value or "") for value in (audited_sha, material_sha)):
        raise ValueError("first-escape proof requires exact audited and material SHA")
    if not (isinstance(issue_number, int) and not isinstance(issue_number, bool) and issue_number > 0
            and isinstance(pull_request_number, int) and not isinstance(pull_request_number, bool)
            and pull_request_number > 0):
        raise ValueError("first-escape proof requires canonical issue and PR numbers")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_name):
        raise ValueError("first-escape proof requires repository owner/name")
    if not repository.is_dir() or not audit_result.is_file():
        raise ValueError("first-escape proof requires Git checkout and original audit source")
    report = load_json_artifact(audit_result, require_object=True)
    identity = report.get("identity")
    if not isinstance(identity, dict) or (
        report.get("head_sha") != audited_sha
        or identity.get("head_sha") != audited_sha
        or identity.get("repository") != repository_name
        or identity.get("issue_number") != issue_number
        or identity.get("pull_request_number") != pull_request_number
        or report.get("status") != "rejected"
        or not str(report.get("rejection_id") or "").startswith("audit-rejection:")
    ):
        raise ValueError("first-escape proof audited SHA, rejection or subject mismatch")
    git_run(repository, "cat-file", "-e", audited_sha + "^{commit}")
    git_run(repository, "cat-file", "-e", material_sha + "^{commit}")
    try:
        git_run(repository, "merge-base", "--is-ancestor", audited_sha, material_sha)
    except subprocess.CalledProcessError as exc:
        raise ValueError("audited commit is not an ancestor of the material head") from exc

    # The names are derived from the canonical subject, never from caller input.
    issue_path = f".audit/entregar-issue/issue-{issue_number}/audit-escape-closure.json"
    absent: set[str] = set()
    foreign: set[str] = set()
    for source_sha in (audited_sha, material_sha):
        for path in (issue_path, ROOT_LEDGER):
            raw = material_parent_blob(repository, source_sha, path)
            if raw is None:
                absent.add(path)
                continue
            if path == issue_path:
                raise ValueError("prior same-target issue-scoped audit escape exists; snapshot required")
            subject = verified_global_subject(repository, source_sha, raw)
            if subject.get("repository") != repository_name:
                raise ValueError("previous global ledger repository differs from claimed repository")
            if subject.get("issue_number") == issue_number:
                raise ValueError("previous same-target global ledger exists; snapshot required")
            foreign.add(path)

    return {
        "status": "absent-proved-on-target",
        "reference_sha": audited_sha,
        "material_head_sha": material_sha,
        "repository": repository_name,
        "issue_number": issue_number,
        "pull_request_number": pull_request_number,
        "absent_paths": sorted(absent),
        "foreign_target_paths": sorted(foreign),
    }
