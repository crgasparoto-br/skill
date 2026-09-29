#!/usr/bin/env python3
"""Validate every generated contract copy against the canonical manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

try:
    from .catalog import ROOT, catalog_skill_ids, load_catalog, validate_catalog
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT, catalog_skill_ids, load_catalog, validate_catalog

CANONICAL_SKILL = "entregar-issue"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"{label} is missing")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is invalid: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must be a JSON object")
        return None
    return value


def validate_manifest_shape(manifest: dict[str, Any], label: str, errors: list[str]) -> dict[str, str]:
    if manifest.get("schema_version") != 1:
        errors.append(f"{label}: schema_version must be 1")
    if not isinstance(manifest.get("contract_version"), str):
        errors.append(f"{label}: contract_version is missing")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        errors.append(f"{label}: files must be a non-empty object")
        return {}
    normalized: dict[str, str] = {}
    for name, digest in files.items():
        if not isinstance(name, str) or not name or "/" in name or name in {"manifest.json", "version.json"}:
            errors.append(f"{label}: invalid contract filename {name!r}")
            continue
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            errors.append(f"{label}: invalid hash for {name}")
            continue
        normalized[name] = digest
    return normalized


def validate_contract_sync(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    catalog_errors = validate_catalog(root)
    if catalog_errors:
        errors.extend(f"catalog prerequisite: {error}" for error in catalog_errors)
        return errors
    catalog = load_catalog(root)
    skill_ids = catalog_skill_ids(catalog)
    if CANONICAL_SKILL not in skill_ids:
        errors.append(f"catalog must include canonical skill {CANONICAL_SKILL}")
        return errors

    canonical_dir = root / CANONICAL_SKILL / "contracts"
    canonical_manifest_path = canonical_dir / "manifest.json"
    canonical_manifest = load_object(canonical_manifest_path, "canonical manifest", errors)
    if canonical_manifest is None:
        return errors
    canonical_files = validate_manifest_shape(canonical_manifest, "canonical manifest", errors)
    canonical_version = str(canonical_manifest.get("contract_version") or "")

    for name, expected in canonical_files.items():
        path = canonical_dir / name
        if not path.is_file():
            errors.append(f"canonical contract missing: {name}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            errors.append(f"canonical contract hash mismatch: {name} expected={expected} actual={actual}")

    for skill_id in sorted(skill_ids):
        skill_dir = root / skill_id
        contracts_dir = skill_dir / "contracts"
        version = load_object(contracts_dir / "version.json", f"{skill_id}/contracts/version.json", errors)
        if version is not None:
            if version.get("contract_version") != canonical_version:
                errors.append(f"{skill_id}: version contract_version differs from canonical manifest")
            if skill_id == CANONICAL_SKILL:
                if version.get("generated_copy") is not False:
                    errors.append(f"{skill_id}: canonical version must set generated_copy=false")
            elif version.get("generated_copy") is not True:
                errors.append(f"{skill_id}: generated copy must set generated_copy=true")
            if version.get("canonical_owner") != CANONICAL_SKILL:
                errors.append(f"{skill_id}: canonical_owner must be {CANONICAL_SKILL}")

        manifest_path = contracts_dir / "manifest.json"
        manifest = load_object(manifest_path, f"{skill_id}/contracts/manifest.json", errors)
        if manifest is None:
            continue
        skill_files = validate_manifest_shape(manifest, f"{skill_id} manifest", errors)
        if manifest.get("contract_version") != canonical_version:
            errors.append(f"{skill_id}: manifest contract_version differs from canonical manifest")
        unknown = sorted(set(skill_files) - set(canonical_files))
        if unknown:
            errors.append(f"{skill_id}: manifest references non-canonical files: {', '.join(unknown)}")
        for name, expected in skill_files.items():
            canonical_expected = canonical_files.get(name)
            if canonical_expected and expected != canonical_expected:
                errors.append(f"{skill_id}: manifest hash differs from canonical for {name}")
            path = contracts_dir / name
            if not path.is_file():
                errors.append(f"{skill_id}: generated contract missing: {name}")
                continue
            actual = sha256_file(path)
            if actual != expected:
                errors.append(f"{skill_id}: generated contract hash mismatch: {name} expected={expected} actual={actual}")

        allowed = set(skill_files) | {"manifest.json", "version.json"}
        if contracts_dir.is_dir():
            extras = sorted(
                path.name for path in contracts_dir.iterdir()
                if path.is_file() and path.name not in allowed
            )
            for extra in extras:
                errors.append(f"{skill_id}: contract file is not declared by its manifest: {extra}")

    # Every versioned skill in the catalog must be represented by a checked contract directory.
    for path in root.iterdir():
        if path.is_dir() and not path.name.startswith(".") and path.name not in {"adapters", "config", "docs", "scripts", "schemas", "tests"}:
            if path.name not in skill_ids:
                errors.append(f"unexpected skill directory outside catalog: {path.name}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate_contract_sync(args.root.resolve())
    if errors:
        print("Contract synchronization validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Contract synchronization validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
