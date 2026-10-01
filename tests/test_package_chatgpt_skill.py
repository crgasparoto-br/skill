from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "package_chatgpt_skill.py"

spec = importlib.util.spec_from_file_location("package_chatgpt_skill", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_entregar_issue_runtime_resource_closure() -> None:
    assert module.validate_skill_runtime(ROOT / "entregar-issue") == []


def test_packager_rejects_missing_referenced_script(tmp_path: Path) -> None:
    skill = tmp_path / "demo"
    (skill / "agents").mkdir(parents=True)
    (skill / "references").mkdir()
    (skill / "scripts").mkdir()
    (skill / "SKILL.md").write_text("---\nname: demo\ndescription: demo\n---\nRun scripts/missing.py.\n", encoding="utf-8")
    (skill / "agents" / "openai.yaml").write_text("interface:\n  display_name: Demo\n", encoding="utf-8")
    errors = module.validate_skill_runtime(skill)
    assert any("scripts/missing.py" in error for error in errors)


def test_packager_ignores_explicit_cross_skill_script_reference(tmp_path: Path) -> None:
    skill = tmp_path / "demo"
    (skill / "agents").mkdir(parents=True)
    (skill / "references").mkdir()
    (skill / "scripts").mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: demo\n---\n"
        "External: python <auditar-issue>/scripts/generate_auditor_keypair.py\n",
        encoding="utf-8",
    )
    (skill / "agents" / "openai.yaml").write_text(
        "interface:\n  display_name: Demo\n",
        encoding="utf-8",
    )
    assert module.validate_skill_runtime(skill) == []


def test_packager_preserves_terminal_runtime_files(tmp_path: Path) -> None:
    output = tmp_path / "skill.zip"
    errors = module.package(ROOT / "entregar-issue", output)
    assert errors == []
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
    for rel in module.ENTREGAR_REQUIRED:
        assert f"entregar-issue/{rel}" in names
