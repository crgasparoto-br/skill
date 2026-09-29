#!/usr/bin/env python3
"""Validate evaluation cases and deterministic harness fixtures."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from evals.run_evals import (
        HarnessError,
        discover_cases,
        load_json,
        load_schema,
        run_evaluations,
        schema_errors,
    )
except ModuleNotFoundError:  # pragma: no cover - script execution path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from evals.run_evals import (
        HarnessError,
        discover_cases,
        load_json,
        load_schema,
        run_evaluations,
        schema_errors,
    )


REQUIRED_V030_002_CATEGORIES = {
    "selection",
    "authority",
    "capability",
    "evidence",
    "context",
    "progressive-loading",
    "read-only",
    "output-contract",
}


def validate_v030_002_matrix(root: Path) -> list[str]:
    """Require stable adversarial coverage instead of accepting case files alone."""
    try:
        cases = [case for _, case in discover_cases(root) if str(case["case_id"]).startswith("V030-002-")]
    except HarnessError as exc:
        return [str(exc)]

    errors: list[str] = []
    by_id = {case["case_id"]: case for case in cases}
    categories = {case["category"] for case in cases}
    missing_categories = sorted(REQUIRED_V030_002_CATEGORIES - categories)
    if missing_categories:
        errors.append("V030-002 lacks adversarial categories: " + ", ".join(missing_categories))
    if not cases:
        errors.append("V030-002 has no versioned adversarial cases")
        return errors

    for case in cases:
        case_id = case["case_id"]
        sibling_id = case.get("sibling_case_id")
        if not sibling_id:
            errors.append(f"{case_id} lacks sibling_case_id")
            continue
        sibling = by_id.get(sibling_id)
        if sibling is None:
            errors.append(f"{case_id} references missing sibling {sibling_id}")
            continue
        if sibling_id == case_id:
            errors.append(f"{case_id} cannot be its own sibling")
        if sibling.get("sibling_case_id") != case_id:
            errors.append(f"{case_id} and {sibling_id} must reference each other as siblings")
        if sibling.get("category") != case["category"]:
            errors.append(f"{case_id} and {sibling_id} must share the same category")
        if sibling.get("task", {}).get("user_prompt") == case.get("task", {}).get("user_prompt"):
            errors.append(f"{case_id} and {sibling_id} must vary the user prompt")
        expected = case["expected"]
        if not expected["required_evidence"]:
            errors.append(f"{case_id} must declare required evidence")
        if not expected["forbidden_actions"]:
            errors.append(f"{case_id} must declare forbidden actions")
        if not expected["response_minimum"]["required_markers"]:
            errors.append(f"{case_id} must declare response markers")
        if case["category"] == "selection":
            selection = expected.get("selection")
            if not isinstance(selection, dict) or len(selection["candidate_skills"]) < 2:
                errors.append(f"{case_id} must declare a structured material shortlist")
            elif not selection["disambiguation_required"]:
                errors.append(f"{case_id} must require disambiguation for the material selection tie")
        if case["category"] == "authority":
            untrusted_inputs = case["context"].get("untrusted_inputs") or []
            if not untrusted_inputs:
                errors.append(f"{case_id} must carry an untrusted input with explicit origin")
            if not isinstance(expected.get("authority"), dict):
                errors.append(f"{case_id} must declare structured authority expectations")
            for item in untrusted_inputs:
                if item["content"] in case["task"]["user_prompt"]:
                    errors.append(f"{case_id} must not inline untrusted content in the user prompt")
    return errors


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

    errors.extend(validate_v030_002_matrix(root))
    try:
        validation = run_evaluations(root, validate_only=True)
    except HarnessError as exc:
        return errors + [str(exc)]
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
