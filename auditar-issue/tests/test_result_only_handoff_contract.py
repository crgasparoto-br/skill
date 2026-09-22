from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_auditor_understands_material_and_published_heads() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ref = (ROOT / "references" / "handoff-certificate-preflight.md").read_text(encoding="utf-8")
    assert "material_head_sha" in skill
    assert "published_handoff_head_sha" in skill
    assert "schema v2 `result-only-child`" in skill
    assert "parent(H) == M" in ref
    assert "allowed_paths" in ref


def test_delivery_not_ready_distinguishes_handoff_only_from_material_refreeze() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ref = (ROOT / "references" / "handoff-certificate-preflight.md").read_text(encoding="utf-8")
    for text in (skill, ref):
        assert "return_control_to=entregar-issue" in text
        assert "handoff-not-produced" in text
        assert "handoff-stale" in text
        assert "handoff-only" in text
        assert "post-write-refreeze" in text


def test_pending_ci_does_not_excuse_missing_handoff() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ref = (ROOT / "references" / "handoff-certificate-preflight.md").read_text(encoding="utf-8")
    assert "CI remoto ainda `pending-no-run`" in skill
    assert "CI pendente nao substitui certificado" in ref
    assert "preflight de gates" in ref


def test_green_material_handoff_recovery_resumes_finalize_after_ci() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ref = (ROOT / "references" / "handoff-certificate-preflight.md").read_text(encoding="utf-8")
    report = (ROOT / "references" / "report-template.md").read_text(encoding="utf-8")
    for text in (skill, ref, report):
        assert "next_phase=finalize-after-ci" in text
    assert "auditar-issue` nunca deve chamar `corrigir-ci`" in ref
