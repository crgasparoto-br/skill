from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_repo_write_must_end_through_terminal_identity_barrier() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    validator = (ROOT / "scripts" / "validate_terminal_handoff.py").read_text(encoding="utf-8")
    assert "barreira universal pos-escrita" in skill
    assert "last_material_write_sha" in terminal
    assert "post-write-refreeze" in terminal
    assert "current_head != published_handoff_head_sha" in terminal
    assert "nenhum retorno pode contornar reconciliacao terminal de identidade" in terminal
    assert "current remote head moved after handoff publication" in validator
    assert "RECOVERY: post-write-refreeze" in validator
    assert "--current-head-sha" in validator
    assert "--published-head-sha" in validator
    assert "--post-handoff-changed-path" in validator


def test_generic_post_write_refreeze_is_not_ci_specific() -> None:
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    assert "Qualquer mudanca material apos freeze" in terminal
    assert "corrigir-ci" in terminal
    assert "teste, documentacao ou formatacao" in terminal


def test_foreign_target_handoff_is_rejected_before_reuse() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    target = (ROOT / "references" / "delivery-target-binding.md").read_text(encoding="utf-8")
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    assert "artifact_reuse.status=current-target" in skill
    assert "foreign-target" in skill
    assert "zero reuso" in target.lower()
    assert "fresh-handoff-required" in terminal
    assert "handoff-only" in terminal


def test_independent_audit_recovery_scope_is_a_floor_not_a_hint() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    connector = (ROOT / "references" / "connector-only-handoff.md").read_text(encoding="utf-8")
    classifier = (ROOT / "scripts" / "classify_handoff_recovery.py").read_text(encoding="utf-8")
    assert "piso de recuperacao" in skill
    assert "material_dirty_since_freeze" in skill
    assert "handoff-stale` **nao seleciona fast path sozinho**" in skill
    assert "Precedencia da decisao de recovery" in terminal
    assert "lower bound" in terminal
    assert "nao inferir `handoff-only` apenas pelo motivo textual" in connector
    assert "--auditor-recovery-scope" in classifier
    assert "--auditor-requires-refreeze" in classifier
    assert "auditor-recovery-floor:post-write-refreeze" in classifier
