#!/usr/bin/env python3
"""Reject stale path:line evidence anchors against the exact candidate workspace.

This checks existence and line bounds, not the semantic correctness of a citation.
Run before material freeze; for connector-only sessions materialize the same SHA.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any

EXT = r"[\w][\w+-]*"  # independente de linguagem e Unicode
PART = r"[\w.@+\[\]{}()~-]+"
PATH = rf"(?:(?:\./)?(?:{PART}/)*{PART}\.{EXT}|(?:\./)?(?:{PART}/)+{PART})"
CANDIDATE = re.compile(rf"(?<![\w./@+-])(?P<path>{PATH}):(?P<ranges>[^\s\"'<>\x60]+)")
RANGES = re.compile(r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*")
# Fail closed when prose abbreviates a second file:line anchor.
ABBREVIATED = re.compile(r"(?:\b(?:and|or|e|ou)\b|[,;])\s+:(?P<range>\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)(?![\w-])", re.IGNORECASE)
IGNORED_FIELDS = {"stderr", "stdout", "log", "logs", "diagnostic", "diagnostics", "error_message", "warning_message", "transcript"}
SKIP_DIRS = {".git", "node_modules", "dist", "build", "coverage", ".next", ".audit", ".venv", "venv"}


def strings(value: Any):
    """Walk evidence-bearing content including JSON keys, not diagnostic output."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield key
                if key.casefold() in IGNORED_FIELDS:
                    continue
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def abbreviated_locations(value: str):
    """Yield shorthand ranges following a qualified path in the same evidence string."""
    anchors = list(CANDIDATE.finditer(value))
    for index, anchor in enumerate(anchors):
        end = anchors[index + 1].start() if index + 1 < len(anchors) else len(value)
        for short in ABBREVIATED.finditer(value, anchor.end(), end):
            yield anchor.group("path"), short.group("range")


def candidate_locations(evidence_files: list[Path]) -> int:
    """Count lexical location candidates without requiring a source checkout."""
    total = 0
    for path in evidence_files:
        from audit_artifact_io import load_json_artifact
        evidence = load_json_artifact(path)
        total += sum(1 for value in strings(evidence) for _ in CANDIDATE.finditer(value))
        total += sum(1 for value in strings(evidence) for _ in abbreviated_locations(value))
    return total


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
            from audit_artifact_io import load_json_artifact
            evidence = load_json_artifact(evidence_path)
        except (ValueError, OSError) as exc:
            errors.append(f"{evidence_path}: invalid evidence JSON: {exc}")
            continue
        for value in strings(evidence):
            for name, segment in abbreviated_locations(value):
                errors.append(
                    f"{evidence_path.name}: {name} and :{segment} abbreviated line reference; "
                    "repeat the complete source path"
                )
            for match in CANDIDATE.finditer(value):
                name = match.group("path")
                segment_text = match.group("ranges").rstrip(".,;)}]")
                if not RANGES.fullmatch(segment_text):
                    errors.append(f"{evidence_path.name}: {name}:{segment_text} malformed line range")
                    continue
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
                for segment in segment_text.split(","):
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
