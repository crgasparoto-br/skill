#!/usr/bin/env python3
"""Enforce the context budget of control planes and references.

Progressive loading pays bytes and tokens, not line counts. The previous rule
asked only that `SKILL.md` stayed under 500 lines, and no validator applied it:
`entregar-issue/SKILL.md` passes that rule with 302 lines while carrying 60 KB and
single lines of 2293 characters. This validator replaces the line rule with
measured limits and fails closed on drift.

Invariants enforced here:

1. every `*/SKILL.md` and every `*/references/**/*.md` is measured, so a file
   matching a discovery pattern cannot be skipped;
2. a file must respect the default limits of its kind, unless an allowance names
   the exact dimensions it raises;
3. an allowance must declare a non-empty reason and only known limit keys;
4. an allowance must exceed the default on every dimension it names, otherwise it
   is convenience rather than debt;
5. an allowance must equal the current measurement of its file, so the config is a
   live measurement: growth fails immediately, and a file that shrinks requires the
   allowance to be lowered or removed;
6. an allowance for a file that respects the defaults, or for a file that does not
   exist, is rejected, so the allowance list can only shrink.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from .catalog import ROOT
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT

CONFIG_RELATIVE = "config/context-budget.json"
KINDS = ("control_plane", "reference")
LIMIT_KEYS = ("max_bytes", "max_line_chars")
ALLOWANCE_KEYS = {"max_bytes", "max_line_chars", "reason"}


def measure(path: Path) -> dict[str, int]:
    data = path.read_bytes()
    text = data.decode("utf-8")
    return {
        "max_bytes": len(data),
        "max_line_chars": max((len(line) for line in text.splitlines()), default=0),
    }


def load_config(root: Path, errors: list[str]) -> dict[str, Any] | None:
    path = root / CONFIG_RELATIVE
    if not path.is_file():
        errors.append(f"{CONFIG_RELATIVE} ausente")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{CONFIG_RELATIVE} inválido: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{CONFIG_RELATIVE} deve conter objeto JSON")
        return None
    if value.get("schema_version") != 1:
        errors.append(f"{CONFIG_RELATIVE}: schema_version inesperada")
    if value.get("system") != "context-budget":
        errors.append(f"{CONFIG_RELATIVE}: system inesperado")
    return value


def positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def load_limits(config: dict[str, Any], errors: list[str]) -> dict[str, dict[str, int]]:
    defaults = config.get("defaults")
    limits: dict[str, dict[str, int]] = {}
    if not isinstance(defaults, dict):
        errors.append(f"{CONFIG_RELATIVE}: defaults ausente")
        return limits
    for kind in KINDS:
        entry = defaults.get(kind)
        if not isinstance(entry, dict):
            errors.append(f"{CONFIG_RELATIVE}: defaults.{kind} ausente")
            continue
        resolved: dict[str, int] = {}
        for key in LIMIT_KEYS:
            if not positive_int(entry.get(key)):
                errors.append(f"{CONFIG_RELATIVE}: defaults.{kind}.{key} deve ser inteiro positivo")
                continue
            resolved[key] = entry[key]
        if len(resolved) == len(LIMIT_KEYS):
            limits[kind] = resolved
    return limits


def discover(root: Path, config: dict[str, Any], errors: list[str]) -> dict[str, list[Path]]:
    discovery = config.get("discovery")
    if not isinstance(discovery, dict):
        errors.append(f"{CONFIG_RELATIVE}: discovery ausente")
        return {}
    found: dict[str, list[Path]] = {}
    for kind in KINDS:
        patterns = discovery.get(kind)
        if not isinstance(patterns, list) or not patterns or not all(isinstance(p, str) and p.strip() for p in patterns):
            errors.append(f"{CONFIG_RELATIVE}: discovery.{kind} deve ser lista não vazia de padrões")
            continue
        paths: list[Path] = []
        for pattern in patterns:
            matched = sorted(path for path in root.glob(pattern.strip()) if path.is_file())
            if not matched:
                errors.append(f"{CONFIG_RELATIVE}: discovery.{kind} não corresponde a nenhum arquivo: {pattern}")
            paths.extend(matched)
        found[kind] = sorted(set(paths))
    return found


def validate_allowance(
    relative: str,
    allowance: Any,
    kind: str | None,
    defaults: dict[str, int],
    observed: dict[str, int] | None,
    errors: list[str],
) -> None:
    label = f"{CONFIG_RELATIVE}: allowances.{relative}"
    if not isinstance(allowance, dict):
        errors.append(f"{label} deve ser objeto")
        return
    unknown = sorted(set(allowance) - ALLOWANCE_KEYS)
    if unknown:
        errors.append(f"{label} contém chave desconhecida: {', '.join(unknown)}")
    if not str(allowance.get("reason", "")).strip():
        errors.append(f"{label} sem justificativa não vazia")
    declared = [key for key in LIMIT_KEYS if key in allowance]
    if not declared:
        errors.append(f"{label} não eleva nenhuma dimensão")
        return
    for key in declared:
        if not positive_int(allowance[key]):
            errors.append(f"{label}.{key} deve ser inteiro positivo")
    if kind is None or observed is None:
        errors.append(f"{label} não corresponde a arquivo descoberto")
        return
    for key in declared:
        value = allowance[key]
        if not positive_int(value):
            continue
        if value <= defaults[key]:
            errors.append(f"{label}.{key} não excede o padrão de {kind}, portanto é exceção desnecessária")
            continue
        if value != observed[key]:
            errors.append(
                f"{label}.{key} declara {value} mas a medição atual é {observed[key]}; "
                "atualize a exceção ou remova-a"
            )


def validate_context_budget(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    config = load_config(root, errors)
    if config is None:
        return errors
    defaults = load_limits(config, errors)
    if not defaults:
        return errors
    found = discover(root, config, errors)
    if not found:
        return errors

    observed: dict[str, dict[str, int]] = {}
    kind_by_relative: dict[str, str] = {}
    for kind, paths in found.items():
        if kind not in defaults:
            continue
        for path in paths:
            relative = path.relative_to(root).as_posix()
            kind_by_relative[relative] = kind
            observed[relative] = measure(path)

    for relative, kind in sorted(kind_by_relative.items()):
        if relative in (config.get("allowances") or {}):
            continue
        measured = observed[relative]
        for key in LIMIT_KEYS:
            if measured[key] > defaults[kind][key]:
                errors.append(
                    f"{relative}: {key}={measured[key]} excede o padrão de {kind} ({defaults[kind][key]}) "
                    "sem exceção declarada"
                )

    allowances = config.get("allowances")
    if not isinstance(allowances, dict):
        errors.append(f"{CONFIG_RELATIVE}: allowances deve ser objeto")
        return errors
    for relative, allowance in sorted(allowances.items()):
        if not isinstance(relative, str) or not relative.strip():
            errors.append(f"{CONFIG_RELATIVE}: allowances contém chave inválida")
            continue
        validate_allowance(
            relative,
            allowance,
            kind_by_relative.get(relative),
            defaults.get(kind_by_relative.get(relative, ""), {}),
            observed.get(relative),
            errors,
        )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate_context_budget(args.root.resolve())
    if errors:
        print("Context budget validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Context budget validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
