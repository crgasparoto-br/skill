from __future__ import annotations

import builtins
import json
import shutil
from pathlib import Path

from scripts.catalog import load_catalog
from scripts.validate_versioning import (
    parse_lineage,
    parse_semver,
    validate_json_schema,
    validate_versioning,
)

ROOT = Path(__file__).resolve().parents[1]


def _versioning_fixture(tmp_path: Path) -> Path:
    files = [
        "VERSION",
        "CHANGELOG.md",
        "docs/RELEASE.md",
        "config/compatibility.json",
        "config/skills-catalog.json",
        "config/skill-system-requirements.json",
        ".github/skill-system-capabilities.json",
        "schemas/compatibility.schema.json",
        "config/platform-adapters.json",
    ]
    for item in files:
        destination = tmp_path / item
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / item, destination)
    for skill in load_catalog(ROOT)["skills"]:
        item = f"{skill['id']}/contracts/version.json"
        destination = tmp_path / item
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / item, destination)
    return tmp_path


def _write_compatibility(root: Path, document: dict) -> None:
    (root / "config/compatibility.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_versioning_manifest_is_consistent() -> None:
    assert validate_versioning(ROOT) == []


def test_semver_parser_accepts_public_versions_and_rejects_ambiguous_values() -> None:
    assert parse_semver("0.1.0") == (0, 1, 0)
    assert parse_semver("1.0.0") == (1, 0, 0)
    assert parse_semver("01.2.3") is None
    assert parse_semver("2026-09-29.2") is None


def test_lineage_parser_rejects_impossible_dates_and_zero_snapshots() -> None:
    assert parse_lineage("2026-09-29.2") is not None
    assert parse_lineage("2026-02-30.1") is None
    assert parse_lineage("2026-09-29.0") is None
    assert parse_lineage("2026-09-999.1") is None


def test_compatibility_schema_rejects_missing_required_fields(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    document = json.loads((root / "config/compatibility.json").read_text(encoding="utf-8"))
    del document["contract_policy"]["compatibility_mode"]
    _write_compatibility(root, document)
    errors = validate_versioning(root)
    assert any("compatibility schema" in error and "compatibility_mode" in error for error in errors)


def test_versioning_rejects_system_version_drift(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    document = json.loads((root / "config/compatibility.json").read_text(encoding="utf-8"))
    document["system_version"] = "2026-09-28.1"
    _write_compatibility(root, document)
    errors = validate_versioning(root)
    assert any("differs from requirements manifest" in error for error in errors)
    assert any("differs from capabilities manifest" in error for error in errors)


def test_versioning_rejects_impossible_lineage_date(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    document = json.loads((root / "config/compatibility.json").read_text(encoding="utf-8"))
    document["contract_policy"]["internal_lineage_version"] = "2026-02-30.1"
    _write_compatibility(root, document)
    errors = validate_versioning(root)
    assert any("internal_lineage_version must use a valid" in error for error in errors)


def test_versioning_rejects_adapter_introduction_drift(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    platform_path = root / "config/platform-adapters.json"
    platform = json.loads(platform_path.read_text(encoding="utf-8"))
    platform["adapters"][0]["introduced_in"] = "0.1.0"
    platform_path.write_text(json.dumps(platform, indent=2) + "\n", encoding="utf-8")
    errors = validate_versioning(root)
    assert any("compatibility min_release differs from platform introduced_in" in error for error in errors)


def test_versioning_rejects_missing_adapter_release_row(tmp_path: Path) -> None:
    root = _versioning_fixture(tmp_path)
    release_doc = root / "docs/RELEASE.md"
    release_doc.write_text(
        release_doc.read_text(encoding="utf-8").replace("| `application` | `0.2.0` | `supported` |\n", ""),
        encoding="utf-8",
    )
    errors = validate_versioning(root)
    assert any("missing adapter row" in error and "application" in error for error in errors)


def test_invalid_schema_returns_controlled_error(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    document = tmp_path / "document.json"
    schema.write_text('{"type": 17}', encoding="utf-8")
    document.write_text("{}", encoding="utf-8")
    errors = validate_json_schema(schema, document, "invalid schema")
    assert any("schema is invalid" in error for error in errors)


def test_schema_dependency_is_fail_closed(monkeypatch, tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    document = tmp_path / "document.json"
    schema.write_text("{}", encoding="utf-8")
    document.write_text("{}", encoding="utf-8")
    original_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ImportError("simulated missing jsonschema")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    errors = validate_json_schema(schema, document, "test schema")
    assert any("jsonschema dependency unavailable" in error for error in errors)
