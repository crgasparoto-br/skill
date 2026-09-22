#!/usr/bin/env python3
"""Validate the repository-level invariants of the skills catalog."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = {
    "auditar-issue",
    "corrigir-ci",
    "design-interface",
    "documentacao-repositorio",
    "entregar-issue",
    "fluxos-conversacionais",
    "revisar-issue",
}


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def validate_skill(skill_dir: Path, errors: list[str]) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        fail(f"{skill_dir.name}: SKILL.md ausente", errors)
        return

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        fail(f"{skill_dir.name}: frontmatter YAML ausente", errors)
    if not re.search(r"^---\n.*?\n---\n", content, flags=re.DOTALL):
        fail(f"{skill_dir.name}: frontmatter YAML inválido", errors)

    name_match = re.search(r"^name:\s*([^\n]+)$", content, flags=re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)$", content, flags=re.MULTILINE)
    if not name_match:
        fail(f"{skill_dir.name}: campo name ausente", errors)
    elif name_match.group(1).strip().strip('"') != skill_dir.name:
        fail(f"{skill_dir.name}: name não corresponde ao diretório", errors)
    if not description_match or not description_match.group(1).strip():
        fail(f"{skill_dir.name}: description ausente", errors)
    if len(content.splitlines()) > 500:
        fail(f"{skill_dir.name}: SKILL.md excede 500 linhas", errors)

    version_file = skill_dir / "contracts" / "version.json"
    if not version_file.is_file():
        fail(f"{skill_dir.name}: contracts/version.json ausente", errors)
    else:
        try:
            version = json.loads(version_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"{skill_dir.name}: version.json inválido: {exc}", errors)
        else:
            if version.get("canonical_owner") != "entregar-issue":
                fail(f"{skill_dir.name}: canonical_owner inesperado", errors)
            if version.get("contract_version") != "2026-08-20.3":
                fail(f"{skill_dir.name}: contract_version inesperada", errors)

    for required_dir in ("references", "schemas", "tests"):
        if not (skill_dir / required_dir).is_dir():
            fail(f"{skill_dir.name}: diretório {required_dir}/ ausente", errors)

    manifest = skill_dir / "contracts" / "manifest.json"
    if manifest.is_file():
        try:
            json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"{skill_dir.name}: contracts/manifest.json inválido: {exc}", errors)


def main() -> int:
    errors: list[str] = []
    actual = {
        path.name
        for path in ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(".") and path.name not in {"docs", "scripts"}
    }
    missing = EXPECTED_SKILLS - actual
    unexpected = actual - EXPECTED_SKILLS
    for name in sorted(missing):
        fail(f"skill esperada ausente: {name}", errors)
    for name in sorted(unexpected):
        fail(f"diretório de skill inesperado: {name}", errors)
    for name in sorted(EXPECTED_SKILLS & actual):
        validate_skill(ROOT / name, errors)

    canonical = ROOT / "entregar-issue" / "contracts" / "manifest.json"
    if not canonical.is_file():
        fail("manifesto canônico de entregar-issue ausente", errors)

    if errors:
        print("Validação falhou:")
        print("\n".join(f"- {error}" for error in errors))
        return 1

    print(f"Validação OK: {len(EXPECTED_SKILLS)} skills encontradas e consistentes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
