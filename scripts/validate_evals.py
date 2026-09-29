#!/usr/bin/env python3
"""Validate evaluation cases and the deterministic harness fixture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from evals.run_evals import HarnessError, load_json, load_schema, run_evaluations, schema_errors
except ModuleNotFoundError:  # pragma: no cover - script execution path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from evals.run_evals import HarnessError, load_json, load_schema, run_evaluations, schema_errors


def validate_evals(root: Path) -> list[str]:
    errors: list[str] = []
    try:
        manifest = load_json(root / "evals" / "manifest.json", "evals/manifest.json")
        errors.extend(schema_errors(manifest, load_schema(root, "eval-manifest.schema.json")))
        for key in ("runner", "validator", "case_schema", "result_schema", "report_schema"):
            target = root / manifest.get(key, "__missing__")
            if not target.is_file():
                errors.append(f"manifest target ausente: {manifest.get(key)!r}")
    except HarnessError as exc:
        errors.append(str(exc))
        return errors
    try:
        validation = run_evaluations(root, validate_only=True)
    except HarnessError as exc:
        return [str(exc)]
    if validation["summary"]["total"] < 1:
        errors.append("nenhum caso de avaliação validado")

    fixture_dir = root / "evals" / "fixtures" / "results"
    try:
        replay = run_evaluations(root, results_dir=fixture_dir)
    except HarnessError as exc:
        errors.append(str(exc))
        return errors
    if replay["summary"]["failed"] or replay["summary"]["invalid"]:
        errors.append("fixture replay contém falhas ou resultados inválidos")
    if replay["summary"]["not_run"]:
        errors.append("fixture replay contém casos não executados")
    if replay["summary"]["passed"] != replay["summary"]["total"]:
        errors.append("fixture replay não aprovou todos os casos")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    errors = validate_evals(args.root.resolve())
    if errors:
        print("Validação de avaliações falhou:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Evaluation harness validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
