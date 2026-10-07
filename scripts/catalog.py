#!/usr/bin/env python3
"""Shared catalog loading and deterministic validation helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CATALOG_RELATIVE = Path("config/skills-catalog.json")
CAPABILITIES_RELATIVE = Path("config/capabilities.json")
CATALOG_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")
CONTRACT_VERSION_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+$")
SKILL_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog(root: Path = ROOT) -> dict[str, Any]:
    path = root / CATALOG_RELATIVE
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"catalog must be a JSON object: {path}")
    return value


def load_capabilities(root: Path = ROOT) -> dict[str, Any]:
    path = root / CAPABILITIES_RELATIVE
    value = load_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"capability registry must be a JSON object: {path}")
    return value


def capability_names(root: Path = ROOT) -> set[str]:
    try:
        value = load_capabilities(root)
    except (OSError, json.JSONDecodeError, ValueError):
        return set()
    capabilities = value.get("capabilities")
    return set(capabilities) if isinstance(capabilities, dict) else set()


def validate_capabilities(root: Path = ROOT) -> list[str]:
    path = root / CAPABILITIES_RELATIVE
    if not path.is_file():
        return [f"capability registry missing: {CAPABILITIES_RELATIVE}"]
    try:
        value = load_capabilities(root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"capability registry invalid: {exc}"]
    errors: list[str] = []
    if value.get("schema_version") != 1:
        errors.append("capability registry schema_version must be 1")
    if value.get("system") != "skill-capabilities":
        errors.append("capability registry system must be skill-capabilities")
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, dict) or not capabilities:
        return [*errors, "capability registry capabilities must be a non-empty object"]
    for name, item in capabilities.items():
        label = f"capability {name}"
        if not isinstance(name, str) or not re.fullmatch(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", name):
            errors.append(f"{label}: invalid capability name")
        if not isinstance(item, dict):
            errors.append(f"{label}: definition must be an object")
            continue
        if not isinstance(item.get("description"), str) or not item.get("description", "").strip():
            errors.append(f"{label}: description must be non-empty")
        if item.get("missing_state") not in {"BLOCK", "UNKNOWN"}:
            errors.append(f"{label}: missing_state must be BLOCK or UNKNOWN")
        if item.get("fallback") not in {"return-unknown", "return-plan-only"}:
            errors.append(f"{label}: fallback is invalid")
    return errors


def catalog_skill_ids(catalog: dict[str, Any]) -> set[str]:
    return {
        str(item.get("id"))
        for item in catalog.get("skills", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def _frontmatter_value(content: str, key: str) -> str | None:
    match = re.search(rf"^{re.escape(key)}:\s*(.+)$", content, flags=re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value.strip()


def _is_relative_safe(value: object) -> bool:
    raw = str(value or "").replace("\\", "/")
    path = Path(raw)
    return bool(raw) and not path.is_absolute() and ".." not in path.parts and raw == raw.strip()


def validate_catalog(root: Path = ROOT, catalog: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_capabilities(root))
    path = root / CATALOG_RELATIVE
    if catalog is None:
        if not path.is_file():
            return [f"catalog missing: {CATALOG_RELATIVE}"]
        try:
            catalog = load_catalog(root)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return [f"catalog invalid: {exc}"]

    if catalog.get("schema_version") != 1:
        errors.append("catalog schema_version must be 1")
    if catalog.get("system") != "skill-catalog":
        errors.append("catalog system must be skill-catalog")
    catalog_version = catalog.get("catalog_version")
    if not isinstance(catalog_version, str) or not CATALOG_VERSION_RE.fullmatch(catalog_version):
        errors.append("catalog catalog_version must use YYYY-MM-DD.N")

    skills = catalog.get("skills")
    if not isinstance(skills, list) or not skills:
        errors.append("catalog skills must be a non-empty list")
        return errors

    required = {
        "id", "path", "status", "purpose", "summary", "input", "modes",
        "read_only", "write_owner", "contract_version", "positive_triggers",
        "negative_triggers", "required_capabilities",
    }
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, item in enumerate(skills):
        label = f"catalog skills[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = sorted(required - set(item))
        if missing:
            errors.append(f"{label} missing fields: {', '.join(missing)}")
        skill_id = item.get("id")
        skill_path = item.get("path")
        if not isinstance(skill_id, str) or not SKILL_ID_RE.fullmatch(skill_id):
            errors.append(f"{label}.id is not a valid skill id")
            skill_id = f"<invalid-{index}>"
        elif skill_id in seen_ids:
            errors.append(f"duplicate catalog skill id: {skill_id}")
        seen_ids.add(skill_id)
        if not isinstance(skill_path, str) or not _is_relative_safe(skill_path):
            errors.append(f"{label}.path is not a safe relative path")
            skill_path = f"<invalid-{index}>"
        elif skill_path in seen_paths:
            errors.append(f"duplicate catalog skill path: {skill_path}")
        seen_paths.add(skill_path)
        if isinstance(skill_id, str) and isinstance(skill_path, str) and skill_id != skill_path:
            errors.append(f"{label}.id must equal .path for a catalog skill")

        if item.get("status") not in {"planned", "implemented", "validated"}:
            errors.append(f"{label}.status is invalid")
        if not isinstance(item.get("purpose"), str) or not item.get("purpose", "").strip():
            errors.append(f"{label}.purpose must be non-empty")
        for field in ("summary", "input", "write_owner"):
            if not isinstance(item.get(field), str) or not item.get(field, "").strip():
                errors.append(f"{label}.{field} must be non-empty")
        if not isinstance(item.get("read_only"), bool):
            errors.append(f"{label}.read_only must be boolean")
        contract_version = item.get("contract_version")
        if not isinstance(contract_version, str) or not CONTRACT_VERSION_RE.fullmatch(contract_version):
            errors.append(f"{label}.contract_version is invalid")

        for field in ("modes", "positive_triggers", "negative_triggers", "required_capabilities"):
            value = item.get(field)
            if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
                errors.append(f"{label}.{field} must be a non-empty list of strings")
            elif len(value) != len(set(value)):
                errors.append(f"{label}.{field} contains duplicates")
        capabilities = item.get("required_capabilities")
        if isinstance(capabilities, list):
            unknown = sorted(set(capabilities) - capability_names(root))
            if unknown:
                errors.append(f"{label}.required_capabilities unknown: {', '.join(unknown)}")

        if not isinstance(skill_path, str) or skill_path.startswith("<invalid-"):
            continue
        skill_dir = root / skill_path
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"{label}: missing {skill_path}/SKILL.md")
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{label}: cannot read SKILL.md: {exc}")
            continue
        if not content.startswith("---\n") or not re.search(r"^---\n.*?\n---\n", content, flags=re.DOTALL):
            errors.append(f"{label}: SKILL.md frontmatter is invalid")
        else:
            frontmatter_name = _frontmatter_value(content, "name")
            if frontmatter_name != skill_id:
                errors.append(f"{label}: frontmatter name does not match {skill_id}")
            if not _frontmatter_value(content, "description"):
                errors.append(f"{label}: frontmatter description is missing")

        version_path = skill_dir / "contracts" / "version.json"
        if version_path.is_file():
            try:
                version = load_json(version_path)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{label}: invalid contracts/version.json: {exc}")
            else:
                if version.get("contract_version") != contract_version:
                    errors.append(f"{label}: catalog contract_version differs from contracts/version.json")
        elif item.get("status") == "validated":
            errors.append(f"{label}: validated skill lacks contracts/version.json")

    return errors
