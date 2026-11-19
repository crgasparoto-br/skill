"""Exact Git-object tests for trusted-base native audit transport selection."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve_trusted_audit_transport.py"
POLICY_PATH = "docs/audit/github-native-contract.json"


def git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def policy(**changes) -> dict:
    data = {
        "schema_version": 1,
        "repository": "owner/repository",
        "base_ref": "develop",
        "canonical": True,
        "audit_mode": "native-github",
        "legacy_handoff_policy": "not-required",
        "github_native_identity": True,
        "exact_sha_evidence": True,
        "independent_review": True,
        "remote_ci_evidence": True,
        "review_assurance": "operator-attested-session-review",
    }
    data.update(changes)
    return data


def repository(tmp_path: Path, initial: dict | None = None) -> tuple[Path, str]:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-b", "develop")
    git(root, "config", "user.name", "Example Operator")
    git(root, "config", "user.email", "operator@example.invalid")
    (root / "README.md").write_text("trusted\n", encoding="utf-8")
    if initial is not None:
        source = root / POLICY_PATH
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps(initial) + "\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "trusted base")
    return root, git(root, "rev-parse", "HEAD")


def commit_file(root: Path, name: str, text: str) -> str:
    source = root / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    git(root, "add", name)
    git(root, "commit", "-m", f"material change: {name}")
    return git(root, "rev-parse", "HEAD")


def run(root: Path, base: str, head: str, **options):
    command = [
        sys.executable, str(SCRIPT), "--root", str(root),
        "--repository", options.get("repository", "owner/repository"),
        "--base-ref", options.get("base_ref", "develop"),
        "--base-sha", options.get("base_sha", base),
        "--head-sha", options.get("head_sha", head),
    ]
    return subprocess.run(command, text=True, capture_output=True, check=False)


def test_native_contract_from_immutable_trusted_base_passes(tmp_path):
    root, base = repository(tmp_path, policy())
    head = commit_file(root, "feature.txt", "new feature\n")
    outcome = run(root, base, head)
    assert outcome.returncode == 0, outcome.stderr
    result = json.loads(outcome.stdout)
    assert result["mode"] == "native-github-audit"
    assert result["legacy_handoff_required"] is False
    assert result["trusted_anchor_sha"] == base
    assert result["material_head_sha"] == head
    raw = subprocess.run(["git", "show", f"{base}:{POLICY_PATH}"], cwd=root,
                         check=True, capture_output=True).stdout
    assert result["contract"]["source_sha256"] == hashlib.sha256(raw).hexdigest()


def test_candidate_cannot_install_own_native_exemption(tmp_path):
    root, base = repository(tmp_path)
    head = commit_file(root, POLICY_PATH, json.dumps(policy()) + "\n")
    outcome = run(root, base, head)
    assert outcome.returncode == 0, outcome.stderr
    result = json.loads(outcome.stdout)
    assert result["mode"] == "certified-handoff"
    assert result["contract"] is None


def test_missing_contract_remains_legacy_without_false_success(tmp_path):
    root, base = repository(tmp_path)
    head = commit_file(root, "feature.txt", "change\n")
    result = json.loads(run(root, base, head).stdout)
    assert result["mode"] == "certified-handoff"
    assert result["legacy_handoff_required"] is True


def test_candidate_modified_contract_cannot_rewrite_trusted_bytes(tmp_path):
    root, base = repository(tmp_path, policy())
    head = commit_file(root, POLICY_PATH, json.dumps(policy(independent_review=False)) + "\n")
    outcome = run(root, base, head)
    assert outcome.returncode == 0, outcome.stderr
    result = json.loads(outcome.stdout)
    assert result["mode"] == "native-github-audit"
    assert result["contract"]["source_git_blob_sha"] == git(root, "rev-parse", f"{base}:{POLICY_PATH}")


@pytest.mark.parametrize("overrides", [
    {"repository": "attacker/repository"},
    {"base_ref": "main"},
    {"canonical": False},
    {"independent_review": False},
    {"exact_sha_evidence": False},
    {"remote_ci_evidence": False},
    {"review_assurance": "third-party-cryptographic"},
    {"legacy_handoff_policy": "optional"},
    {"schema_version": 2},
])
def test_invalid_trusted_contract_fails_closed(tmp_path, overrides):
    root, base = repository(tmp_path, policy(**overrides))
    head = commit_file(root, "feature.txt", "change\n")
    outcome = run(root, base, head)
    assert outcome.returncode == 2
    assert "BLOCK:" in outcome.stderr


def test_extra_unreviewed_policy_field_fails_closed(tmp_path):
    root, base = repository(tmp_path, policy(candidate_may_override=True))
    head = commit_file(root, "feature.txt", "change\n")
    assert run(root, base, head).returncode == 2


def test_symlink_does_not_become_a_canonical_contract(tmp_path):
    root, _base = repository(tmp_path)
    path = root / POLICY_PATH
    path.parent.mkdir(parents=True)
    path.symlink_to("../../README.md")
    git(root, "add", POLICY_PATH)
    git(root, "commit", "-m", "symbolic link in base")
    linked_base = git(root, "rev-parse", "HEAD")
    head = commit_file(root, "feature.txt", "change\n")
    outcome = run(root, linked_base, head)
    assert outcome.returncode == 2
    assert "regular Git blob" in outcome.stderr


@pytest.mark.parametrize("key", ["base_sha", "head_sha"])
def test_unavailable_or_fake_git_object_fails_closed(tmp_path, key):
    root, base = repository(tmp_path, policy())
    head = commit_file(root, "feature.txt", "change\n")
    outcome = run(root, base, head, **{key: "f" * 40})
    assert outcome.returncode == 2


def test_material_checkout_must_match_authenticated_head(tmp_path):
    root, base = repository(tmp_path, policy())
    head = commit_file(root, "feature.txt", "change\n")
    outcome = run(root, base, head, head_sha=base)
    assert outcome.returncode == 2
    assert "checkout HEAD" in outcome.stderr


def test_trusted_base_must_be_ancestor_of_material_head(tmp_path):
    root, base = repository(tmp_path, policy())
    head = commit_file(root, "feature.txt", "change\n")
    git(root, "checkout", "-b", "unrelated", base)
    other = commit_file(root, "other.txt", "change\n")
    git(root, "checkout", "develop")
    outcome = run(root, other, head)
    assert outcome.returncode == 2


def test_main_release_cannot_be_treated_as_develop_issue(tmp_path):
    root, base = repository(tmp_path, policy())
    head = commit_file(root, "feature.txt", "change\n")
    assert run(root, base, head, base_ref="main").returncode == 2


def test_duplicate_json_key_in_trusted_base_fails_closed(tmp_path):
    root, base = repository(tmp_path)
    contract = root / POLICY_PATH
    contract.parent.mkdir(parents=True, exist_ok=True)
    duplicate = json.dumps(policy())
    duplicate = duplicate.replace('"canonical": true,', '"canonical": true, "canonical": false,')
    contract.write_text(duplicate + "\n", encoding="utf-8")
    git(root, "add", POLICY_PATH)
    git(root, "commit", "-m", "ambiguous trusted policy")
    linked_base = git(root, "rev-parse", "HEAD")
    head = commit_file(root, "feature.txt", "change\n")
    outcome = run(root, linked_base, head)
    assert outcome.returncode == 2
    assert "duplicate trusted native contract" in outcome.stderr


def test_oversized_trusted_policy_fails_closed(tmp_path):
    root, _base = repository(tmp_path)
    contract = root / POLICY_PATH
    contract.parent.mkdir(parents=True, exist_ok=True)
    contract.write_text(json.dumps(policy()) + " " * 17000, encoding="utf-8")
    git(root, "add", POLICY_PATH)
    git(root, "commit", "-m", "oversized trusted contract")
    linked_base = git(root, "rev-parse", "HEAD")
    head = commit_file(root, "feature.txt", "change\n")
    outcome = run(root, linked_base, head)
    assert outcome.returncode == 2
    assert "size budget" in outcome.stderr
