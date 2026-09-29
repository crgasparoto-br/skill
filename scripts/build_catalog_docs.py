#!/usr/bin/env python3
"""Build or check the generated skill catalog table in README.md."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .catalog import ROOT, load_catalog
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT, load_catalog

START = "<!-- BEGIN GENERATED: skill-catalog -->"
END = "<!-- END GENERATED: skill-catalog -->"


def render_catalog(catalog: dict) -> str:
    rows = [
        START,
        "| Skill | Finalidade | Entrada principal |",
        "| --- | --- | --- |",
    ]
    for item in catalog["skills"]:
        rows.append(f"| [`{item['id']}`](./{item['path']}/) | {item['summary']} | {item['input']} |")
    rows.append(END)
    return "\n".join(rows)


def replace_block(readme: str, block: str) -> str:
    start = readme.find(START)
    end = readme.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError("README.md lacks generated catalog markers")
    end += len(END)
    return readme[:start] + block + readme[end:]


def validate_readme_catalog(root: Path = ROOT) -> list[str]:
    readme_path = root / "README.md"
    if not readme_path.is_file():
        return ["README.md is missing"]
    try:
        expected = render_catalog(load_catalog(root))
        actual_readme = readme_path.read_text(encoding="utf-8")
        actual = replace_block(actual_readme, expected)
    except (OSError, ValueError, KeyError) as exc:
        return [f"generated catalog documentation is invalid: {exc}"]
    if actual != actual_readme:
        return ["README.md generated skill catalog is stale; run build_catalog_docs.py --write"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="check generated content without writing (default)")
    mode.add_argument("--write", action="store_true", help="write generated content")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    readme_path = root / "README.md"
    try:
        content = readme_path.read_text(encoding="utf-8")
        block = render_catalog(load_catalog(root))
        updated = replace_block(content, block)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Catalog documentation failed: {exc}")
        return 1
    if args.write:
        readme_path.write_text(updated, encoding="utf-8")
        print("Generated catalog documentation written.")
        return 0
    errors = validate_readme_catalog(root)
    if errors:
        for error in errors:
            print(f"- {error}")
        return 1
    print("Generated catalog documentation is current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
