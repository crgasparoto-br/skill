"""Adversarial bootstrap for the first rejected review without a prior same-target ledger."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from audit_artifact_io import pack_json_artifact  # noqa: E402 - CLI test loads script modules via their own search path
from verify_first_audit_escape import prove_first_audit_escape  # noqa: E402 - CLI test loads script modules via their own search path

REPO = "owner/repo"


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo: Path, content: str) -> str:
    (repo / "README.md").write_text(content, encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", content)
    return git(repo, "rev-parse", "HEAD")


def fixture_repo(tmp_path: Path, *, old_root: dict | None = None,
                 issue_ledger: bool = False, shard: bool = False) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    root = repo / ".audit/entregar-issue"
    root.mkdir(parents=True)
    if old_root is not None:
        file = root / "audit-escape-closure.json"
        file.write_text(json.dumps(old_root), encoding="utf-8")
        if shard:
            pack_json_artifact(file, force=True)
    if issue_ledger:
        scoped = root / "issue-42/audit-escape-closure.json"
        scoped.parent.mkdir()
        scoped.write_text('{"escapes": [{"escape_id": "EARLIER"}]}', encoding="utf-8")
    audited = commit(repo, "audited")
    material = commit(repo, "fixed")
    source = tmp_path / "audit-source-result.json"
    source.write_text(json.dumps({
        "status": "rejected", "head_sha": audited,
        "identity": {"head_sha": audited, "repository": REPO,
                     "issue_number": 42, "pull_request_number": 99},
        "rejection_id": "audit-rejection:first-001",
    }), encoding="utf-8")
    return {"repo": repo, "audited": audited, "material": material, "source": source}


def proof(case: dict, **overrides):
    args = {
        "repository": case["repo"], "audited_sha": case["audited"],
        "material_sha": case["material"], "repository_name": REPO,
        "issue_number": 42, "pull_request_number": 99, "audit_result": case["source"],
    }
    return prove_first_audit_escape(**(args | overrides))


def test_first_rejection_without_ledger_is_proven_by_git(tmp_path):
    case = fixture_repo(tmp_path)
    receipt = proof(case)
    assert receipt["status"] == "absent-proved-on-target"
    assert receipt["reference_sha"] == case["audited"]
    assert set(receipt["absent_paths"]) == {
        ".audit/entregar-issue/audit-escape-closure.json",
        ".audit/entregar-issue/issue-42/audit-escape-closure.json",
    }


def test_sharded_global_ledger_for_another_target_cannot_be_reused(tmp_path):
    foreign = {"subject": {"repository": REPO, "issue_number": 40,
                            "pull_request_number": 80, "material_head_sha": "a" * 40},
               "escapes": [{"escape_id": "FOREIGN"}]}
    case = fixture_repo(tmp_path, old_root=foreign, shard=True)
    receipt = proof(case)
    assert receipt["foreign_target_paths"] == [".audit/entregar-issue/audit-escape-closure.json"]
    assert receipt["absent_paths"] == [".audit/entregar-issue/issue-42/audit-escape-closure.json"]


@pytest.mark.parametrize("subject", [
    {"repository": REPO, "issue_number": 42, "pull_request_number": 99},
    {"repository": REPO, "issue_number": 42, "pull_request_number": 100},
    {"repository": "forged/repo", "issue_number": 40, "pull_request_number": 80},
    {},
])
def test_existing_or_unverifiable_root_ledger_rejects_bootstrap(tmp_path, subject):
    case = fixture_repo(tmp_path, old_root={"subject": subject, "escapes": []})
    with pytest.raises(ValueError):
        proof(case)


def test_existing_issue_ledger_must_be_preserved_not_bootstrapped(tmp_path):
    case = fixture_repo(tmp_path, issue_ledger=True)
    with pytest.raises(ValueError, match="snapshot required"):
        proof(case)


@pytest.mark.parametrize("field,value", [
    ("head_sha", "b" * 40), ("status", "approved"),
    ("rejection_id", ""),
])
def test_audit_source_cannot_be_substituted(tmp_path, field, value):
    case = fixture_repo(tmp_path)
    source = json.loads(case["source"].read_text())
    source[field] = value
    case["source"].write_text(json.dumps(source))
    with pytest.raises(ValueError):
        proof(case)


@pytest.mark.parametrize("target", [
    {"repository_name": "forged/repo"}, {"issue_number": 41},
    {"pull_request_number": 100}, {"audited_sha": "0" * 40},
    {"material_sha": "0" * 40},
])
def test_wrong_identity_or_unknown_git_object_never_proves_absence(tmp_path, target):
    case = fixture_repo(tmp_path)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        proof(case, **target)


def test_removed_issue_ledger_after_audit_is_not_absence(tmp_path):
    case = fixture_repo(tmp_path)
    current = case["repo"] / ".audit/entregar-issue/issue-42/audit-escape-closure.json"
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text('{"escapes": [{"escape_id":"HISTORY"}]}')
    case["material"] = commit(case["repo"], "added-ledger")
    with pytest.raises(ValueError, match="snapshot required"):
        proof(case)


def test_missing_checkout_or_source_does_not_become_false_negative(tmp_path):
    case = fixture_repo(tmp_path)
    with pytest.raises(ValueError, match="requires Git checkout"):
        proof(case, repository=tmp_path / "missing")
    with pytest.raises(ValueError, match="requires Git checkout"):
        proof(case, audit_result=tmp_path / "missing.json")


def test_intermediate_issue_ledger_created_then_deleted_still_blocks(tmp_path):
    case = fixture_repo(tmp_path)
    ledger = case["repo"] / ".audit/entregar-issue/issue-42/audit-escape-closure.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('{"escapes": [{"escape_id":"HISTORY"}]}')
    commit(case["repo"], "history-created")
    ledger.unlink()
    case["material"] = commit(case["repo"], "history-deleted")
    with pytest.raises(ValueError, match="snapshot required"):
        proof(case)


def test_intermediate_root_ledger_created_then_deleted_still_blocks(tmp_path):
    case = fixture_repo(tmp_path)
    root = case["repo"] / ".audit/entregar-issue/audit-escape-closure.json"
    root.write_text(json.dumps({
        "subject": {"repository": REPO, "issue_number": 42,
                    "pull_request_number": 99, "material_head_sha": "a" * 40},
        "escapes": [{"escape_id": "HISTORY"}],
    }))
    commit(case["repo"], "root-created")
    root.unlink()
    case["material"] = commit(case["repo"], "root-deleted")
    with pytest.raises(ValueError, match="snapshot required"):
        proof(case)


def test_parent_git_symlink_fails_closed(tmp_path):
    case = fixture_repo(tmp_path)
    path = case["repo"] / ".audit/entregar-issue/issue-42/audit-escape-closure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to("/tmp/untrusted")
    case["material"] = commit(case["repo"], "symlink")
    with pytest.raises(ValueError, match="unsafe Git type"):
        proof(case)
