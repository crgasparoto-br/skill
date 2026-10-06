#!/usr/bin/env python3
"""Synchronize generated contract copies and declared shared files from their canonical sources."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .catalog import ROOT, catalog_skill_ids, load_catalog, validate_catalog
    from .validate_contract_sync import CANONICAL_SKILL, load_object, load_shared_groups, sha256_file, validate_manifest_shape, validate_contract_sync
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT, catalog_skill_ids, load_catalog, validate_catalog
    from validate_contract_sync import CANONICAL_SKILL, load_object, load_shared_groups, sha256_file, validate_manifest_shape, validate_contract_sync


def canonical_manifest(root: Path) -> tuple[Path, dict[str, Any]]:
    path = root / CANONICAL_SKILL / "contracts" / "manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("canonical manifest must be an object")
    return path, value


def refreshed_manifest(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    source_dir = root / CANONICAL_SKILL / "contracts"
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("canonical manifest files must be a non-empty object")
    refreshed = dict(manifest)
    refreshed["files"] = {
        name: sha256_file(source_dir / name)
        for name in sorted(files)
        if (source_dir / name).is_file()
    }
    if len(refreshed["files"]) != len(files):
        missing = sorted(set(files) - set(refreshed["files"]))
        raise ValueError(f"canonical contract files are missing: {', '.join(missing)}")
    return refreshed


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def synchronize(root: Path) -> list[str]:
    errors = validate_catalog(root)
    if errors:
        return [f"catalog prerequisite: {error}" for error in errors]
    _, original = canonical_manifest(root)
    canonical = refreshed_manifest(root, original)
    canonical_path = root / CANONICAL_SKILL / "contracts" / "manifest.json"
    if canonical != original:
        write_json(canonical_path, canonical)

    source_dir = root / CANONICAL_SKILL / "contracts"
    skill_ids = catalog_skill_ids(load_catalog(root))
    for skill_id in sorted(skill_ids - {CANONICAL_SKILL}):
        target_dir = root / skill_id / "contracts"
        target_manifest_path = target_dir / "manifest.json"
        if not target_manifest_path.is_file():
            return [f"{skill_id}: manifest.json is required before synchronization"]
        target = json.loads(target_manifest_path.read_text(encoding="utf-8"))
        names = target.get("files")
        if not isinstance(names, dict) or not names:
            return [f"{skill_id}: manifest files must be a non-empty object"]
        unknown = sorted(set(names) - set(canonical["files"]))
        if unknown:
            return [f"{skill_id}: manifest references non-canonical files: {', '.join(unknown)}"]
        for name in names:
            (target_dir / name).write_bytes((source_dir / name).read_bytes())
        generated = {
            "schema_version": 1,
            "contract_version": canonical["contract_version"],
            "files": {name: canonical["files"][name] for name in sorted(names)},
        }
        write_json(target_manifest_path, generated)

    errors: list[str] = []
    for canonical, copies in load_shared_groups(root, errors):
        source = root / canonical
        if not source.is_file():
            errors.append(f"shared canonical file missing: {canonical}")
            continue
        for copy in copies:
            target = root / copy
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="validate without writing (default)")
    mode.add_argument("--write", action="store_true", help="synchronize generated copies")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.write:
        errors = synchronize(root)
        if errors:
            print("Contract synchronization failed:")
            for error in errors:
                print(f"- {error}")
            return 1
        print("Contract copies synchronized.")
    errors = validate_contract_sync(root)
    if errors:
        print("Contract synchronization validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Contract synchronization validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
