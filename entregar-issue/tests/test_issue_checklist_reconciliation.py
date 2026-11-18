"""Fail-closed tests for offline issue-checkbox reconciliation."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_issue_checkboxes.py"
SPEC = importlib.util.spec_from_file_location("reconcile_issue_checkboxes", MODULE)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)
SHA = "a" * 40

BODY = (
    "## Objetivo\n\nPreservar comportamento.\n\n"
    "## Critérios de aceite\n\n"
    "- [ ] Um\n- [x] Dois\n- Tres\n\n"
    "## Riscos\n\n- [ ] Fora do escopo\n"
)


def audit(*statuses: str, body: str = BODY) -> dict:
    items = mod.analyze_body(body)[1]
    assert len(statuses) == len(items)
    return {
        "validity": "independent",
        "subject_sha": SHA,
        "audit_url": "https://github.com/example/repo/pull/1#review",
        "criteria": [
            {
                "ordinal": item["ordinal"],
                "text": item["text"],
                "status": status,
                "evidence": ["test:case; sha=" + SHA] if status in {"verified", "failed", "partial"} else [],
            }
            for item, status in zip(items, statuses, strict=True)
        ],
    }


def test_mark_verified_unmark_failed_and_preserve_other_sections() -> None:
    result, summary = mod.reconcile(BODY, BODY, audit("verified", "failed", "verified"), SHA)
    assert "- [x] Um\n- [ ] Dois\n- [x] Tres\n" in result
    assert "## Riscos\n\n- [ ] Fora do escopo" in result
    assert len(summary["changes"]) == 3
    assert summary["warnings"] == []


def test_idempotence_and_checkbox_only_concurrent_updates() -> None:
    decisions = audit("verified", "failed", "verified")
    first, _ = mod.reconcile(BODY, BODY, decisions, SHA)
    again, summary = mod.reconcile(BODY, first, decisions, SHA)
    assert first == again
    assert not summary["changes"]


@pytest.mark.parametrize(
    "changed",
    [
        BODY.replace("Um", "Um alterado"),
        BODY.replace("Preservar comportamento.", "Novo escopo."),
        BODY.replace("- Tres", "- Tres\n- Quatro"),
    ],
)
def test_reject_material_issue_drift(changed: str) -> None:
    with pytest.raises(ValueError, match="changed"):
        mod.reconcile(BODY, changed, audit("verified", "failed", "verified"), SHA)


def test_reject_missing_or_untrusted_decisions() -> None:
    with pytest.raises(ValueError, match="Every criterion"):
        mod.reconcile(BODY, BODY, {"validity": "independent", "subject_sha": SHA, "audit_url": "https://example.com/audit", "criteria": []}, SHA)
    with pytest.raises(ValueError, match="review/attestation"):
        mod.reconcile(BODY, BODY, {**audit("verified", "failed", "verified"), "validity": "pre-audit"}, SHA)
    with pytest.raises(ValueError, match="evidence"):
        records = audit("verified", "failed", "verified")
        records["criteria"][0]["evidence"] = []
        mod.reconcile(BODY, BODY, records, SHA)


def test_reject_stale_sha_and_identity_swap() -> None:
    with pytest.raises(ValueError, match="SHA"):
        mod.reconcile(BODY, BODY, audit("verified", "failed", "verified"), "b" * 40)
    records = audit("verified", "failed", "verified")
    records["criteria"][1]["text"] = "Um"
    with pytest.raises(ValueError, match="identity"):
        mod.reconcile(BODY, BODY, records, SHA)


def test_solo_attestation_is_allowed_without_claiming_independence() -> None:
    records = {**audit("verified", "failed", "verified"), "validity": "solo-context-attested"}
    result, summary = mod.reconcile(BODY, BODY, records, SHA)
    assert len(summary["changes"]) == 3
    assert "- [x] Um" in result


def test_reopen_checked_criteria_without_verified_evidence() -> None:
    result, summary = mod.reconcile(BODY, BODY, audit("unknown", "unknown", "not-applicable"), SHA)
    assert result == BODY.replace("- [x] Dois", "- [ ] Dois")
    assert len(summary["changes"]) == 1
    assert summary["warnings"] == ["Criterion 2 reopened: no verified evidence"]


def test_duplicate_items_use_order_not_text_search() -> None:
    duplicate = "## Critérios de aceite\n- [ ] Igual\n- [ ] Igual\n"
    records = audit("verified", "failed", body=duplicate)
    result, summary = mod.reconcile(duplicate, duplicate, records, SHA)
    assert result.endswith("- [x] Igual\n- [ ] Igual\n")
    assert len(summary["changes"]) == 1


def test_ignore_fenced_examples_and_require_single_section() -> None:
    body = "## Critérios de aceite\n\n~~~md\n- [ ] Exemplo\n~~~\n- [ ] Real\n"
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Real"]
    with pytest.raises(ValueError, match="exactly one"):
        mod.analyze_body("## Contexto\n- [ ] Sem criterios\n")
