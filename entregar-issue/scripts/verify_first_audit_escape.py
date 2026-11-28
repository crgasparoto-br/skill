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

from audit_artifact_io import load_json_artifact, read_logical_bytes
from git_tree_snapshot import git_run, material_parent_blob

ROOT_LEDGER = ".audit/entregar-issue/audit-escape-closure.json"


def verified_git_ledger(repository: Path, source_sha: str, raw: bytes,
                        ledger_path: str = ROOT_LEDGER) -> tuple[bytes, dict]:
    """Read canonical logical bytes from authenticated Git, including every shard."""
    try:
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("previous ledger must be a JSON object")
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
                    blob = material_parent_blob(repository, source_sha, str(Path(ledger_path).parent / relative))
                    if blob is None:
                        raise ValueError("previous global ledger shard missing")
                    output = Path(directory) / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(blob)
                raw, _ = read_logical_bytes(target)
                data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("subject"), dict):
            raise ValueError("previous global ledger lacks subject")
        subject = data["subject"]
        issue, pr = subject.get("issue_number"), subject.get("pull_request_number")
        if (not isinstance(subject.get("repository"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", subject["repository"])
                or type(issue) is not int or issue <= 0
                or "pull_request_number" not in subject
                or pr is not None and (type(pr) is not int or pr <= 0)
                or not isinstance(subject.get("material_head_sha"), str)
                or not re.fullmatch(r"[0-9a-f]{40}", subject["material_head_sha"])):
            raise ValueError("previous ledger subject identity is malformed")
        return raw, data
    except (UnicodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        raise ValueError("previous global ledger cannot be validated") from exc


def verified_global_subject(repository: Path, source_sha: str, raw: bytes) -> dict:
    return verified_git_ledger(repository, source_sha, raw)[1]["subject"]


def ledger_history(repository: Path, material_sha: str, path: str):
    """Read reachable historical versions, not just endpoint presence or changed files."""
    shards = str(Path(path).with_suffix(".parts"))
    changes = git_run(repository, "log", "--full-history", "--format=%H",
                      material_sha, "--", path, shards).decode("ascii").splitlines()
    if len(changes) > 2000:
        raise ValueError("audit escape history exceeds proof budget")
    for sha in dict.fromkeys([material_sha, *changes]):
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("audit escape history returned malformed commit")
        raw = material_parent_blob(repository, sha, path)
        if raw is not None:
            yield sha, raw


def ensure_no_historical_ledger(
    repository: Path, material_sha: str, issue_path: str,
    repository_name: str, issue_number: int,
) -> None:
    """Reject ledger creation/deletion anywhere in the reachable target history."""
    for path in (issue_path, ROOT_LEDGER):
        for commit_sha, raw in ledger_history(repository, material_sha, path):
            if path == issue_path:
                raise ValueError("historical same-target audit escape exists; snapshot required")
            subject = verified_global_subject(repository, commit_sha, raw)
            if subject.get("repository") != repository_name:
                raise ValueError("historical ledger repository differs from trusted target")
            if subject.get("issue_number") == issue_number:
                raise ValueError("historical same-target global ledger exists; snapshot required")


def verify_rejection_anchor(
    repository: Path, *, audited_sha: str, material_sha: str,
    repository_name: str, issue_number: int, pull_request_number: int | None,
    audit_result: Path,
) -> None:
    """Bind a rejected audit to a complete, ancestral Git history of this target."""
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
    if git_run(repository, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ValueError("first-escape absence requires complete Git history")
    try:
        git_run(repository, "merge-base", "--is-ancestor", audited_sha, material_sha)
    except subprocess.CalledProcessError as exc:
        raise ValueError("audited commit is not an ancestor of the material head") from exc


def prove_first_audit_escape(
    repository: Path, *, audited_sha: str, material_sha: str,
    repository_name: str, issue_number: int, pull_request_number: int | None,
    audit_result: Path,
) -> dict:
    """Reject unknown provenance, malformed foreign history, or erased same-target history."""
    verify_rejection_anchor(repository, audited_sha=audited_sha, material_sha=material_sha,
                            repository_name=repository_name, issue_number=issue_number,
                            pull_request_number=pull_request_number, audit_result=audit_result)
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

    # A prior ledger cannot be hidden by deleting it before either endpoint.
    ensure_no_historical_ledger(repository, material_sha, issue_path, repository_name, issue_number)

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
