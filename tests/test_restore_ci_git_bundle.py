"""Offline Git evidence restoration must fail closed on forged CI artifacts."""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "auditar-issue/scripts/restore_ci_git_bundle.py"
BASE_REF = "develop"
REPO_NAME = "org/repository"
RUN_ID = "12345"


def command(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def fixture(tmp_path: Path) -> tuple[Path, str, str, dict]:
    repo = tmp_path / "source"
    repo.mkdir()
    command("git", "init", "-q", str(repo))
    command("git", "config", "user.name", "Test", cwd=repo)
    command("git", "config", "user.email", "test@example.invalid", cwd=repo)
    (repo / "original.txt").write_text("original\n", encoding="utf-8")
    command("git", "add", ".", cwd=repo)
    command("git", "commit", "-qm", "base", cwd=repo)
    base = command("git", "rev-parse", "HEAD", cwd=repo)
    (repo / "candidate.txt").write_text("candidate\n", encoding="utf-8")
    command("git", "add", ".", cwd=repo)
    command("git", "commit", "-qm", "head", cwd=repo)
    head = command("git", "rev-parse", "HEAD", cwd=repo)
    command("git", "update-ref", "refs/ci-verification/base", base, cwd=repo)
    command("git", "update-ref", "refs/ci-verification/head", head, cwd=repo)
    bundle = tmp_path / "repository.bundle"
    command("git", "bundle", "create", str(bundle),
            "refs/ci-verification/base", "refs/ci-verification/head", cwd=repo)
    manifest = {"schemaVersion": 1, "repository": REPO_NAME,
                "baseRef": BASE_REF, "baseSha": base, "headSha": head,
                "runId": RUN_ID}
    return bundle, base, head, manifest


def archive(tmp_path: Path, bundle: Path, manifest: dict,
            *, extra: dict[str, bytes] | None = None) -> Path:
    path = tmp_path / "artifact.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.write(bundle, "repository.bundle")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return path


def restore(tmp_path: Path, zip_path: Path, base: str, head: str,
            *, repository: str = REPO_NAME, run_id: str = RUN_ID,
            base_ref: str = BASE_REF) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--archive", str(zip_path),
         "--output", str(tmp_path / "restored.git"), "--repository", repository,
         "--base-ref", base_ref, "--trusted-base-sha", base,
         "--trusted-head-sha", head, "--run-id", run_id],
        capture_output=True, text=True, check=False,
    )


def test_recovers_full_git_objects_and_changed_paths_without_network(tmp_path: Path) -> None:
    bundle, base, head, manifest = fixture(tmp_path)
    result = restore(tmp_path, archive(tmp_path, bundle, manifest), base, head)
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["changed_paths"] == ["candidate.txt"]
    assert payload["base_sha"] == base and payload["head_sha"] == head
    assert command("git", "-C", payload["git_repo"], "rev-parse", f"{head}^{{commit}}") == head
    assert command("git", "-C", payload["git_repo"], "diff", "--name-only", f"{base}...{head}") == "candidate.txt"


@pytest.mark.parametrize("field,replacement", [
    ("repository", "different/repo"),
    ("baseRef", "main"),
    ("runId", "54321"),
    ("baseSha", "a" * 40),
    ("headSha", "b" * 40),
    ("schemaVersion", 999),
])
def test_rejects_manifest_forgery(tmp_path: Path, field: str, replacement: object) -> None:
    bundle, base, head, manifest = fixture(tmp_path)
    manifest[field] = replacement
    result = restore(tmp_path, archive(tmp_path, bundle, manifest), base, head)
    assert result.returncode == 2
    assert "manifest" in result.stdout
    assert not (tmp_path / "restored.git").exists()


def test_rejects_bundle_with_different_git_objects_even_when_manifest_matches(tmp_path: Path) -> None:
    bundle, base, head, manifest = fixture(tmp_path)
    repo = tmp_path / "source"
    command("git", "update-ref", "refs/ci-verification/head", base, cwd=repo)
    command("git", "bundle", "create", str(bundle),
            "refs/ci-verification/base", "refs/ci-verification/head", cwd=repo)
    result = restore(tmp_path, archive(tmp_path, bundle, manifest), base, head)
    assert result.returncode == 2
    assert "advertised refs" in result.stdout


def test_rejects_zip_slip_and_additional_members(tmp_path: Path) -> None:
    bundle, base, head, manifest = fixture(tmp_path)
    artifact = archive(tmp_path, bundle, manifest, extra={"../evil": b"evil"})
    result = restore(tmp_path, artifact, base, head)
    assert result.returncode == 2
    assert "exactly" in result.stdout
    assert not (tmp_path / "evil").exists()


def test_rejects_existing_checkout_without_overwriting(tmp_path: Path) -> None:
    bundle, base, _head, manifest = fixture(tmp_path)
    checkout = tmp_path / "restored.git"
    checkout.mkdir()
    sentinel = checkout / "keep.txt"
    sentinel.write_text("do not touch", encoding="utf-8")
    result = restore(tmp_path, archive(tmp_path, bundle, manifest), base, head)
    assert result.returncode == 2
    assert sentinel.read_text(encoding="utf-8") == "do not touch"


def test_rejects_wrong_trusted_head_independent_of_manifest(tmp_path: Path) -> None:
    bundle, base, head, manifest = fixture(tmp_path)
    result = restore(tmp_path, archive(tmp_path, bundle, manifest), base, "c" * 40)
    assert result.returncode == 2
    assert "headSha" in result.stdout


def test_rejects_unexpected_bundle_format(tmp_path: Path) -> None:
    _bundle, base, head, manifest = fixture(tmp_path)
    artifact = tmp_path / "artifact.zip"
    with zipfile.ZipFile(artifact, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("repository.bundle", "not-a-git-bundle")
    result = restore(tmp_path, artifact, base, head)
    assert result.returncode == 2
    assert "bundle" in result.stdout
