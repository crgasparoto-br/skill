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
