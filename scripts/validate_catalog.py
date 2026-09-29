#!/usr/bin/env python3
"""Validate the machine-readable skill catalog and its skill metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .catalog import ROOT, validate_catalog
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT, validate_catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate_catalog(root)
    schema_documents = (
        (root / "schemas" / "skill-catalog.schema.json", root / "config" / "skills-catalog.json", "catalog"),
        (root / "schemas" / "capabilities.schema.json", root / "config" / "capabilities.json", "capabilities"),
    )
    for schema_path, document_path, label in schema_documents:
        if not schema_path.is_file() or not document_path.is_file():
            continue
        try:
            from jsonschema import Draft202012Validator

            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            document = json.loads(document_path.read_text(encoding="utf-8"))
            schema_errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda error: list(error.path))
            errors.extend(
                f"JSON Schema ({label}): {'/'.join(str(part) for part in error.path) or '$'}: {error.message}"
                for error in schema_errors
            )
        except ImportError:
            break
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot validate {label} schema: {exc}")
    if errors:
        print("Catalog validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Catalog validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
