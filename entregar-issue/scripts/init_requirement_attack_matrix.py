#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_artifact_io import load_json_artifact
from risk_inference import (
    coverage_requirement_ids_from_closure,
    derive_families_from_obligation,
    derive_surfaces,
    required_test_cases_from_texts,
    requires_quantitative_evidence,
    retention_tiers_from_closure,
)


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise SystemExit("requirement closure must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement-closure", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    closure = load(Path(args.requirement_closure))
    retention_tiers = retention_tiers_from_closure(closure)
    coverage_requirement_ids = coverage_requirement_ids_from_closure(closure)
    by_requirement: dict[str, dict] = {}
    for obligation in closure.get("obligations") or []:
        if not isinstance(obligation, dict) or obligation.get("disposition") == "not-applicable":
            continue
        for requirement_id in obligation.get("requirement_ids") or []:
            rid = str(requirement_id)
            entry = by_requirement.setdefault(rid, {
                "requirement_id": rid,
                "obligation_ids": [],
                "risk_families": set(),
                "source_texts": [],
                "plausible_wrong_implementation": "",
                "positive_control": None,
                "negative_controls": [],
                "regression_controls": [],
                "obligation_control_map": [],
            })
            entry["obligation_ids"].append(str(obligation.get("id")))
            source_text = str(obligation.get("source_text") or "").strip()
            if source_text:
                entry["source_texts"].append(source_text)
            entry["risk_families"].update(derive_families_from_obligation(obligation))

    requirements = []
    for rid in sorted(by_requirement):
        item = by_requirement[rid]
        item["obligation_ids"] = sorted(set(item["obligation_ids"]))
        item["source_texts"] = sorted(set(item["source_texts"]))
        item["risk_families"] = sorted(item["risk_families"])
        item["risk_surfaces"] = derive_surfaces(item["source_texts"])
        item["quantitative_evidence_required"] = requires_quantitative_evidence(item["source_texts"])
        item["obligation_control_map"] = [
            {"obligation_id": oid, "primary_negative_control_id": ""}
            for oid in item["obligation_ids"]
        ]
        required_test_cases = required_test_cases_from_texts(item["source_texts"])
        if required_test_cases:
            item["test_coverage_contract"] = {
                "cases": [
                    {
                        "case": case,
                        "control_id": "",
                        "status": "pending",
                        "evidence": "",
                    }
                    for case in required_test_cases
                ]
            }
        performance_surfaces = {
            str(entry.get("surface") or "")
            for entry in item["risk_surfaces"]
            if isinstance(entry, dict)
        } & {"stage-attribution-completeness", "critical-path-necessity", "benchmark-path-fidelity"}
        if performance_surfaces:
            item["performance_contract"] = {
                "production_entrypoint": "",
                "terminal_boundary": "",
                "inventory_evidence": None,
                "operations": [],
                "optimized_branches": [],
                "benchmark": None,
            }
        if rid in coverage_requirement_ids and retention_tiers:
            item["coverage_contract"] = {
                "reporting_entrypoint": "",
                "retained_tiers": [
                    {
                        **tier,
                        "applicability": "unclassified",
                        "reason": "",
                        "control_id": "",
                    }
                    for tier in retention_tiers
                ],
            }
        requirements.append(item)

    output = {
        "schema_version": 1,
        "head_sha": args.head_sha,
        "requirements": requirements,
        "uncovered_requirements": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
