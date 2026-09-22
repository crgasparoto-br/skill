#!/usr/bin/env python3
"""Audit-side readiness check for compact standard delivery evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_artifact_io import load_json_artifact

CRITICAL_FLAGS = {"isolation", "atomicity", "reference-liveness"}

def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement-closure", required=True)
    parser.add_argument("--standard-evidence", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--contract-version", required=True)
    args = parser.parse_args()
    errors: list[str] = []
    try:
        closure = load(Path(args.requirement_closure))
        evidence = load(Path(args.standard_evidence))
    except Exception as exc:
        print(f"BLOCK: invalid standard evidence input: {exc}")
        return 2

    required_ids: set[str] = set()
    critical: list[str] = []
    for obligation in closure.get("obligations") or []:
        if not isinstance(obligation, dict) or obligation.get("disposition") != "covered":
            continue
        flags = {str(v) for v in obligation.get("flags") or []}
        hit = sorted(flags & CRITICAL_FLAGS)
        if hit:
            critical.append(f"{obligation.get('id') or '?'}:{','.join(hit)}")
        required_ids.update(str(v).strip() for v in obligation.get("requirement_ids") or [] if str(v).strip())
    if critical:
        errors.append("delivery used standard evidence for critical obligations: " + "; ".join(critical))
    if evidence.get("schema_version") != 1:
        errors.append("standard evidence schema_version must be 1")
    if evidence.get("contract_version") != args.contract_version:
        errors.append("standard evidence contract_version mismatch")
    if evidence.get("head_sha") != args.head_sha:
        errors.append("standard evidence is stale for material head")

    rows = evidence.get("requirements")
    if not isinstance(rows, list):
        errors.append("standard evidence requirements must be an array")
        rows = []
    by_id = {}
    for row in rows:
        if not isinstance(row, dict):
            errors.append("standard evidence contains non-object requirement row")
            continue
        rid = str(row.get("requirement_id") or "").strip()
        if not rid:
            errors.append("standard evidence requirement row lacks requirement_id")
            continue
        if rid in by_id:
            errors.append(f"duplicate standard evidence requirement_id: {rid}")
        by_id[rid] = row
        for field in ("positive_evidence", "regression_evidence"):
            values = row.get(field)
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
                errors.append(f"{rid}: {field} must contain evidence strings")
        neg = row.get("primary_negative_control")
        if not isinstance(neg, dict) or neg.get("status") != "passed":
            errors.append(f"{rid}: primary negative control is absent or not passed")
        elif any(not isinstance(neg.get(field), str) or not neg[field].strip() for field in ("id", "procedure", "expected", "observed")):
            errors.append(f"{rid}: primary negative control is incomplete")
    missing = sorted(required_ids - set(by_id))
    if missing:
        errors.append("standard evidence omits requirement ids: " + ", ".join(missing))

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print(f"READY: standard evidence preflight covers {len(required_ids)} requirements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
