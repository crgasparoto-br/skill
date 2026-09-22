from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_delivery_requires_semantic_documentation_drift_gate() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ref = (ROOT / "references" / "documentation-semantic-drift-gate.md").read_text(encoding="utf-8")
    readiness = (ROOT / "scripts" / "validate_handoff_readiness.py").read_text(encoding="utf-8")
    assert "DOC-SEMANTIC-DRIFT-001" in skill
    assert "autorizacao" in ref and "default" in ref and "provision" in ref
    assert "documentation:canonical-claims" in skill
    assert "requirement-attack-matrix lacks documentation risk family" in readiness
