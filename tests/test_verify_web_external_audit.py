"""Adversarial exact-target tests for signed web-audit gating."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "verify_web_external_audit.py"
spec = importlib.util.spec_from_file_location("web_audit_gate", MODULE)
assert spec and spec.loader
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
HEAD = "a" * 40
BASE = "b" * 40


def valid_report():
    return {
        "repository": "crgasparoto-br/skill",
        "issue": 125,
        "base_ref": "develop",
        "head_sha": HEAD,
        "head_sha_after": HEAD,
        "base_sha": BASE,
        "base_sha_after": BASE,
        "verdict": "approved",
        "findings": [],
        "recommendations": [],
        "limitations": [],
        "independent": True,
        "same_conversation": False,
        "implementation_context_id": "implementation-123",
        "audit_context_id": "independent-audit-456",
        "source_context_proof": {"value": "independent-audit-456", "issuer": "trusted-auditor"},
        "neutral_packet": {
            "implementation_conclusions_included": False,
            "implementation_narrative_included": False,
        },
    }


def check(report):
    return gate.check_binding(
        report, repository="crgasparoto-br/skill", issue=125,
        base_ref="develop", base_sha=BASE, head_sha=HEAD,
    )


def test_accepts_exact_target_after_signature_verification():
    assert check(valid_report()) == []


@pytest.mark.parametrize("field,value", [
    ("repository", "other/repo"),
    ("issue", 126),
    ("base_ref", "main"),
    ("base_sha", "c" * 40),
    ("base_sha_after", "c" * 40),
    ("head_sha", "c" * 40),
    ("head_sha_after", "c" * 40),
    ("verdict", "approved-with-reservations"),
    ("verdict", "rejected"),
    ("findings", [{"id": "A-001"}]),
    ("recommendations", ["change policy"]),
    ("limitations", ["missing test"]),
    ("independent", False),
    ("same_conversation", True),
    ("audit_context_id", "implementation-123"),
])
def test_rejects_wrong_binding_or_claims(field, value):
    report = copy.deepcopy(valid_report())
    report[field] = value
    assert check(report), field


@pytest.mark.parametrize("field", [
    "implementation_conclusions_included",
    "implementation_narrative_included",
])
def test_rejects_contaminated_neutral_packet(field):
    report = valid_report()
    report["neutral_packet"][field] = True
    assert check(report)


def test_rejects_missing_neutral_packet():
    report = valid_report()
    del report["neutral_packet"]
    assert check(report)


def test_requires_exact_40_character_sha():
    assert gate.SHA.fullmatch(HEAD)
    assert not gate.SHA.fullmatch("b" * 39)
    assert not gate.SHA.fullmatch(HEAD + "malicious")


def test_merge_preview_binding_accepts_exact_sha():
    assert gate.check_binding(valid_report() | {
        "merge_preview_sha": "c" * 40,
        "merge_preview_sha_after": "c" * 40,
    }, repository="crgasparoto-br/skill", issue=125, base_ref="develop",
        base_sha=BASE, head_sha=HEAD, merge_preview_sha="c" * 40) == []


@pytest.mark.parametrize("field", ["merge_preview_sha", "merge_preview_sha_after"])
def test_merge_preview_binding_rejects_stale_snapshot(field):
    report = valid_report() | {
        "merge_preview_sha": "c" * 40,
        "merge_preview_sha_after": "c" * 40,
    }
    report[field] = "d" * 40
    assert gate.check_binding(report, repository="crgasparoto-br/skill",
        issue=125, base_ref="develop", base_sha=BASE, head_sha=HEAD,
        merge_preview_sha="c" * 40)


def test_context_proof_must_match_and_have_expected_issuer():
    report = valid_report()
    assert gate.check_binding(report, repository="crgasparoto-br/skill", issue=125,
        base_ref="develop", base_sha=BASE, head_sha=HEAD,
        context_proof_issuer="trusted-auditor") == []
    report["source_context_proof"]["issuer"] = "implementation"
    assert gate.check_binding(report, repository="crgasparoto-br/skill", issue=125,
        base_ref="develop", base_sha=BASE, head_sha=HEAD,
        context_proof_issuer="trusted-auditor")
    report["source_context_proof"]["value"] = "fabricated-context"
    assert check(report)


def solo_report():
    report = valid_report()
    report.update({
        "assurance_mode": "single-operator-separate-context",
        "independent": False,
        "merge_preview_sha": "c" * 40,
        "merge_preview_sha_after": "c" * 40,
        "pull_request": 176,
        "operator_github_id": 12345,
        "issue_body_sha256": "d" * 64,
        "signature": {"key_id": "solo-key-1"},
    })
    return report


def check_solo(report, **overrides):
    values = {
        "repository": "crgasparoto-br/skill",
        "issue": 125,
        "base_ref": "develop",
        "base_sha": BASE,
        "head_sha": HEAD,
        "merge_preview_sha": "c" * 40,
        "solo_only": True,
        "expected_pull_request": 176,
        "expected_issue_body_sha256": "d" * 64,
        "configured_operator_id": 12345,
        "configured_key_id": "solo-key-1",
        "authenticated_comment_author_id": 12345,
    }
    values.update(overrides)
    return gate.check_binding(report, **values)


def test_solo_binding_accepts_exact_report_and_authenticated_identity():
    assert check_solo(solo_report()) == []


@pytest.mark.parametrize("change", [
    lambda report: report.update(pull_request=177),
    lambda report: report.update(issue_body_sha256="e" * 64),
    lambda report: report.update(operator_github_id=54321),
    lambda report: report.update(signature={"key_id": "other-key"}),
])
def test_solo_binding_rejects_report_identity_changes(change):
    report = solo_report()
    change(report)
    assert check_solo(report)


def test_solo_binding_rejects_authenticated_comment_author_mismatch():
    assert check_solo(solo_report(), authenticated_comment_author_id=54321)


def test_legacy_binding_does_not_activate_solo_checks_by_default():
    report = valid_report()
    report["pull_request"] = 176
    report["operator_github_id"] = 12345
    report["issue_body_sha256"] = "d" * 64
    assert check(report) == []
