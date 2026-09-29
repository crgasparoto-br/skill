#!/usr/bin/env python3
"""Validate the machine-readable skill catalog and its skill metadata."""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    from .catalog import ROOT, validate_catalog
    from .validate_versioning import validate_json_schema
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT, validate_catalog
    from validate_versioning import validate_json_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate_catalog(root)
    schema_documents = (
        (root / "schemas" / "skill-catalog.schema.json", root / "config" / "skills-catalog.json", "catalog schema"),
        (root / "schemas" / "capabilities.schema.json", root / "config" / "capabilities.json", "capabilities schema"),
        (root / "schemas" / "compatibility.schema.json", root / "config" / "compatibility.json", "compatibility schema"),
    )
    for schema_path, document_path, label in schema_documents:
        errors.extend(validate_json_schema(schema_path, document_path, label))
    if errors:
        print("Catalog validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Catalog validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
