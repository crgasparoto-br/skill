from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "references"


def read_reference(name: str) -> str:
    return (REFERENCES / name).read_text(encoding="utf-8")


def test_blocker_harvest_requires_material_surface_coverage_not_a_finding_count() -> None:
    policy = read_reference("blocker-harvest.md")
    assert "requisito -> familia -> superficie -> dimensoes de ataque" in policy
    assert "nao impor teto de findings" in policy
    assert "Duas falhas iniciais nao encerram a busca" in policy
    assert "covered" in policy and "not-applicable" in policy and "not-executed" in policy
    assert "reprovada com colheita abrangente" in policy
    assert "reprovada com cobertura limitada" in policy
    assert "reaudit-readiness.md" in policy
    assert "provas caras" in policy


def test_detector_attacks_cross_real_dataflow_axes_and_negative_controls() -> None:
    design = read_reference("adversarial-control-design.md")
    for axis in ("Origem", "Identidade e escopo", "Transformacao", "Fluxo",
                 "Consumo", "Fronteira"):
        assert "| " + axis + " |" in design
    assert "transformacao x consumo" in design
    assert "origem x escopo" in design
    assert "controle negativo" in design
    assert "static-inference" in design


def test_report_exposes_coverage_and_test_status_without_false_exhaustiveness() -> None:
    report = read_reference("report-template.md")
    checklist = read_reference("audit-checklist.md")
    assert "### Cobertura e saturacao adversarial" in report
    assert "Familia / superficie" in report
    assert "Cobertura declarada" in report
    assert "Superficies remanescentes" in report
    assert "preflight-bounded" in report
    assert "matriz de saturacao" in checklist
    assert "controles baratos restantes" in checklist
    assert "cobertura limitada como exaustiva" in checklist
