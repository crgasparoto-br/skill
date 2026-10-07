from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator

if TYPE_CHECKING:
    from pathlib import Path


def validate_against_schema(data: Any, schema_path: Path, label: str, errors: list[str]) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{label} schema could not be loaded: {exc}")
        return
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"{label} schema violation at {location}: {error.message}")
