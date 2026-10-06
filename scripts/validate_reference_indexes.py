#!/usr/bin/env python3
"""Validate navigability of skill references.

Progressive loading is only selective when a reference can be entered without being
read whole. A long reference must therefore declare when it should be read and expose
an index whose anchors resolve to its own headings.

Rules:

1. every reference at or above the declared byte threshold must declare when to be
   read and must expose an index;
2. every index entry must be a local anchor that resolves to a heading in the same
   file, so an index cannot point at nothing;
3. every heading of the file must be reachable from the index, so an index cannot
   silently omit a section;
4. an exclusion is allowed only for a reference that exists, carries a non-empty
   reason, and is at or above the threshold, so the exclusion list cannot grow by
   convenience.

The size limit itself belongs to `config/context-budget.json` and is not re-checked
here; this validator decides only which references must be navigable.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from .catalog import ROOT
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT

CONFIG_RELATIVE = "config/reference-index.json"
DISCOVERY = "*/references/**/*.md"
INDEX_HEADINGS = ("Índice", "Indice")
CONDITIONAL_HEADING = "Quando ler este arquivo"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def slugify(heading: str) -> str:
    """Return the anchor GitHub derives from a heading."""
    text = heading.strip().casefold()
    text = "".join(char for char in text if char.isalnum() or char in " -_")
    return re.sub(r"\s", "-", text)


def parse_headings(text: str) -> list[tuple[int, str, int]]:
    """Return (level, title, line number) for every Markdown heading."""
    headings: list[tuple[int, str, int]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING_RE.match(line)
        if match:
            headings.append((len(match.group(1)), match.group(2), number))
    return headings


def section_body(lines: list[str], start_line: int, level: int) -> str:
    """Return the body of the section starting at `start_line` (1-indexed)."""
    body: list[str] = []
    for line in lines[start_line:]:
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body)


def index_heading_line(headings: list[tuple[int, str, int]]) -> tuple[int, str, int] | None:
    for level, title, number in headings:
        if title in INDEX_HEADINGS:
            return level, title, number
    return None


def conditional_heading_line(headings: list[tuple[int, str, int]]) -> tuple[int, str, int] | None:
    for level, title, number in headings:
        if title.casefold() == CONDITIONAL_HEADING.casefold():
            return level, title, number
    return None


def load_config(root: Path, errors: list[str]) -> dict[str, Any] | None:
    path = root / CONFIG_RELATIVE
    if not path.is_file():
        errors.append(f"{CONFIG_RELATIVE} ausente")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{CONFIG_RELATIVE} inválido: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{CONFIG_RELATIVE} deve conter objeto JSON")
        return None
    if value.get("schema_version") != 1:
        errors.append(f"{CONFIG_RELATIVE}: schema_version inesperada")
    if value.get("system") != "reference-index":
        errors.append(f"{CONFIG_RELATIVE}: system inesperado")
    threshold = value.get("index_threshold_bytes")
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold <= 0:
        errors.append(f"{CONFIG_RELATIVE}: index_threshold_bytes deve ser inteiro positivo")
        return None
    return value


def validate_reference_indexes(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    config = load_config(root, errors)
    if config is None:
        return errors
    threshold: int = config["index_threshold_bytes"]

    references = sorted(path for path in root.glob(DISCOVERY) if path.is_file())
    if not references:
        errors.append(f"nenhuma referência encontrada em {DISCOVERY}")
        return errors

    excluded = config.get("exclusions")
    if not isinstance(excluded, dict):
        errors.append(f"{CONFIG_RELATIVE}: exclusions deve ser objeto")
        excluded = {}

    sizes: dict[str, int] = {}
    for path in references:
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        sizes[relative] = len(path.read_bytes())
        headings = parse_headings(text)
        index_entry = index_heading_line(headings)
        conditional_entry = conditional_heading_line(headings)
        needs_index = sizes[relative] >= threshold and relative not in excluded

        if needs_index and index_entry is None:
            errors.append(f"{relative}: referência com {sizes[relative]} bytes sem seção de índice")
        if needs_index and conditional_entry is None:
            errors.append(f"{relative}: referência com {sizes[relative]} bytes sem bloco '{CONDITIONAL_HEADING}'")
        if index_entry is None:
            continue

        level, _, index_line = index_entry
        body = section_body(lines, index_line, level)
        entries = LINK_RE.findall(body)
        if not entries:
            errors.append(f"{relative}: seção de índice sem nenhuma entrada")
        slugs = {slugify(title) for _, title, _ in headings}
        for target in entries:
            anchor = target.strip()
            if not anchor.startswith("#"):
                errors.append(f"{relative}: entrada de índice não é âncora local: {anchor}")
                continue
            if anchor[1:] not in slugs:
                errors.append(f"{relative}: âncora de índice não resolve: {anchor}")
        linked = {target.strip()[1:] for target in entries if target.strip().startswith("#")}
        required = {
            slugify(title)
            for heading_level, title, number in headings
            if heading_level == 2
            and title not in INDEX_HEADINGS
            and title.casefold() != CONDITIONAL_HEADING.casefold()
            and number != index_line
        }
        for missing in sorted(required - linked):
            errors.append(f"{relative}: seção ausente do índice: #{missing}")

    for relative, exclusion in sorted(excluded.items()):
        label = f"{CONFIG_RELATIVE}: exclusions.{relative}"
        if not isinstance(exclusion, dict) or not str(exclusion.get("reason", "")).strip():
            errors.append(f"{label} sem justificativa não vazia")
            continue
        if relative not in sizes:
            errors.append(f"{label} não corresponde a referência descoberta")
            continue
        if sizes[relative] < threshold:
            errors.append(f"{label} é exceção desnecessária: a referência está abaixo do limiar")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate_reference_indexes(args.root.resolve())
    if errors:
        print("Reference index validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Reference index validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())