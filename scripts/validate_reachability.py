#!/usr/bin/env python3
"""Fail when a skill ships references, scripts or schemas that its SKILL.md never reaches.

An operational file is reachable when it is named (path or file name) by SKILL.md,
agents/openai.yaml or another reachable file, or imported by a reachable Python
script. Unreachable files are dead weight for an AI: they are never loaded, drift
silently and invite contradictory instructions. contracts/ is governed by
sync_contracts.py; assets/ and tests/ are not instructions.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

try:
    from .catalog import ROOT, catalog_skill_ids, load_catalog
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT, catalog_skill_ids, load_catalog

CHECKED_DIRS = ("references", "scripts", "schemas")
ENTRYPOINTS = ("SKILL.md", "agents/openai.yaml")
TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".sh"}
NAME_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:md|py|json|ya?ml|sh)\b")
IMPORT_RE = re.compile(r"^\s*(?:from\s+(\.?[\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)


def _operational_files(skill_dir: Path) -> set[Path]:
    files: set[Path] = set()
    for name in CHECKED_DIRS:
        base = skill_dir / name
        if base.is_dir():
            files.update(
                path for path in base.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}
            )
    return files


def _resolve_names(text: str, current: Path, skill_dir: Path, by_name: dict[str, set[Path]]) -> set[Path]:
    found: set[Path] = set()
    for raw_token in NAME_RE.findall(text):
        token = raw_token.strip("./") if raw_token.startswith("./") else raw_token
        for base in (current.parent, skill_dir):
            candidate = (base / token).resolve()
            if candidate.is_file():
                found.add(candidate)
        found.update(by_name.get(Path(token).name, set()))
    return found


def _resolve_imports(text: str, current: Path, skill_dir: Path) -> set[Path]:
    found: set[Path] = set()
    scripts = skill_dir / "scripts"
    for absolute, plain in IMPORT_RE.findall(text):
        module = absolute or plain
        base = current.parent if module.startswith(".") else scripts
        parts = module.lstrip(".").split(".")
        for size in range(len(parts), 0, -1):
            stem = base.joinpath(*parts[:size])
            for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
                if candidate.is_file():
                    found.add(candidate.resolve())
    return found


def unreachable_files(skill_dir: Path) -> list[Path]:
    skill_dir = skill_dir.resolve()
    operational = {path.resolve() for path in _operational_files(skill_dir)}
    by_name: dict[str, set[Path]] = {}
    for path in operational:
        by_name.setdefault(path.name, set()).add(path)
    seen: set[Path] = set()
    stack = [(skill_dir / entry).resolve() for entry in ENTRYPOINTS]
    while stack:
        current = stack.pop()
        if current in seen or not current.is_file() or current.suffix not in TEXT_SUFFIXES:
            continue
        seen.add(current)
        text = current.read_text(encoding="utf-8")
        stack.extend(_resolve_names(text, current, skill_dir, by_name) - seen)
        if current.suffix == ".py":
            stack.extend(_resolve_imports(text, current, skill_dir) - seen)
    return sorted(operational - seen)


def validate_reachability(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for skill_id in sorted(catalog_skill_ids(load_catalog(root))):
        skill_dir = root / skill_id
        for path in unreachable_files(skill_dir):
            errors.append(f"{path.relative_to(skill_dir.resolve()).as_posix()} in {skill_id} is not reachable from SKILL.md; link it where it applies or delete it")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate_reachability(args.root.resolve())
    if errors:
        print("Reachability validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Reachability validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
