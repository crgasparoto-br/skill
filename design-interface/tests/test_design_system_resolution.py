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


def test_normative_guidance_has_no_consumer_specific_visual_rules() -> None:
    sources = [ROOT / "SKILL.md", *sorted((ROOT / "references").glob("*.md"))]
    content = "\n".join(path.read_text(encoding="utf-8") for path in sources).casefold()
    # Negative regression for previously leaked, product-owned references.
    forbidden = (
        "solver" + "fin",
        "--" + "sf-",
        "docs/golden_" + "statement.md",
        'data-button-variant="neutral"',
        "/lanca" + "mentos",
    )
    for token in forbidden:
        assert token not in content


def test_project_rules_are_owned_by_consumer_repositories() -> None:
    spec = (ROOT.parent / "docs/SKILL_SYSTEM_SPEC.md").read_text(encoding="utf-8")
    agents = (ROOT.parent / "AGENTS.md").read_text(encoding="utf-8")
    standards = (ROOT / "references/interface-standards.md").read_text(encoding="utf-8")
    assert "### 4.12 Portabilidade e propriedade das regras por projeto" in spec
    assert "repositorio consumidor" in spec
    assert "As regras normativas do catalogo devem ser portaveis" in agents
    assert "pertencem exclusivamente ao repositorio consumidor" in standards
