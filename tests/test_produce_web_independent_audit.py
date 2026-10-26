"""Fail-closed tests for the GitHub-hosted independent audit producer."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "produce_web_independent_audit.py"
spec = importlib.util.spec_from_file_location("web_audit_producer", SCRIPT)
assert spec is not None and spec.loader is not None
producer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producer)

HEAD = "a" * 40
BASE = "b" * 40
PREVIEW = "c" * 40


def packet():
    return {
        "repository": "org/repo", "issue_number": 9, "pr_number": 10,
        "head_sha": HEAD, "base_sha": BASE,
        "merge_preview_sha": PREVIEW, "base_ref": "develop",
    }


def fake_checks(*, fail=None):
    names = [
        "Structure and tests",
        "Offline authorization tests",
        "collect / Require certified semantic handoff (exact SHA)",
    ]
    return {
        "total_count": len(names),
        "check_runs": [
            {
                "id": i + 1, "name": name, "head_sha": HEAD,
                "status": "completed", "conclusion": "failure" if name == fail else "success",
                "app": {"id": 15368},
            }
            for i, name in enumerate(names)
        ],
    }


def test_technical_checks_require_exact_sha_and_success(monkeypatch):
    monkeypatch.setattr(producer, "github", lambda *_: fake_checks())
    producer.verify_technical_checks(packet(), "token")
    monkeypatch.setattr(producer, "github", lambda *_: fake_checks(fail="Structure and tests"))
    with pytest.raises(ValueError, match="not green"):
        producer.verify_technical_checks(packet(), "token")


def test_technical_checks_reject_forged_app(monkeypatch):
    checks = fake_checks()
    checks["check_runs"][0]["app"]["id"] = 55555
    monkeypatch.setattr(producer, "github", lambda *_: checks)
    with pytest.raises(ValueError, match="missing trusted"):
        producer.verify_technical_checks(packet(), "token")


def test_technical_checks_reject_truncated_inventory(monkeypatch):
    checks = fake_checks()
    checks["total_count"] = 50
    monkeypatch.setattr(producer, "github", lambda *_: checks)
    with pytest.raises(ValueError, match="truncated"):
        producer.verify_technical_checks(packet(), "token")


def test_model_approval_requires_evidence():
    with pytest.raises(ValueError, match="no evidence"):
        producer.build_report(
            packet(),
            {"verdict": "approved", "findings": [], "limitations": [], "evidence": []},
            "github-actions:12", "github-actions-source:10",
        )


def test_model_rejection_never_generates_approved_report():
    with pytest.raises(ValueError, match="rejected"):
        producer.build_report(
            packet(),
            {"verdict": "rejected", "findings": [{"id": "A1"}],
             "limitations": [], "evidence": [{"id": "EV1", "claim": "x", "source": "file"}]},
            "github-actions:12", "github-actions-source:10",
        )


def test_approved_report_binds_independent_run_and_target():
    report = producer.build_report(
        packet(),
        {"verdict": "approved", "findings": [], "limitations": [],
         "evidence": [{
             "id": "EV1",
             "claim": "Canonical requirement is covered by negative assertion",
             "source": "tests/test_feature.py",
         }]},
        "github-actions:12", "github-actions-source:10",
    )
    assert report["head_sha"] == report["head_sha_after"] == HEAD
    assert report["merge_preview_sha_after"] == PREVIEW
    assert report["audit_context_id"] == "github-actions:12"
    assert report["implementation_context_id"] == "github-actions-source:10"
    assert "signature" not in report  # Signing only occurs in the isolated trusted runner.
    assert report["verdict"] == "approved"


def test_canonical_issue_and_patch_are_required(monkeypatch):
    pr = {
        "state": "open", "base": {"ref": "develop", "sha": BASE},
        "head": {"sha": HEAD, "repo": {"full_name": "org/repo"}},
        "merge_commit_sha": PREVIEW,
    }
    issue = {"title": "Issue", "body": "Verify explicit binding"}
    def github(repo, suffix, token):
        return pr if suffix == "pulls/10" else issue
    monkeypatch.setattr(producer, "github", github)
    monkeypatch.setattr(producer, "get_all_files", lambda *_: [
        {"filename": "src/validator.py", "status": "modified", "patch": ""}
    ])
    with pytest.raises(ValueError, match="missing full textual patch"):
        producer.build_packet("org/repo", 10, 9, "token")


def test_canonical_coverage_must_have_real_source_excerpt():
    p = packet() | {
        "issue_body": "## Acceptance\n1. Secure signing\n2. Reject forged report",
        "changed_files": ["scripts/verify.py"],
    }
    response = {
        "verdict": "approved", "findings": [], "limitations": [],
        "evidence": [{
            "id": "EV1", "claim": "The SHA check rejects mismatch.",
            "source": "scripts/verify.py", "excerpt": "raise ValueError('sha mismatch')",
        }],
        "requirement_coverage": [
            {"id": "REQ-1", "evidence_ids": ["EV1"]},
            {"id": "REQ-2", "evidence_ids": ["EV1"]},
        ],
    }
    source = "FILE scripts/verify.py\nraise ValueError('sha mismatch')"
    producer.validate_model_coverage(response, p, source)
    response["evidence"][0]["excerpt"] = "assert True # fabricated proof"
    with pytest.raises(ValueError, match="not grounded"):
        producer.validate_model_coverage(response, p, source)


def test_missing_requirement_binding_must_fail_closed():
    p = packet() | {
        "issue_body": "1. One\n2. Two\n3. Three",
        "changed_files": ["scripts/verify.py"],
    }
    response = {
        "verdict": "approved", "findings": [], "limitations": [],
        "evidence": [{
            "id": "EV1", "claim": "A source line shows check",
            "source": "scripts/verify.py", "excerpt": "raise ValueError('sha mismatch')",
        }],
        "requirement_coverage": [
            {"id": "REQ-1", "evidence_ids": ["EV1"]},
            {"id": "REQ-2", "evidence_ids": ["EV1"]},
        ],
    }
    with pytest.raises(ValueError, match="every canonical requirement"):
        producer.validate_model_coverage(response, p, "raise ValueError('sha mismatch')")
