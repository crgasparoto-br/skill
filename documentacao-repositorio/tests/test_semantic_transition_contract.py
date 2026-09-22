from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_normative_policy_changes_trigger_repository_wide_contradiction_scan() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    scan = (ROOT / "references" / "contradiction-scan.md").read_text(encoding="utf-8")
    impact = (ROOT / "references" / "impact-record.md").read_text(encoding="utf-8")
    assert "autorizacao" in skill and "default" in skill and "trigger" in skill
    assert "DOC-SEMANTIC-DRIFT-001" in scan
    assert "linguagem normativa" in scan
    assert "unresolved_contradictions=[]" in scan
    assert "autorizacao/permissao/capability" in impact
