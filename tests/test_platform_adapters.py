from __future__ import annotations

import json
import shutil
from pathlib import Path

from scripts.validate_adapters import validate_adapters

ROOT = Path(__file__).resolve().parents[1]


def _adapter_fixture(tmp_path: Path) -> Path:
    for relative in (
        "config/platform-adapters.json",
        "config/skills-catalog.json",
        "config/capabilities.json",
        "schemas/platform-adapters.schema.json",
        "docs/PLATFORM_ADAPTERS.md",
        "docs/SKILL_SYSTEM_SPEC.md",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    shutil.copytree(ROOT / "adapters", tmp_path / "adapters")
    return tmp_path


def _write_manifest(root: Path, manifest: dict) -> None:
    (root / "config/platform-adapters.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def test_platform_adapter_manifest_is_valid() -> None:
    assert validate_adapters(ROOT) == []


def test_all_supported_platforms_have_explicit_instructions() -> None:
    manifest = json.loads((ROOT / "config/platform-adapters.json").read_text(encoding="utf-8"))
    adapter_ids = {item["id"] for item in manifest["adapters"]}
    assert adapter_ids == {"generic", "openai", "claude", "gemini", "ide", "application"}
    for item in manifest["adapters"]:
        path = ROOT / item["instruction_path"]
        assert path.is_file()
        assert path.read_text(encoding="utf-8").strip()


def test_load_order_is_exact_and_cannot_be_truncated(tmp_path: Path) -> None:
    root = _adapter_fixture(tmp_path)
    manifest = json.loads((root / "config/platform-adapters.json").read_text(encoding="utf-8"))
    manifest["adapters"][0]["load_order"] = [
        "config/compatibility.json",
        "config/skills-catalog.json",
        "config/capabilities.json",
        "schemas/contracts/scripts",
    ]
    _write_manifest(root, manifest)
    errors = validate_adapters(root)
    assert any("load_order" in error for error in errors)


def test_none_assumed_cannot_provide_capabilities(tmp_path: Path) -> None:
    root = _adapter_fixture(tmp_path)
    manifest = json.loads((root / "config/platform-adapters.json").read_text(encoding="utf-8"))
    manifest["adapters"][0]["provided_capabilities"] = ["repository-write"]
    _write_manifest(root, manifest)
    errors = validate_adapters(root)
    assert any("none-assumed" in error for error in errors)


def test_adapter_instructions_cannot_assert_host_access(tmp_path: Path) -> None:
    root = _adapter_fixture(tmp_path)
    (root / "adapters/generic.md").write_text(
        "Assuma que o host possui repository-write e test-execution.\n",
        encoding="utf-8",
    )
    errors = validate_adapters(root)
    assert any("presumes host capabilities" in error for error in errors)


def test_adapter_instructions_cannot_state_direct_host_access(tmp_path: Path) -> None:
    root = _adapter_fixture(tmp_path)
    (root / "adapters/generic.md").write_text(
        "O host possui repository-write e test-execution.\nThe host has ci-read.\n",
        encoding="utf-8",
    )
    errors = validate_adapters(root)
    assert any("presumes host capabilities" in error for error in errors)


def test_normative_spec_cannot_omit_platform_manifest_from_load_order(tmp_path: Path) -> None:
    root = _adapter_fixture(tmp_path)
    spec = root / "docs/SKILL_SYSTEM_SPEC.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(" → `config/platform-adapters.json`", ""),
        encoding="utf-8",
    )
    errors = validate_adapters(root)
    assert any("SKILL_SYSTEM_SPEC.md" in error and "canonical load order" in error for error in errors)
