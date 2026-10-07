#!/usr/bin/env python3
"""Cheap preflight: reject a delivery packet that has not saturated requirements and risk families."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact
from preflight_semantic_guards import conflicting_current_sha_claims

CANONICAL = {
    "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
    "temporal-consistency", "temporal-destination", "concurrency-atomicity",
    "idempotency", "rollback", "historical-immutability", "structural-contract", "documentation",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def load(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def controls(item: dict) -> list[dict]:
    result: list[dict] = []
    pc = item.get("positive_control")
    if isinstance(pc, dict):
        result.append(pc)
    result.extend(c for c in item.get("negative_controls") or [] if isinstance(c, dict))
    result.extend(c for c in item.get("regression_controls") or [] if isinstance(c, dict))
    return result


def validate_quantitative_provenance(matrix: dict, provenance: dict | None, head_sha: str, errors: list[str]) -> None:
    quantitative: list[tuple[str, dict]] = []
    for item in matrix.get("requirements") or []:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("requirement_id") or "?")
        for control in controls(item):
            if str(control.get("evidence_kind") or "") == "quantitative":
                quantitative.append((rid, control))
    if not quantitative:
        return
    if provenance is None:
        errors.append("quantitative controls require evidence-provenance.json")
        return
    if provenance.get("schema_version") != 1:
        errors.append("evidence provenance schema_version must be 1")
    if str(provenance.get("material_head_sha") or "") != head_sha:
        errors.append("evidence provenance material_head_sha differs from candidate")
    entries = provenance.get("evidence")
    if not isinstance(entries, list):
        errors.append("evidence provenance evidence must be an array")
        return
    by_id = {
        str(item.get("evidence_id")): item
        for item in entries
        if isinstance(item, dict) and item.get("evidence_id")
    }
    for rid, control in quantitative:
        label = f"requirement {rid} quantitative control {control.get('id') or '?'}"
        evidence_id = str(control.get("evidence_id") or "").strip()
        if not evidence_id:
            errors.append(f"{label} lacks evidence_id")
            continue
        entry = by_id.get(evidence_id)
        if not entry:
            errors.append(f"{label} references unknown evidence_id {evidence_id}")
            continue
        if entry.get("kind") != "quantitative":
            errors.append(f"{label} provenance kind is not quantitative")
        if entry.get("status") != "passed":
            errors.append(f"{label} provenance entry is not passed")
        if entry.get("freshness_policy") != "exact-material-head":
            errors.append(f"{label} provenance is not exact-material-head")
        if str(entry.get("subject_sha") or "") != head_sha:
            errors.append(f"{label} measured subject_sha differs from candidate")
        control_path = str(control.get("evidence_path") or control.get("evidence") or "").strip()
        if control_path and control_path != str(entry.get("path") or "").strip():
            errors.append(f"{label} evidence path differs from provenance")
        control_hash = str(control.get("evidence_sha256") or "").strip()
        entry_hash = str(entry.get("sha256") or "").strip()
        if not SHA256_RE.match(control_hash):
            errors.append(f"{label} lacks valid evidence_sha256")
        elif control_hash != entry_hash:
            errors.append(f"{label} evidence hash differs from provenance")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--attack-matrix", required=True)
    p.add_argument("--risk-saturation", required=True)
    p.add_argument("--inherited-controls", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--evidence-provenance")
    a = p.parse_args()
    errors: list[str] = []
    try:
        matrix = load(Path(a.attack_matrix))
        risk = load(Path(a.risk_saturation))
        inherited = load(Path(a.inherited_controls))
        provenance = load(Path(a.evidence_provenance)) if a.evidence_provenance else None
    except Exception as exc:
        print(f"BLOCK: {exc}")
        return 2
    if matrix.get("head_sha") != a.head_sha:
        errors.append("attack matrix head_sha differs from candidate")
    if risk.get("head_sha") != a.head_sha:
        errors.append("risk saturation head_sha differs from candidate")
    if inherited.get("head_sha") != a.head_sha:
        errors.append("inherited controls head_sha differs from candidate")
    if matrix.get("uncovered_requirements"):
        errors.append("attack matrix has uncovered requirements")
    for item in matrix.get("requirements") or []:
        rid = item.get("requirement_id") if isinstance(item, dict) else "?"
        if not isinstance(item, dict):
            errors.append("invalid attack matrix entry")
            continue
        if len(str(item.get("plausible_wrong_implementation") or "").strip()) < 20:
            errors.append(f"requirement {rid} lacks plausible wrong implementation")
        pc = item.get("positive_control")
        if not isinstance(pc, dict) or pc.get("status") != "passed" or pc.get("head_sha") != a.head_sha:
            errors.append(f"requirement {rid} positive control not passed on candidate")
        neg = item.get("negative_controls") or []
        if not neg:
            errors.append(f"requirement {rid} lacks negative controls")
        if any(not isinstance(c, dict) or c.get("status") != "passed" or c.get("head_sha") != a.head_sha for c in neg):
            errors.append(f"requirement {rid} has negative control not passed on candidate")
        reg = item.get("regression_controls") or []
        if not reg:
            errors.append(f"requirement {rid} lacks regression controls")
        if any(not isinstance(c, dict) or c.get("status") != "passed" or c.get("head_sha") != a.head_sha for c in reg):
            errors.append(f"requirement {rid} has regression control not passed on candidate")
    validate_quantitative_provenance(matrix, provenance, a.head_sha, errors)
    families = {str(i.get("family")): i for i in risk.get("families") or [] if isinstance(i, dict)}
    matrix_families: set[str] = set()
    matrix_surfaces: set[tuple[str, str]] = set()
    for requirement in matrix.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        req_families = {str(value) for value in requirement.get("risk_families") or []}
        matrix_families.update(req_families)
        for surface in requirement.get("risk_surfaces") or []:
            if isinstance(surface, dict):
                family = str(surface.get("risk_family") or surface.get("family") or "").strip()
                name = str(surface.get("surface") or "").strip()
                if family and name:
                    matrix_surfaces.add((family, name))

    missing = sorted(CANONICAL - set(families))
    if missing:
        errors.append(f"risk saturation omits canonical families: {missing}")
    for family, item in families.items():
        if item.get("applicable") is True and (item.get("status") != "passed" or not item.get("control_ids")):
            errors.append(f"risk family {family} is applicable but unsaturated")
    if risk.get("material_families_missing_controls"):
        errors.append("risk saturation reports missing material controls")
    if inherited.get("unresolved_controls"):
        errors.append("inherited controls unresolved")
    for item in inherited.get("controls") or []:
        cid = item.get("id") if isinstance(item, dict) else "?"
        if not isinstance(item, dict) or item.get("status") != "passed" or item.get("head_sha") != a.head_sha:
            errors.append(f"inherited control {cid} not passed on candidate")
            continue
        if item.get("subject_sha") != a.head_sha:
            errors.append(f"inherited control {cid} subject_sha differs from candidate")
        family = str(item.get("risk_family") or "").strip()
        surface = str(item.get("surface") or "").strip()
        if family:
            if family not in matrix_families:
                errors.append(f"active inherited control {cid} requires risk family {family} omitted by attack matrix")
            risk_item = families.get(family)
            if not isinstance(risk_item, dict) or risk_item.get("applicable") is not True:
                errors.append(f"active inherited control {cid} requires risk family {family} but risk saturation marks it not applicable")
        conflicts = conflicting_current_sha_claims(item.get("observed"), a.head_sha)
        if conflicts:
            errors.append(f"inherited control {cid} observed narrative asserts non-current SHA(s) as current/exact-head: {conflicts}")
        if family and surface and (family, surface) not in matrix_surfaces:
            errors.append(f"active inherited control {cid} requires risk surface {family}:{surface} omitted by attack matrix")
    if errors:
        for e in errors:
            print(f"BLOCK: {e}")
        return 2
    print("READY: delivery packet is saturated and quantitative evidence is fresh enough to spend an independent audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
