#!/usr/bin/env python3
"""Validate local Markdown links, skill references and generated catalog docs."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

try:
    from .build_catalog_docs import validate_readme_catalog
    from .catalog import ROOT, validate_catalog
except ImportError:  # pragma: no cover - direct script execution
    from build_catalog_docs import validate_readme_catalog
    from catalog import ROOT, validate_catalog

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
PATH_REF_RE = re.compile(r"`((?:references|schemas|contracts|scripts)/[A-Za-z0-9_./-]+)`")


def iter_markdown_files(root: Path):
    for path in sorted(root.rglob("*.md")):
        if ".git" not in path.parts and ".venv" not in path.parts:
            yield path


def local_link_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for path in iter_markdown_files(root):
        in_fence = False
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for raw_target in LINK_RE.findall(line):
                target = raw_target.strip().strip("<>")
                if not target or target.startswith(("#", "http://", "https://", "mailto:")):
                    continue
                link = target.split("#", 1)[0].split("?", 1)[0].strip()
                if not link:
                    continue
                candidate = (path.parent / link).resolve()
                if not candidate.exists():
                    errors.append(f"{path.relative_to(root).as_posix()}:{line_no}: broken local link {link}")
    return errors


def skill_reference_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for skill_md in sorted(root.glob("*/SKILL.md")):
        in_fence = False
        for line_no, line in enumerate(skill_md.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for reference in PATH_REF_RE.findall(line):
                if "..." in reference or reference.endswith("/"):
                    continue
                candidate = (skill_md.parent / reference.rstrip(".,;:`)"))
                if not candidate.exists():
                    errors.append(f"{skill_md.relative_to(root).as_posix()}:{line_no}: missing skill reference {reference}")
    return errors


def validate_docs(root: Path = ROOT) -> list[str]:
    errors = list(validate_catalog(root))
    errors.extend(local_link_errors(root))
    errors.extend(skill_reference_errors(root))
    errors.extend(validate_readme_catalog(root))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate_docs(args.root.resolve())
    if errors:
        print("Documentation validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Documentation validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
