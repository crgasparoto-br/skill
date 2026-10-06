from __future__ import annotations

import shutil
from pathlib import Path

from scripts.validate_reachability import unreachable_files, validate_reachability

ROOT = Path(__file__).resolve().parents[1]


def make_skill(tmp_path: Path) -> Path:
    skill = tmp_path / "demo"
    (skill / "references").mkdir(parents=True)
    (skill / "scripts" / "pkg").mkdir(parents=True)
    (skill / "SKILL.md").write_text("Ler `references/guide.md` e executar `scripts/run.py`.\n", encoding="utf-8")
    (skill / "references" / "guide.md").write_text("Detalhe em [extra.md](extra.md).\n", encoding="utf-8")
    (skill / "references" / "extra.md").write_text("fim\n", encoding="utf-8")
    (skill / "scripts" / "run.py").write_text("from helper import value\nfrom pkg.inner import other\n", encoding="utf-8")
    (skill / "scripts" / "helper.py").write_text("value = 1\n", encoding="utf-8")
    (skill / "scripts" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (skill / "scripts" / "pkg" / "inner.py").write_text("other = 2\n", encoding="utf-8")
    return skill


def test_repository_has_no_unreachable_operational_files() -> None:
    assert validate_reachability(ROOT) == []


def test_links_and_imports_make_files_reachable(tmp_path: Path) -> None:
    assert unreachable_files(make_skill(tmp_path)) == []


def test_orphan_reference_and_script_are_reported(tmp_path: Path) -> None:
    skill = make_skill(tmp_path)
    (skill / "references" / "stale.md").write_text("regra antiga\n", encoding="utf-8")
    (skill / "scripts" / "legacy.py").write_text("print('x')\n", encoding="utf-8")
    names = {path.name for path in unreachable_files(skill)}
    assert names == {"stale.md", "legacy.py"}


def test_file_named_only_by_an_orphan_is_still_unreachable(tmp_path: Path) -> None:
    skill = make_skill(tmp_path)
    (skill / "references" / "stale.md").write_text("Executar `scripts/legacy.py`.\n", encoding="utf-8")
    (skill / "scripts" / "legacy.py").write_text("print('x')\n", encoding="utf-8")
    assert {path.name for path in unreachable_files(skill)} == {"stale.md", "legacy.py"}


def test_generated_caches_are_ignored(tmp_path: Path) -> None:
    skill = make_skill(tmp_path)
    cache = skill / "scripts" / "__pycache__"
    cache.mkdir()
    shutil.copy(skill / "scripts" / "helper.py", cache / "helper.cpython-311.pyc")
    assert unreachable_files(skill) == []
