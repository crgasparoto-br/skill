from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_audit_emits_reusable_escape_controls_and_sibling_sweep() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ref = (ROOT / "references" / "audit-escape-feedback.md").read_text(encoding="utf-8")

    assert "escape-control.json" in skill
    assert "audit_escape" in skill
    assert "ao menos dois casos irmaos" in ref
    assert "TEMP-ASOF-001" in ref
    assert "RESTART-IDEM-001" in ref
    assert "mesmo entrypoint publico" in ref
    assert "sem GET/health-check/operacao auxiliar" in ref


def test_blocker_harvest_saturates_material_surfaces_not_finding_count() -> None:
    policy = (ROOT / "references" / "blocker-harvest.md").read_text(encoding="utf-8")
    assert "requisito -> familia -> superficie -> dimensoes de ataque" in policy
    assert "nao impor teto de findings" in policy
    assert "Duas falhas iniciais nao encerram a busca" in policy
    assert all(status in policy for status in ("covered", "not-applicable", "not-executed"))
    assert "reprovada com colheita abrangente" in policy
    assert "reprovada com cobertura limitada" in policy
    assert "reaudit-readiness.md" in policy


def test_detector_audit_crosses_semantic_axes_and_negative_controls() -> None:
    design = (ROOT / "references" / "adversarial-control-design.md").read_text(encoding="utf-8")
    for axis in ("Origem", "Identidade e escopo", "Transformacao", "Fluxo", "Consumo", "Fronteira"):
        assert "| " + axis + " |" in design
    assert "origem x escopo" in design
    assert "transformacao x consumo" in design
    assert "controle negativo" in design
    assert "static-inference" in design


def test_audit_report_declares_adversarial_coverage_and_residual_risk() -> None:
    report = (ROOT / "references" / "report-template.md").read_text(encoding="utf-8")
    checklist = (ROOT / "references" / "audit-checklist.md").read_text(encoding="utf-8")
    assert "### Cobertura e saturacao adversarial" in report
    assert "Familia / superficie" in report
    assert "Cobertura declarada" in report
    assert "Superficies remanescentes" in report
    assert "preflight-bounded" in report
    assert "matriz de saturacao" in checklist
    assert "controles baratos restantes" in checklist
    assert "cobertura limitada como exaustiva" in checklist
