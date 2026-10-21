#!/usr/bin/env python3
"""Restore an exact-SHA, trusted CI Git bundle without network access.

The caller MUST independently authenticate the PR base/head and successful CI run
against GitHub before invoking this script. The archive manifest is NOT an anchor.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
MAX_BUNDLE = 512 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
FILES = {"manifest.json", "repository.bundle"}


class BundleError(Exception):
    pass


def git(*args: str, cwd: Path | None = None) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_ALLOW_PROTOCOL="file")
    result = subprocess.run(["git", *args], cwd=cwd, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise BundleError(f"git {' '.join(args[:3])} failed: {result.stderr.strip()[:500]}")
    return result.stdout.strip()


def extract(archive: Path, destination: Path) -> dict:
    try:
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            if len(infos) != 2 or {item.filename for item in infos} != FILES:
                raise BundleError("archive must contain exactly manifest.json and repository.bundle")
            for item in infos:
                if item.is_dir() or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise BundleError("archive contains a directory or symlink")
                limit = MAX_MANIFEST if item.filename == "manifest.json" else MAX_BUNDLE
                if item.file_size > limit:
                    raise BundleError(f"archive member too large: {item.filename}")
                with zf.open(item) as source, (destination / item.filename).open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                if (destination / item.filename).stat().st_size > limit:
                    raise BundleError(f"archive member exceeded byte limit: {item.filename}")
    except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as exc:
        raise BundleError(f"invalid CI artifact: {exc}") from exc
    try:
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise BundleError(f"invalid manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise BundleError("manifest must be a JSON object")
    return manifest


def restore(args: argparse.Namespace) -> dict:
    if not REPOSITORY.fullmatch(args.repository):
        raise BundleError("invalid repository identity")
    if not SHA.fullmatch(args.trusted_base_sha) or not SHA.fullmatch(args.trusted_head_sha):
        raise BundleError("trusted base/head must be exact lowercase 40-character SHAs")
    if not args.run_id.isdecimal() or int(args.run_id) < 1:
        raise BundleError("run ID must be a positive integer from GitHub")
    if not args.base_ref.strip():
        raise BundleError("trusted base ref must not be empty")
    output = args.output.resolve()
    if output.exists():
        raise BundleError("output already exists; never overwrite an existing Git checkout")
    if not output.parent.is_dir():
        raise BundleError("output parent directory does not exist")
    with tempfile.TemporaryDirectory(prefix="audit-git-bundle-", dir=output.parent) as scratch:
        stage = Path(scratch)
        manifest = extract(args.archive, stage)
        expected = {
            "schemaVersion": 1,
            "repository": args.repository,
            "baseRef": args.base_ref,
            "baseSha": args.trusted_base_sha,
            "headSha": args.trusted_head_sha,
            "runId": args.run_id,
        }
        for key, value in expected.items():
            if str(manifest.get(key)) != str(value):
                raise BundleError(f"CI artifact manifest {key} disagrees with trusted GitHub metadata")
        bundle = stage / "repository.bundle"
        repository = stage / "git-checkout.git"
        git("init", "--bare", "-q", str(repository))
        git("-C", str(repository), "bundle", "verify", str(bundle))
        advertised = git("-C", str(repository), "bundle", "list-heads", str(bundle)).splitlines()
        advertised_refs = dict(line.split(" ", 1)[::-1] for line in advertised if " " in line)
        if (advertised_refs.get("refs/ci-verification/base") != args.trusted_base_sha
                or advertised_refs.get("refs/ci-verification/head") != args.trusted_head_sha):
            raise BundleError("bundle advertised refs disagree with independently verified SHAs")
        git("-C", str(repository), "bundle", "unbundle", str(bundle))
        for sha in (args.trusted_base_sha, args.trusted_head_sha):
            if git("-C", str(repository), "rev-parse", f"{sha}^{{commit}}") != sha:
                raise BundleError("trusted SHA is not a commit object")
        git("-C", str(repository), "fsck", "--full", "--no-reflogs")
        # The same three-dot diff used by validate_audit_completeness.py.
        changed = git("-C", str(repository), "diff", "--name-only", "--no-renames",
                      f"{args.trusted_base_sha}...{args.trusted_head_sha}").splitlines()
        repository.rename(output)
    return {"repository": args.repository, "base_sha": args.trusted_base_sha,
            "head_sha": args.trusted_head_sha, "run_id": args.run_id,
            "git_repo": str(output), "changed_paths": changed, "status": "restored"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--trusted-base-sha", required=True)
    parser.add_argument("--trusted-head-sha", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        result = restore(args)
    except (BundleError, OSError) as exc:
        print(f"BLOCK: offline CI Git bundle restoration unavailable: {exc}")
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
