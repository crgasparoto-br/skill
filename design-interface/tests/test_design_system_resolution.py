from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_local_precedence_keeps_fallback_last() -> None:
    standards = (ROOT / "references/interface-standards.md").read_text(encoding="utf-8")
    section = standards.split("## Descoberta e precedencia por solucao", 1)[1]
    section = section.split("## Hierarquia", 1)[0]
    levels = [
        "**Padroes locais aprovados**",
        "**Componentes locais executaveis**",
        "**Telas correlatas da mesma solucao**",
        "**Defaults genericos desta skill**",
    ]
    positions = [section.index(level) for level in levels]
    assert positions == sorted(positions)
    assert "sem padrao local identificado" in section
    assert "referencia e **implementada**, nao oficialmente aprovada" in section


def test_conflicts_are_recorded_instead_of_silently_overridden() -> None:
    standards = (ROOT / "references/interface-standards.md").read_text(encoding="utf-8")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    audit = (ROOT / "references/visual-audit.md").read_text(encoding="utf-8")
    assert "Em conflito entre documentacao aprovada" in standards
    assert "fontes locais, precedencia, conflitos e defaults" in skill
    assert "registrar lacunas, conflitos e defaults usados" in audit


def test_solverfin_rules_remain_conditional_on_repository() -> None:
    standards = (ROOT / "references/interface-standards.md").read_text(encoding="utf-8")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    audit = (ROOT / "references/visual-audit.md").read_text(encoding="utf-8")
    assert "so valem no proprio SolverFin" in standards
    assert "No SolverFin, consultar" in skill
    assert "nao importar Golden Screen ou tokens especificos de outro produto" in audit
