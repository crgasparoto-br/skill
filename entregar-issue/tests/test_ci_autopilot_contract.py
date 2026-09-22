from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_delivery_never_returns_only_because_ci_is_pending():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    remote = (ROOT / "references" / "remote-gate.md").read_text(encoding="utf-8")
    result = (ROOT / "references" / "controller-result-template.md").read_text(encoding="utf-8")
    assert "nunca e motivo para devolver o controle ao usuario" in skill
    assert "nao responder com pendencia remota" in remote
    assert "limite-atingido-com-pendencias" not in result


def test_delivery_delegates_ci_wait_and_failure_to_corrigir_ci():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    composition = (ROOT / "references" / "composition-contract.md").read_text(encoding="utf-8")
    assert "CI autopilot" in skill
    assert "ci-remediation-loop" in skill
    assert "completed/failure" in skill
    assert "durante a fase remota do ciclo principal" in composition
    assert "nao manter `delivery-snapshot` ativo em paralelo" in composition


def test_ci_fix_returns_to_refreeze_before_final_handoff():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    assert "material_dirty_since_freeze" in skill
    assert "post-write-refreeze" in skill
    assert "CI material verde" in terminal
