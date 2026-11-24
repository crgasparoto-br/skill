from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

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


def test_selection_states_are_defined_by_the_local_design_system() -> None:
    standards = (ROOT / "references/interface-standards.md").read_text(encoding="utf-8")
    audit = (ROOT / "references/visual-audit.md").read_text(encoding="utf-8")
    assert "segundo os componentes locais" in audit
    assert "conforme o design system do projeto" in standards
    assert "alternativas equivalentes devem ter o **mesmo estilo neutro**" not in standards.casefold()
    assert "iniciem neutras" not in audit.casefold()


def test_project_rules_are_owned_by_consumer_repositories() -> None:
    spec = (ROOT.parent / "docs/SKILL_SYSTEM_SPEC.md").read_text(encoding="utf-8")
    agents = (ROOT.parent / "AGENTS.md").read_text(encoding="utf-8")
    standards = (ROOT / "references/interface-standards.md").read_text(encoding="utf-8")
    assert "### 4.12 Portabilidade e propriedade das regras por projeto" in spec
    assert "repositorio consumidor" in spec
    assert "As regras normativas do catalogo devem ser portaveis" in agents
    assert "pertencem exclusivamente ao repositorio consumidor" in standards


# Scenario-matrix tests constrain the decisions, not merely keyword presence.
# Rendering and generative behavior need separate evidence under visual-audit.md.
_EXPECTED_DIRECTION_CASES = {
    "DS-CONFLITO": ("aprovado", "tema-conflitante", "preservar-tokens", "substituir-tokens"),
    "DS-LACUNA": (
        "aprovado-parcial",
        "tema-opcional",
        "preservar-tokens-e-completar-lacuna",
        "alterar-token-aprovado",
    ),
    "COMPONENTE": (
        "componente-nao-aprovado",
        "referencia-estetica",
        "reutilizar-implementacao-e-registrar-nao-aprovacao",
        "declarar-aprovacao",
    ),
    "SEM-REDE": ("sem-fonte-local", "offline", "defaults-acessiveis-ou-sem-tema", "exigir-rede"),
    "CONTRASTE": (
        "sem-fonte-local",
        "tema-baixo-contraste",
        "rejeitar-tema-e-manter-contraste-e-foco",
        "reduzir-contraste-ou-foco",
    ),
}


def _direction_cases(source: str) -> dict[str, tuple[str, str, str, str]]:
    section = source.split("## Casos verificáveis", 1)[1].split("\n## ", 1)[0]
    rows = [row for row in section.splitlines() if row.startswith("| ")]
    assert [cell.strip() for cell in rows[0].strip("|").split("|")] == [
        "ID", "Contexto local", "Referência", "Aceitar", "Rejeitar"
    ]
    assert rows[1].startswith("| ---")
    parsed = {}
    for row in rows[2:]:
        cells = tuple(cell.strip() for cell in row.strip("|").split("|"))
        assert len(cells) == 5 and cells[0] not in parsed
        parsed[cells[0]] = cells[1:]
    return parsed


def _cases_match_contract(cases: dict[str, tuple[str, str, str, str]]) -> bool:
    return cases == _EXPECTED_DIRECTION_CASES


def test_visual_direction_is_reachable_only_as_gap_fallback() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    standards = (ROOT / "references/interface-standards.md").read_text(encoding="utf-8")
    reference = ROOT / "references/visual-direction.md"
    assert reference.is_file()
    assert "references/visual-direction.md" in skill
    assert "depois de identificar uma lacuna visual relevante" in standards
    assert "visual-direction.md" in standards
    content = reference.read_text(encoding="utf-8")
    assert "somente se a descoberta e a precedência" in content
    assert "04977e15f3dfd6ee4b74c887dac3eb52665d6c92" in content


def test_visual_direction_cases_cover_positive_and_negative_controls() -> None:
    cases = _direction_cases((ROOT / "references/visual-direction.md").read_text(encoding="utf-8"))
    assert _cases_match_contract(cases)
    assert all(accepted != rejected for _, _, accepted, rejected in cases.values())
    assert cases["DS-LACUNA"][2] == "preservar-tokens-e-completar-lacuna"
    assert cases["COMPONENTE"][3] == "declarar-aprovacao"
    assert cases["SEM-REDE"][2] == "defaults-acessiveis-ou-sem-tema"
    assert cases["CONTRASTE"][2] == "rejeitar-tema-e-manter-contraste-e-foco"


