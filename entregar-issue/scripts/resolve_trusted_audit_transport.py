#!/usr/bin/env python3
"""Resolve audit transport from immutable Git bytes in the trusted PR base.

The caller MUST be trusted workflow code checking out the authenticated
repository and material head. Candidate files are never an authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CONTRACT_PATH = "docs/audit/github-native-contract.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
EXPECTED_FIELDS = frozenset({
    "schema_version", "repository", "base_ref", "canonical", "audit_mode",
    "legacy_handoff_policy", "github_native_identity", "exact_sha_evidence",
    "independent_review", "remote_ci_evidence",
})


def git(root: Path, *arguments: str) -> bytes:
    proc = subprocess.run(
        ["git", *arguments], cwd=root, capture_output=True, check=False,
    )
    if proc.returncode:
        raise ValueError("trusted Git object or ancestry validation failed")
    return proc.stdout


def _unique_json_pairs(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate trusted native contract JSON field")
        result[key] = value
    return result


def _contract(root: Path, base_sha: str, repository: str, base_ref: str) -> dict | None:
    entries = git(root, "ls-tree", "--full-tree", base_sha, "--", CONTRACT_PATH)
    if not entries:
        return None
    lines = entries.splitlines()
    if len(lines) != 1:
        raise ValueError("trusted contract path is ambiguous")
    metadata, separator, actual_path = lines[0].partition(b"\t")
    fields = metadata.split()
    if (separator != b"\t" or actual_path != CONTRACT_PATH.encode("utf-8")
            or len(fields) != 3 or fields[0] != b"100644"
            or fields[1] != b"blob" or SHA.fullmatch(fields[2].decode("ascii")) is None):
        raise ValueError("trusted contract must be a regular Git blob at the canonical path")
    object_sha = fields[2].decode("ascii")
    raw = git(root, "cat-file", "blob", object_sha)
    if len(raw) > 16384:
        raise ValueError("trusted native contract exceeds size budget")
    recomputed = hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw,
        usedforsecurity=False,
    ).hexdigest()
    if object_sha != recomputed:
        raise ValueError("trusted contract Git blob digest mismatch")
    try:
        source = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("trusted contract JSON is invalid") from exc
    if not isinstance(source, dict) or set(source) != EXPECTED_FIELDS:
        raise ValueError("trusted contract has missing or unexpected fields")
    if (type(source["schema_version"]) is not int or source["schema_version"] != 1
            or source["repository"] != repository or source["base_ref"] != base_ref
            or source["canonical"] is not True
            or source["audit_mode"] != "native-github"
            or source["legacy_handoff_policy"] not in ("not-required", "forbidden")
            or any(source[key] is not True for key in (
                "github_native_identity", "exact_sha_evidence",
                "independent_review", "remote_ci_evidence"
            ))):
        raise ValueError("trusted native audit contract is incomplete or foreign")
    return {
        "path": CONTRACT_PATH,
        "observed_at_sha": base_sha,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "source_git_blob_sha": object_sha,
        "canonical": True,
        **{key: source[key] for key in (
            "audit_mode", "legacy_handoff_policy", "github_native_identity",
            "exact_sha_evidence", "independent_review", "remote_ci_evidence"
        )},
    }


def resolve(root: Path, repository: str, base_ref: str,
            base_sha: str, head_sha: str) -> dict:
    if (REPOSITORY.fullmatch(repository) is None or base_ref != "develop"
            or SHA.fullmatch(base_sha) is None or SHA.fullmatch(head_sha) is None):
        raise ValueError("repository, develop base or Git SHA is invalid")
    git(root, "cat-file", "-e", base_sha + "^{commit}")
    git(root, "cat-file", "-e", head_sha + "^{commit}")
    if git(root, "rev-parse", "HEAD").decode("ascii").strip() != head_sha:
        raise ValueError("material checkout HEAD differs from authenticated PR head")
    # A normal PR may be behind develop: its current base SHA need not be an
    # ancestor of the feature head. Require a genuine shared Git history,
    # without inventing a fast-forward relation.
    common_base = git(root, "merge-base", base_sha, head_sha).decode("ascii").strip()
    if SHA.fullmatch(common_base) is None:
        raise ValueError("trusted base and material HEAD lack a valid common ancestor")
    manifest = {
        "schema_version": 1,
        "repository": repository,
        "trusted_anchor_sha": base_sha,
        "contract": _contract(root, base_sha, repository, base_ref),
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "audit-transport.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("classify_audit_transport.py")),
             "--manifest", str(path)],
            text=True, capture_output=True, check=False,
        )
    if proc.returncode:
        raise ValueError("canonical audit transport classifier rejected the manifest")
    result = json.loads(proc.stdout)
    if (result["mode"] == "native-github-audit") != (manifest["contract"] is not None):
        raise ValueError("native contract and transport classification disagree")
    return {**result, "repository": repository, "base_ref": base_ref,
            "material_head_sha": head_sha, "contract": manifest["contract"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-ref", default="develop")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = resolve(args.root.resolve(), args.repository, args.base_ref,
                         args.base_sha, args.head_sha)
        output = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
        if args.output is not None:
            args.output.write_text(output, encoding="utf-8")
        print(output, end="")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
