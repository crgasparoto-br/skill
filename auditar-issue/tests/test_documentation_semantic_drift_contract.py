from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_independent_audit_scans_normative_policy_drift_beyond_routes_and_names() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    design = (ROOT / "references" / "adversarial-control-design.md").read_text(encoding="utf-8")
    rules = (ROOT / "references" / "evidence-rules.md").read_text(encoding="utf-8")
    assert "autorizacao/role/permissao/capability" in skill
    assert "default/preset" in skill and "provisionamento/trigger" in skill
    assert "DOC-SEMANTIC-DRIFT-001" in design
    assert "mudanca semantica normativa" in rules
