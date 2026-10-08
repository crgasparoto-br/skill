"""Testes do contrato executavel de handoff de release."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_handoff import build_report, load_json, markdown_report

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/release-handoff.json").read_text(encoding="utf-8"))
DEVELOP = "c" * 40
MAIN = "d" * 40


def evidence(
    *,
    audit: str = "approved",
    develop: str = DEVELOP,
    main: str = MAIN,
    drop: str = "",
    extra: bool = False,
) -> dict:
    """Evidencia sintetica, com os desvios pedidos pelo teste."""
    items = {
        "issues-delivered": {"value": "45", "source": "github"},
        "develop-sha": {"value": develop, "source": "git"},
        "gates": {"value": "ok", "source": "local"},
        "independent-audit": {"value": audit, "source": "auditar-issue"},
        "divergence": {"value": "sim", "source": "git"},
    }
    if drop:
        items.pop(drop)
    if extra:
        items["surpresa"] = {"value": "x", "source": "manual"}
    return {"schema_version": 1, "main": main, "items": items}


def report_for(document: dict, develop: str = DEVELOP, main: str = MAIN) -> dict:
    """Relatorio para a evidencia informada."""
    return build_report(POLICY, document, {"develop": develop, "main": main})


def test_policy_declares_required_evidence_with_reason() -> None:
    """Cada item obrigatorio precisa de descricao e motivo declarados."""
    required = POLICY["required"]
    assert {item["id"] for item in required} >= {
        "issues-delivered",
        "develop-sha",
        "gates",
        "independent-audit",
        "divergence",
    }
    for item in required:
        assert item["description"].strip()
        assert item["reason"].strip()


def test_contract_does_not_hold_merge_authority() -> None:
    """O contrato nao pode declarar autoridade de merge, tag ou publicacao."""
    authority = POLICY["authority"]
    assert authority["merges"] is False
    assert authority["tags"] is False
    assert authority["publishes"] is False


def test_contract_source_has_no_forbidden_command() -> None:
    """O contrato nao pode invocar merge, tag, publicacao ou escrita em git."""
    text = (ROOT / "scripts/release_handoff.py").read_text(encoding="utf-8")
    for command in ("gh pr merge", "gh release", "git push", "git tag", "git merge", "git commit"):
        assert command not in text


def test_complete_evidence_is_approved() -> None:
    """Evidencia completa e valida aprova o handoff."""
    report = report_for(evidence())
    assert report["ready"] is True
    assert report["problems"] == []
    assert [row["id"] for row in report["items"]] == [item["id"] for item in POLICY["required"]]


def test_missing_required_item_is_rejected() -> None:
    """Item obrigatorio sem evidencia reprova o handoff."""
    report = report_for(evidence(drop="gates"))
    assert report["ready"] is False
    assert any("gates" in problem and "sem evidencia" in problem for problem in report["problems"])


def test_unapproved_audit_is_rejected() -> None:
    """Parecer de auditoria fora da lista aprovada reprova o handoff."""
    report = report_for(evidence(audit="rejected"))
    assert report["ready"] is False
    assert any("nao esta aprovado" in problem for problem in report["problems"])


def test_equal_develop_and_main_is_rejected() -> None:
    """`develop` igual a `main` significa que nao ha release a promover."""
    report = report_for(evidence(main=DEVELOP), develop=DEVELOP, main=DEVELOP)
    assert report["ready"] is False
    assert any("mesmo commit" in problem for problem in report["problems"])


def test_invalid_sha_is_rejected() -> None:
    """Commit que nao e hexadecimal de 40 caracteres reprova o handoff."""
    document = evidence(develop="nao-e-sha")
    report = report_for(document, develop="nao-e-sha")
    assert report["ready"] is False
    assert any("hexadecimal" in problem for problem in report["problems"])


def test_unknown_evidence_identifier_is_rejected() -> None:
    """Identificador de evidencia desconhecido reprova o handoff."""
    report = report_for(evidence(extra=True))
    assert report["ready"] is False
    assert any("desconhecido" in problem for problem in report["problems"])


def test_evidence_from_another_commit_is_rejected() -> None:
    """A evidencia precisa apontar o commit de `develop` informado."""
    report = report_for(evidence(), develop="e" * 40)
    assert report["ready"] is False
    assert any("diferente do informado" in problem for problem in report["problems"])


def test_report_is_deterministic_and_marked() -> None:
    """A mesma entrada produz a mesma saida, e o relatorio marca cada item."""
    first = markdown_report(report_for(evidence()))
    second = markdown_report(report_for(evidence()))
    assert first == second
    for item in POLICY["required"]:
        assert f"`{item['id']}`" in first
    assert "nao pronto" not in first


def test_invalid_evidence_file_fails_closed(tmp_path: Path) -> None:
    """Evidencia ausente ou invalida falha fechado, sem aprovar em silencio."""
    broken = tmp_path / "evidence.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(SystemExit):
        load_json(broken)
