from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_skill_shifts_evidence_to_effect_scope_left():
    skill = read("SKILL.md")
    workflow = read("references/implementation-workflow.md")
    adversarial = read("references/controller-adversarial-evidence.md")
    gate = read("references/evidence-effect-scope-gate.md")
    catalog = read("references/audit-escape-pattern-catalog.md")

    assert "evidence-effect-scope-gate.md" in skill
    assert "authorization:evidence-effect-scope" in skill
    assert "AUTH-EFFECT-SCOPE-001" in skill
    assert "branch emergencial/override/excecao" in gate.lower()

    assert "effect_b" in workflow
    assert "ausencia de linha, evento, timestamp, outbound ou estado parcial" in workflow
    assert "Evidencia que restringe efeito posterior" in adversarial
    assert "deliberadamente separar" in adversarial

    assert "Presenca de evidencia valida nao substitui" in gate
    assert "pedido misto" in gate
    assert "branch emergencial/override/excecao" in gate
    assert "evidence-effect-scope-gap" in catalog


def test_authorization_gate_preserves_scope_in_exception_branches():
    text = read("references/persistence-authorization-gates.md")
    assert "Escopo de evidencia para efeito" in text
    assert "AUTH-EFFECT-SCOPE-001" in text
    assert "branch emergencial/override/excecao" in text
    assert "ausencia de mutacao" in text
