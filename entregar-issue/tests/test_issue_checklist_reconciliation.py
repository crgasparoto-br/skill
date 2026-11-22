"""Fail-closed tests for offline issue-checkbox reconciliation."""

from __future__ import annotations

import importlib.util
import json
import sys
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
                "original_checked": item["checked"],
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


def test_reject_audit_snapshot_checkbox_mismatch() -> None:
    records = audit("verified", "partial", "unknown")
    records["criteria"][1]["original_checked"] = False
    with pytest.raises(ValueError, match="identity"):
        mod.reconcile(BODY, BODY, records, SHA)


def test_longer_fence_keeps_shorter_markers_and_examples_inert() -> None:
    fence = chr(96) * 4
    shorter = chr(96) * 3
    body = (
        "## Critérios de aceite\n"
        "- [ ] Primeiro\n"
        f"{fence}markdown\n{shorter}\n"
        "- [ ] Exemplo inerte\n"
        f"{fence}\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]
    result, _ = mod.reconcile(body, body, audit("verified", "verified", body=body), SHA)
    assert "- [x] Primeiro\n" in result
    assert "- [ ] Exemplo inerte\n" in result
    assert "- [x] Segundo\n" in result


def test_html_comment_in_fenced_example_does_not_hide_real_criteria() -> None:
    fence = chr(96) * 4
    shorter = chr(96) * 3
    body = (
        "## Critérios de aceite\n"
        "- [ ] Primeiro\n"
        f"{fence}md\n"
        "<!--\n"
        f"{shorter}\n"
        "- [ ] Exemplo inerte\n"
        f"{fence}\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]


def test_fence_close_requires_matching_length_and_no_info_string() -> None:
    body = (
        "## Critérios de aceite\n"
        "~~~~markdown\n"
        "~~~\n"
        "- [ ] Exemplo inerte\n"
        "~~~~\n"
        "- [ ] Real\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Real"]


def test_acceptance_heading_with_closing_hashes() -> None:
    body = "## Critérios de aceite ##\n- [ ] Real\n"
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Real"]


def test_fenced_markers_inside_html_comment_do_not_hide_real_criteria() -> None:
    fence = chr(96) * 3
    body = (
        "## Critérios de aceite\n"
        "- [ ] Primeiro\n"
        "<!-- exemplo inerte\n"
        f"{fence}md\n"
        "- [ ] Item dentro do comentário\n"
        "-->\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]


@pytest.mark.parametrize("indent", ["\t", "  \t"])
def test_tab_indented_child_is_a_real_nested_list_item(indent: str) -> None:
    # CommonMark tabs indented after a parent list marker are child items.
    body = (
        "## Critérios de aceite\n"
        "- [ ] Pai\n"
        f"{indent}- [ ] Filho\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == [
        "Pai", "Filho", "Segundo",
    ]
    proposed, summary = mod.reconcile(
        body, body, audit("verified", "verified", "unknown", body=body), SHA,
    )
    assert f"{indent}- [x] Filho\n" in proposed
    assert summary["criteria_total"] == 3


@pytest.mark.parametrize("indent", ["\t", "  \t", "    "])
def test_indented_code_outside_list_is_not_a_criterion(indent: str) -> None:
    body = (
        "## Critérios de aceite\n"
        f"{indent}- [ ] Inerte em código\n"
        "- [ ] Real\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Real"]


@pytest.mark.parametrize("tag", ["pre", "script", "style", "textarea"])
def test_raw_html_block_is_inert(tag: str) -> None:
    body = (
        "## Critérios de aceite\n"
        f"<{tag}>\n"
        "- [ ] Exemplo inerte\n"
        f"</{tag}>\n"
        "- [ ] Critério real\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Critério real"]


@pytest.mark.parametrize("opening", ["~~~md\n", "<!-- exemplo\n", "<pre>\n"])
def test_unterminated_inert_block_fails_closed(opening: str) -> None:
    body = "## Critérios de aceite\n- [ ] Real\n" + opening + "- [ ] Inerte\n"
    with pytest.raises(ValueError, match="Unterminated"):
        mod.analyze_body(body)


def test_indented_acceptance_heading_is_recognized() -> None:
    body = "  ## Critérios de aceite ###\n- [ ] Real\n"
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Real"]

@pytest.mark.parametrize("tag", ["div", "details", "section", "custom-panel"])
def test_html_blocks_do_not_inject_fake_headings_or_acceptance_items(tag: str) -> None:
    # CommonMark type 6 (standard tags) and type 7 (custom tags) are inert.
    body = (
        "## Critérios de aceite\n"
        "- [ ] Primeiro\n"
        f"<{tag}>\n"
        "## Cabeçalho de exemplo\n"
        "- [ ] Falso\n"
        f"</{tag}>\n"
        "\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]
    result, summary = mod.reconcile(body, body, audit("verified", "verified", body=body), SHA)
    assert "- [x] Primeiro\n" in result
    assert "- [ ] Falso\n" in result
    assert "- [x] Segundo\n" in result
    assert len(summary["changes"]) == 2


def test_standard_html_block_stays_inert_until_blank_line() -> None:
    body = (
        "## Critérios de aceite\n"
        "- [ ] Primeiro\n"
        "<div>\n"
        "- [ ] Exemplo\n"
        "</div>\n"
        "- [ ] Ainda inerte\n"
        "\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]


@pytest.mark.parametrize(
    ("opening", "closing"),
    [("<?demo\n", "?>\n"), ("<![CDATA[\n", "]]>\n"), ("<!DOCTYPE html\n", ">\n")],
)
def test_other_multiline_html_inert_blocks_do_not_inject_items(
    opening: str, closing: str
) -> None:
    body = "## Critérios de aceite\n" + opening + "- [ ] Falso\n" + closing + "- [ ] Real\n"
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Real"]


@pytest.mark.parametrize("tag", ["custom-panel", "span", "custom-widget"])
def test_type7_tag_cannot_interrupt_an_open_paragraph(tag: str) -> None:
    # CommonMark type-7 HTML does not interrupt a paragraph; a following bullet can.
    body = (
        "## Critérios de aceite\n"
        "- [ ] Primeiro\n"
        "Texto explicativo\n"
        f"<{tag}>\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]
    proposed, summary = mod.reconcile(body, body, audit("verified", "verified", body=body), SHA)
    assert "- [x] Segundo\n" in proposed
    assert len(summary["changes"]) == 2


@pytest.mark.parametrize("marker", ["2.", "2)", "0.", "02."])
def test_non_one_ordered_item_cannot_interrupt_an_open_paragraph(marker: str) -> None:
    # An ordered list interrupts a paragraph only when its start number is one.
    body = (
        "## Critérios de aceite\n"
        "- [ ] Primeiro\n"
        "Texto explicativo\n"
        f"{marker} [ ] Apenas exemplo no parágrafo\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]


def test_one_ordered_item_can_interrupt_an_open_paragraph() -> None:
    body = "## Critérios de aceite\nTexto explicativo\n1. [ ] Critério real\n"
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Critério real"]


def test_type6_html_block_still_interrupts_an_open_paragraph() -> None:
    body = (
        "## Critérios de aceite\n"
        "- [ ] Primeiro\n"
        "Texto explicativo\n"
        "<div>\n"
        "- [ ] Exemplo inerte\n"
        "\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]


def test_ten_digit_ordered_marker_is_not_a_commonmark_list_item() -> None:
    body = (
        "## Critérios de aceite\n"
        "- [ ] Primeiro\n"
        "\n"
        "1234567890. [ ] Não é um critério\n"
        "- [ ] Segundo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]


def test_nine_digit_ordered_marker_can_start_its_own_list() -> None:
    body = "## Critérios de aceite\n\n123456789. [ ] Critério válido\n"
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Critério válido"]


@pytest.mark.parametrize(
    "separator",
    ["- - -\n", "* * *\n", "_ _ _\n", "- \t- \t-   \n", "*  *   *\n", "---\n", "***\n", "___\n"],
)
def test_thematic_breaks_never_become_criteria(separator: str) -> None:
    # CommonMark thematic breaks outrank otherwise plausible list-item markers.
    body = "## Critérios de aceite\n- [ ] Primeiro\n" + separator + "- [ ] Segundo\n"
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Primeiro", "Segundo"]
    proposed, summary = mod.reconcile(body, body, audit("verified", "verified", body=body), SHA)
    assert separator in proposed
    assert "- [x] Primeiro\n" in proposed
    assert "- [x] Segundo\n" in proposed
    assert len(summary["changes"]) == 2


@pytest.mark.parametrize("separator", ["- - -\n", "* * *\n", "_ _ _\n"])
def test_thematic_break_alone_is_not_a_criterion(separator: str) -> None:
    with pytest.raises(ValueError, match="no list items"):
        mod.analyze_body("## Critérios de aceite\n" + separator)


@pytest.mark.parametrize("separator", ["- - -\n", "* * *\n", "_ _ _\n"])
def test_thematic_break_closes_paragraph_before_ordered_list(separator: str) -> None:
    body = "## Critérios de aceite\nTexto explicativo\n" + separator + "2. [ ] Critério real\n"
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Critério real"]
    proposed, _ = mod.reconcile(body, body, audit("verified", body=body), SHA)
    assert "2. [x] Critério real" in proposed
    assert separator in proposed


@pytest.mark.parametrize("digit", ["\u0661", "\u06f2", "\u096a", "\uff12", "\U0001d7d9"])
def test_unicode_numeric_markers_are_not_commonmark_list_items(digit: str) -> None:
    # Python \d matches Unicode, but CommonMark ordered list markers use ASCII 0-9.
    body = "## Critérios de aceite\n\n" + digit + ". [ ] Exemplo inválido\n- [ ] Real\n"
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Real"]
    proposed, _ = mod.reconcile(body, body, audit("verified", body=body), SHA)
    assert digit + ". [ ] Exemplo inválido\n" in proposed
    assert "- [x] Real\n" in proposed



def test_nested_acceptance_items_are_audited_individually() -> None:
    body = (
        "## Critérios de aceite\n"
        "- [ ] Pai\n"
        "    - [ ] Filho com quatro espaços\n"
        "- [ ] Outro\n"
    )
    items = mod.analyze_body(body)[1]
    assert [item["text"] for item in items] == [
        "Pai", "Filho com quatro espaços", "Outro",
    ]
    result, summary = mod.reconcile(
        body, body, audit("verified", "failed", "verified", body=body), SHA,
    )
    assert "- [x] Pai\n" in result
    assert "    - [ ] Filho com quatro espaços\n" in result
    assert "- [x] Outro\n" in result
    assert summary["criteria_total"] == 3


def test_nested_lists_after_blank_line_and_in_ordered_parent() -> None:
    body = (
        "## Critérios de aceite\n"
        "1. [ ] Pai ordenado\n\n"
        "    - [ ] Filho\n"
        "        - [ ] Neto\n"
        "2. [ ] Irmão\n"
    )
    items = mod.analyze_body(body)[1]
    assert [item["text"] for item in items] == [
        "Pai ordenado", "Filho", "Neto", "Irmão",
    ]
    result, summary = mod.reconcile(
        body, body, audit("verified", "verified", "unknown", "verified", body=body), SHA,
    )
    assert "    - [x] Filho\n" in result
    assert "        - [ ] Neto\n" in result
    assert summary["criteria_total"] == 4


def test_indented_code_not_promoted_to_nested_acceptance_criterion() -> None:
    body = (
        "## Critérios de aceite\n"
        "- [ ] Pai\n\n"
        "      - [ ] Dentro de código do pai\n"
        "- [ ] Segundo\n"
        "    - [ ] Filho legítimo\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == [
        "Pai", "Segundo", "Filho legítimo",
    ]
    result, summary = mod.reconcile(
        body, body, audit("verified", "verified", "verified", body=body), SHA,
    )
    assert "      - [ ] Dentro de código do pai\n" in result
    assert "    - [x] Filho legítimo\n" in result
    assert len(summary["changes"]) == 3


def test_orphan_indented_code_is_inert_and_missing_child_decision_blocks() -> None:
    body = (
        "## Critérios de aceite\n"
        "    - [ ] Código órfão\n"
        "- [ ] Pai\n"
        "    - [ ] Filho\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == ["Pai", "Filho"]
    with pytest.raises(ValueError, match="Every criterion"):
        mod.reconcile(body, body, audit("verified", "verified", body=body) | {
            "criteria": audit("verified", "verified", body=body)["criteria"][:1]
        }, SHA)


def test_nested_heading_does_not_terminate_acceptance_section() -> None:
    body = (
        "## Critérios de aceite\n"
        "- [ ] Pai\n"
        "  ## Subtítulo dentro do item\n"
        "    - [ ] Filho\n"
        "- [ ] Outro\n"
    )
    assert [item["text"] for item in mod.analyze_body(body)[1]] == [
        "Pai", "Filho", "Outro",
    ]

def test_remote_readback_accepts_identical_body_and_sha() -> None:
    proposed = BODY.replace("- [ ] Um", "- [x] Um")
    result = mod.check_remote_readback(proposed, proposed, SHA, SHA)
    assert result == {"subject_sha": SHA, "criteria_total": 3,
                      "criteria_checked": 2, "body_match": True}


def test_remote_readback_rejects_race_and_unrelated_changes() -> None:
    proposed = BODY.replace("- [ ] Um", "- [x] Um")
    for actual in (BODY, proposed.replace("Preservar comportamento.", "Modificado."),
                   proposed.replace("- [x] Um", "- [x] Outro")):
        with pytest.raises(ValueError, match="read-back differs"):
            mod.check_remote_readback(proposed, actual, SHA, SHA)


def test_remote_readback_rejects_head_drift_and_malformed_sha() -> None:
    for sha, current in ((SHA, "b" * 40), ("not-a-sha", "not-a-sha")):
        with pytest.raises(ValueError, match="material SHA"):
            mod.check_remote_readback(BODY, BODY, sha, current)

def test_cli_remote_readback_reconciles_and_checks_exact_body_and_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "issue.md"
    decision = tmp_path / "audit.json"
    readback = tmp_path / "remote-body.md"
    out = tmp_path / "proposed.md"
    source.write_text(BODY, encoding="utf-8")
    decision.write_text(json.dumps(audit("verified", "unknown", "unknown")), encoding="utf-8")
    proposed = mod.reconcile(BODY, BODY, audit("verified", "unknown", "unknown"), SHA)[0]
    readback.write_text(proposed, encoding="utf-8")
    arguments = ["prog", "--audited-body", str(source), "--current-body", str(source),
                 "--audit", str(decision), "--material-sha", SHA, "--output", str(out),
                 "--readback-body", str(readback), "--observed-material-sha", SHA]
    monkeypatch.setattr(sys, "argv", arguments)
    assert mod.main() == 0
    assert out.read_text(encoding="utf-8") == proposed
    assert json.loads(capsys.readouterr().out)["remote_readback"]["body_match"] is True

    readback.write_text(BODY, encoding="utf-8")
    out.unlink()
    with pytest.raises(ValueError, match="read-back differs"):
        mod.main()
    assert not out.exists()

    readback.write_text(proposed, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", arguments[:-2])
    with pytest.raises(ValueError, match="both be provided"):
        mod.main()