# The entire reviewed normative reference is guarded, not just the example table.
# Changing its bytes requires deliberate policy review and updating this baseline
# in the same commit; the digest is not evidence of an agent's runtime behavior.
_DIRECTION_POLICY_SHA256 = "3ac61f013abdcf89deae6d166c3d289f886c344a651cdd0561a75766172b181f"


def _assert_direction_contract(source: str) -> None:
    assert _cases_match_contract(_direction_cases(source)), "direction scenario contract changed"
    assert sha256(source.encode("utf-8")).hexdigest() == _DIRECTION_POLICY_SHA256, (
        "normative direction changed outside the reviewed policy; rederive and review the contract"
    )


def test_visual_direction_normative_contract_is_reviewed_in_full() -> None:
    source = (ROOT / "references/visual-direction.md").read_text(encoding="utf-8")
    _assert_direction_contract(source)


@pytest.mark.parametrize(
    ("anchor", "contradiction"),
    [
        pytest.param(
            "## Decidir sem deslocar fontes locais\n",
            "**Regra contraditória intencional:** quando um tema externo conflitar com "
            "design system aprovado, substituir os tokens locais pelo tema externo.",
            id="approved-token-override-outside-matrix",
        ),
        pytest.param(
            "## Decidir sem deslocar fontes locais\n",
            "**Regra contraditória intencional:** componentes não documentados são oficialmente aprovados.",
            id="false-component-approval-outside-matrix",
        ),
        pytest.param(
            "## Completar somente o que falta\n",
            "Aplicar os tokens externos também às propriedades já cobertas por padrões locais.",
            id="partial-gap-overrides-covered-property",
        ),
        pytest.param(
            "## Fonte externa e registro\n",
            "Na falta de rede, interromper a entrega até acessar a referência externa.",
            id="offline-dependency",
        ),
        pytest.param(
            "## Famílias opcionais\n",
            "Uma escolha estética pode dispensar contraste, foco visível e segurança.",
            id="inaccessible-theme-exception",
        ),
    ],
)
def test_visual_direction_rejects_contradictory_normative_prose(
    anchor: str, contradiction: str
) -> None:
    source = (ROOT / "references/visual-direction.md").read_text(encoding="utf-8")
    _assert_direction_contract(source)
    assert source.count(anchor) == 1
    mutant = source.replace(anchor, f"{anchor}\n{contradiction}\n", 1)
    assert mutant != source
    # Reproduce the audit escape: the original table oracle is still green.
    assert _cases_match_contract(_direction_cases(mutant))
    # The same complete-document oracle used on the real reference must reject it.
    with pytest.raises(AssertionError, match="normative direction changed"):
        _assert_direction_contract(mutant)


@pytest.mark.parametrize(
    "case_id",
    _EXPECTED_DIRECTION_CASES,
)
def test_visual_direction_rejects_wrong_decision_in_source(case_id: str) -> None:
    source = (ROOT / "references/visual-direction.md").read_text(encoding="utf-8")
    _assert_direction_contract(source)
    context, external, accepted, rejected = _EXPECTED_DIRECTION_CASES[case_id]
    original = f"| {case_id} | {context} | {external} | {accepted} | {rejected} |"
    wrong = f"| {case_id} | {context} | {external} | {rejected} | {rejected} |"
    assert source.count(original) == 1
    mutant = source.replace(original, wrong, 1)
    with pytest.raises(AssertionError, match="direction scenario contract changed"):
        _assert_direction_contract(mutant)


def test_visual_direction_rejects_missing_offline_case_in_source() -> None:
    source = (ROOT / "references/visual-direction.md").read_text(encoding="utf-8")
    _assert_direction_contract(source)
    mutant = "\n".join(line for line in source.split("\n") if not line.startswith("| SEM-REDE |"))
    with pytest.raises(AssertionError, match="direction scenario contract changed"):
        _assert_direction_contract(mutant)
