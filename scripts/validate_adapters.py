#!/usr/bin/env python3
"""Validate the platform adapter manifest and its instruction files."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from .catalog import ROOT, capability_names, load_capabilities, load_catalog
    from .validate_versioning import parse_semver, validate_json_schema
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT, capability_names, load_capabilities, load_catalog
    from validate_versioning import parse_semver, validate_json_schema

EXPECTED_ADAPTERS = {"generic", "openai", "claude", "gemini", "ide", "application"}
EXPECTED_LOAD_ORDER = [
    "config/compatibility.json",
    "config/skills-catalog.json",
    "config/capabilities.json",
    "config/platform-adapters.json",
    "<skill>/SKILL.md",
    "conditional references",
    "schemas/contracts/scripts",
]
EXPECTED_LOAD_TEXT = [
    "config/compatibility.json",
    "config/skills-catalog.json",
    "config/capabilities.json",
    "config/platform-adapters.json",
    "<skill>/SKILL.md",
    ("conditional references", "referências condicionais"),
    "schemas/contracts/scripts",
]


def contains_canonical_load_order(text: str) -> bool:
    position = -1
    for token in EXPECTED_LOAD_TEXT:
        candidates = token if isinstance(token, tuple) else (token,)
        found = [text.find(candidate, position + 1) for candidate in candidates]
        position = min((item for item in found if item >= 0), default=-1)
        if position < 0:
            return False
    return True


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
        errors.append(f"{label} must be an object")
        return None
    return value


def validate_adapters(root: Path = ROOT) -> list[str]:
    errors = validate_json_schema(
        root / "schemas" / "platform-adapters.schema.json",
        root / "config" / "platform-adapters.json",
        "platform adapters schema",
    )
    manifest_path = root / "config" / "platform-adapters.json"
    manifest = load_object(manifest_path, "platform adapter manifest", errors)
    if manifest is None:
        return errors
    try:
        catalog = load_catalog(root)
        capabilities = load_capabilities(root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [*errors, f"platform adapter prerequisites are invalid: {exc}"]

    if manifest.get("catalog_version") != catalog.get("catalog_version"):
        errors.append("platform adapter catalog_version differs from skills catalog")
    if capabilities.get("system") != "skill-capabilities":
        errors.append("platform adapter capability registry identity is invalid")
    capability_ids = capability_names(root)
    adapters = manifest.get("adapters")
    if not isinstance(adapters, list) or not adapters:
        return [*errors, "platform adapters must be a non-empty list"]
    actual_ids = {item.get("id") for item in adapters if isinstance(item, dict)}
    if actual_ids != EXPECTED_ADAPTERS:
        errors.append(f"platform adapter ids differ: expected={sorted(EXPECTED_ADAPTERS)} actual={sorted(actual_ids)}")
    if len(actual_ids) != len(adapters):
        errors.append("platform adapter ids must be unique")

    declared_paths: set[str] = set()
    for index, item in enumerate(adapters):
        label = f"platform adapters[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        for field in ("id", "platform", "instruction_path", "capability_source", "capability_profile", "fallback_policy"):
            if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                errors.append(f"{label}.{field} must be non-empty")
        if item.get("status") not in {"planned", "implemented", "validated"}:
            errors.append(f"{label}.status is invalid")
        if parse_semver(str(item.get("introduced_in"))) is None:
            errors.append(f"{label}.introduced_in must use SemVer")
        if item.get("capability_source") != "host-declared":
            errors.append(f"{label}.capability_source must be host-declared")
        if item.get("capability_profile") != "none-assumed":
            errors.append(f"{label}.capability_profile must be none-assumed")
        if item.get("fallback_policy") != "config/capabilities.json":
            errors.append(f"{label}.fallback_policy must use config/capabilities.json")
        provided = item.get("provided_capabilities")
        if not isinstance(provided, list) or len(provided) != len(set(provided)):
            errors.append(f"{label}.provided_capabilities must be a unique list")
        elif item.get("capability_profile") == "none-assumed" and provided != []:
            errors.append(f"{label}.none-assumed adapters cannot provide capabilities")
        elif set(provided) - capability_ids:
            errors.append(f"{label}.provided_capabilities contains unknown capabilities: {sorted(set(provided) - capability_ids)}")
        load_order = item.get("load_order")
        if load_order != EXPECTED_LOAD_ORDER:
            errors.append(f"{label}.load_order must equal the canonical progressive-loading sequence")

        instruction_path = item.get("instruction_path")
        if not isinstance(instruction_path, str) or not instruction_path.startswith("adapters/") or ".." in Path(instruction_path).parts:
            errors.append(f"{label}.instruction_path is unsafe")
            continue
        declared_paths.add(instruction_path)
        path = root / instruction_path
        content = ""
        if path.is_file():
            content = path.read_text(encoding="utf-8")
        if not path.is_file() or not content.strip():
            errors.append(f"{label}: instruction file is missing or empty: {instruction_path}")
        elif not contains_canonical_load_order(content):
            errors.append(f"{label}: instruction text does not declare the canonical load order")
        normalized_content = content.casefold()
        assumption_pattern = r"\b(assuma que|assume that|presuma que|presume that)\b.{0,80}\b(host|the host)\b.{0,60}\b(has|possui|tem|provides)\b"
        direct_access_pattern = r"\b(?:o\s+host|the\s+host|host)\s+(?:possui|tem|has|provides|fornece|acessa|can\s+access|may\s+access)\b.{0,100}\b(?:repository-write|test-execution|ci-read|git|browser|navegador|credentials|credenciais)\b"
        available_pattern = r"\b(?:repository-write|test-execution|ci-read)\b.{0,50}\b(?:is\s+available|est[aá]\s+dispon[ií]vel)\b.{0,30}\b(?:host|ambiente)\b"
        if re.search(assumption_pattern, normalized_content, flags=re.DOTALL) or re.search(direct_access_pattern, normalized_content, flags=re.DOTALL) or re.search(available_pattern, normalized_content, flags=re.DOTALL):
            errors.append(f"{label}: instruction text presumes host capabilities")
        if path.suffix == ".yaml":
            try:
                import yaml
                value = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    errors.append(f"{label}: YAML adapter must be an object")
            except ImportError:
                errors.append("YAML adapter validation requires PyYAML; dependency cannot be skipped")
            except (OSError, ValueError) as exc:
                errors.append(f"{label}: YAML adapter is invalid: {exc}")

    adapters_dir = root / "adapters"
    if adapters_dir.is_dir():
        actual_paths = {path.relative_to(root).as_posix() for path in adapters_dir.iterdir() if path.is_file()}
        extras = sorted(actual_paths - declared_paths)
        errors.extend(f"undeclared adapter instruction: {path}" for path in extras)
    if not (root / "docs" / "PLATFORM_ADAPTERS.md").is_file():
        errors.append("docs/PLATFORM_ADAPTERS.md is missing")
    for relative in ("docs/SKILL_SYSTEM_SPEC.md", "docs/PLATFORM_ADAPTERS.md"):
        path = root / relative
        if path.is_file() and not contains_canonical_load_order(path.read_text(encoding="utf-8")):
            errors.append(f"{relative} does not declare the canonical load order")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate_adapters(args.root.resolve())
    if errors:
        print("Platform adapter validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Platform adapter validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
