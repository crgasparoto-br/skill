#!/usr/bin/env python3
"""Reject stale path:line evidence anchors against the exact candidate workspace.

This checks existence and line bounds, not the semantic correctness of a citation.
Run before material freeze; for connector-only sessions materialize the same SHA.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

EXT = r"[A-Za-z][A-Za-z0-9_+-]*"  # extensoes sem lista fixa
PART = r"[A-Za-z0-9_.@+\[\]{}()~-]+"
ANCHOR = re.compile(
    rf"(?<![\w./@+-])(?P<path>(?:(?:{PART}/)*{PART}\.{EXT}|(?:{PART}/)+{PART})):"
    r"(?P<ranges>\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)"
)
SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".next", ".audit", ".venv", "venv"}


def strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def source_index(root: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".cache")]
        for filename in files:
            relative = (Path(directory) / filename).relative_to(root).as_posix()
            result.setdefault(filename, []).append(relative)
    return result


def validate(root: Path, evidence_files: list[Path], *, require_qualified_paths: bool = False) -> tuple[list[str], int]:
    errors: list[str] = []
    index = source_index(root)
    checked = 0
    line_counts: dict[Path, int] = {}
    for evidence_path in evidence_files:
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            errors.append(f"{evidence_path}: invalid evidence JSON: {exc}")
            continue
        for value in strings(evidence):
            for match in ANCHOR.finditer(value):
                name = match.group("path")
                if require_qualified_paths and "/" not in name:
                    errors.append(f"{evidence_path.name}: {name}: unqualified source path in partial checkout")
                    continue
                candidates = [name] if (root / name).is_file() else ([] if "/" in name else index.get(name, []))
                if len(candidates) != 1:
                    cause = "missing source" if not candidates else "ambiguous basename: " + ", ".join(candidates)
                    errors.append(f"{evidence_path.name}: {name}: {cause}")
                    continue
                target = root / candidates[0]
                if target.is_symlink() or target.resolve() != target or not target.resolve().is_relative_to(root):
                    errors.append(f"{evidence_path.name}: {name}: symlink or path escapes repository root")
                    continue
                if target not in line_counts:
                    try:
                        with target.open(encoding="utf-8") as handle:
                            line_counts[target] = sum(1 for _ in handle)
                    except (OSError, UnicodeError) as exc:
                        errors.append(f"{evidence_path.name}: {name}: cannot read: {exc}")
                        continue
                maximum = line_counts[target]
                for segment in match.group("ranges").split(","):
                    start, _, end_string = segment.partition("-")
                    first = int(start)
                    last = int(end_string or start)
                    checked += 1
                    if first < 1 or last < first or last > maximum:
                        errors.append(f"{evidence_path.name}: {name}:{segment} outside 1-{maximum} ({candidates[0]})")
    return errors, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--evidence", action="append", required=True, help="JSON evidence file, repeatable")
    parser.add_argument("--require-qualified-paths", action="store_true", help="Reject bare basenames when using a partial materialization")
    args = parser.parse_args()
    root = Path(args.repository_root).resolve()
    if not root.is_dir():
        print(f"BLOCK: repository root unavailable: {root}")
        return 2
    errors, checked = validate(root, [Path(p) for p in args.evidence], require_qualified_paths=args.require_qualified_paths)
    if checked == 0:
        errors.append("no source locations found in evidence; cannot attest source traceability")
    for error in errors:
        print("BLOCK: " + error)
    if errors:
        return 2
    print(f"READY: validated {checked} source line anchors against candidate workspace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
