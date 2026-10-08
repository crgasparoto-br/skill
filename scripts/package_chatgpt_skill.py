#!/usr/bin/env python3
"""Validate and package one ChatGPT skill directory as skill.zip."""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

MAX_BYTES = 25 * 1024 * 1024
SCRIPT_REF_RE = re.compile(r"(?<![A-Za-z0-9_.-])(scripts/[A-Za-z0-9_./-]+\.(?:py|sh))")
ENTREGAR_REQUIRED = {
    "scripts/runtime_resource_preflight.py",
    "scripts/build_handoff_certificate.py",
    "scripts/classify_audit_transport.py",
    "scripts/classify_handoff_recovery.py",
    "scripts/delivery_target_binding.py",
    "scripts/validate_delivery_completion.py",
    "scripts/validate_result_only_pr_recovery.py",
    "scripts/validate_terminal_handoff.py",
}
BASE_REQUIRED = {"SKILL.md", "agents/openai.yaml"}
EXCLUDED_PATH_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def is_packaged_file(path: Path, skill_dir: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    relative = path.relative_to(skill_dir)
    if any(part in EXCLUDED_PATH_PARTS for part in relative.parts):
        return False
    return path.suffix not in EXCLUDED_SUFFIXES


def referenced_scripts(skill_dir: Path) -> set[str]:
    refs: set[str] = set()
    for path in skill_dir.rglob("*.md"):
        if path.is_symlink() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for match in SCRIPT_REF_RE.finditer(text):
            prefix = text[max(0, match.start() - 96):match.start()]
            external = re.search(r"<([a-z0-9-]+)>/$", prefix)
            if external and external.group(1) not in {"skill", skill_dir.name}:
                continue
            refs.add(match.group(1))
    return refs


def validate_skill_runtime(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    if not skill_dir.is_dir():
        return [f"skill directory is missing: {skill_dir}"]
    for rel in sorted(BASE_REQUIRED):
        if not (skill_dir / rel).is_file():
            errors.append(f"required skill file is missing: {rel}")
    for required_dir in ("references", "scripts"):
        if not (skill_dir / required_dir).is_dir():
            errors.append(f"required skill directory is missing: {required_dir}/")
    if skill_dir.name == "entregar-issue":
        for rel in sorted(ENTREGAR_REQUIRED):
            if not (skill_dir / rel).is_file():
                errors.append(f"entregar-issue terminal runtime file is missing: {rel}")
    for rel in sorted(referenced_scripts(skill_dir)):
        if not (skill_dir / rel).is_file():
            errors.append(f"SKILL/reference points to missing runtime file: {rel}")
    for path in skill_dir.rglob("*"):
        if path.is_symlink():
            errors.append(f"symlink is not allowed in packaged skill: {path.relative_to(skill_dir)}")
    return errors


def archive_names(skill_dir: Path) -> list[str]:
    return [
        f"{skill_dir.name}/{path.relative_to(skill_dir).as_posix()}"
        for path in skill_dir.rglob("*")
        if is_packaged_file(path, skill_dir)
    ]


def package(skill_dir: Path, output: Path) -> list[str]:
    errors = validate_skill_runtime(skill_dir)
    if errors:
        return errors
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(skill_dir.rglob("*")):
            if is_packaged_file(path, skill_dir):
                zf.write(path, f"{skill_dir.name}/{path.relative_to(skill_dir).as_posix()}")
    if output.stat().st_size > MAX_BYTES:
        errors.append(f"skill archive exceeds 25 MiB: {output.stat().st_size} bytes")
        return errors
    expected = set(archive_names(skill_dir))
    with zipfile.ZipFile(output) as zf:
        actual = set(zf.namelist())
    missing = sorted(expected - actual)
    if missing:
        errors.append("archive is incomplete: " + ", ".join(missing[:20]))
    if skill_dir.name == "entregar-issue":
        for rel in sorted(ENTREGAR_REQUIRED):
            name = f"entregar-issue/{rel}"
            if name not in actual:
                errors.append(f"archive lacks terminal runtime file: {name}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill_dir", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist/skill.zip"))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    skill_dir = args.skill_dir.resolve()
    errors = validate_skill_runtime(skill_dir) if args.validate_only else package(skill_dir, args.output.resolve())
    if errors:
        print("Skill package validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Skill runtime validation OK: {skill_dir.name}" if args.validate_only else f"Skill package OK: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
