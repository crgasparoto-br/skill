from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_delivery_prefers_original_pr_for_result_only_recovery() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    recovery = (ROOT / "references" / "result-only-pr-recovery.md").read_text(encoding="utf-8")
    assert "preservar a pr original" in skill.lower()
    assert "validate_result_only_pr_recovery.py" in skill
    assert "replacement_pr_budget=1" in skill
    assert "prepublication" in terminal.lower() or "pre-publicacao" in terminal.lower()
    assert "force apenas no ref" in recovery
    assert "Nao abrir uma segunda PR substituta automaticamente" in recovery


def test_force_exception_cannot_rewrite_material_history() -> None:
    recovery = (ROOT / "references" / "result-only-pr-recovery.md").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "validate_result_only_pr_recovery.py").read_text(encoding="utf-8")
    assert "nunca para reescrever material" in recovery
    assert "current-child-contains-material-paths" in validator
    assert "candidate-contains-material-paths" in validator
    assert "candidate-parent-differs-from-material" in validator
