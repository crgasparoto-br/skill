from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_implementation_shifts_discriminating_controls_before_final_gate():
    skill = read("SKILL.md")
    workflow = read("references/implementation-workflow.md")
    efficiency = read("references/controller-execution-efficiency.md")

    assert "Antes da primeira edicao material" in skill
    assert "controle negativo primario por `risk_family + surface`" in skill
    assert "reconciliacao pos-diff" in skill
    assert "nao deve ser a primeira etapa a descobrir ataque barato" in skill

    assert "definir antes da primeira edicao" in workflow
    assert "Reconciliar risco pelo diff" in workflow
    assert "controle negativo discriminante primario para cada `risk_family + surface`" in workflow
    assert "Nenhum requisito segue ao gate final com superficie material conhecida sem controle focado executado" in workflow

    assert "auditoria independente como primeira descoberta de ataque barato" in efficiency
    assert "O gate final confirma saturacao, nao substitui o shift-left" in efficiency


def test_post_diff_reconciliation_does_not_replan_the_delivery():
    skill = read("SKILL.md")
    workflow = read("references/implementation-workflow.md")
    efficiency = read("references/controller-execution-efficiency.md")

    assert "sem recalcular o plano inteiro" in skill
    assert "nao recalcular readiness, plano ou requisitos ja estaveis" in workflow
    assert "nao recalcular o plano nem reabrir requisitos estaveis" in efficiency
