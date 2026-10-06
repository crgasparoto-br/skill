from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_core_work_is_internal_and_external_skills_are_conditional():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    planner = (ROOT / "scripts/plan_execution.py").read_text(encoding="utf-8")
    assert "nunca invocar skill que nao apareca nele" in skill
    assert "internal_plan" in planner
    assert "'stage': 'implementation'" in planner
    assert "'stage': 'hygiene'" in planner
    assert "mode='guidance'" in planner
    assert "phase='pre-implementation'" in planner
    assert "internal-verification" in planner
    assert "design-interface (guidance)" in skill
    assert "design-interface (verify)" in skill


def test_schema_requires_contract_version():
    schema = (ROOT / "schemas/subskill-result.schema.json").read_text(encoding="utf-8")
    assert '"contract_version"' in schema
    assert '"2026-08-20.3"' in schema
