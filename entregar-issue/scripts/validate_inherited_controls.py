#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact

from handoff_semantic_guards import conflicting_current_sha_claims
from risk_inference import (
    required_canonical_families_from_closure,
    required_canonical_surfaces_from_closure,
)

CONTROL_TYPES = {"test", "gate", "scenario", "procedure"}
RETIREMENT_DISPOSITIONS = {"superseded", "not-applicable"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
GENERIC_PASS_RE = re.compile(
    r"^(?:ci|workflow|pipeline)\s+(?:is\s+)?(?:green|passed)|^no\s+(?:diff|change|regression)|"
    r"^(?:unchanged|same\s+as\s+before|not\s+touched|still\s+passes?)\.?$",
    re.I,
)


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def meaningful(value: object, minimum: int, label: str, errors: list[str]) -> str:
    text = str(value or "").strip()
    if len(text) < minimum:
        errors.append(f"{label} is missing or too short")
    if text and GENERIC_PASS_RE.search(text):
        errors.append(f"{label} is generic pass-through evidence rather than a discriminant execution")
    return text


def matrix_controls(matrix: dict | None) -> tuple[set[str], set[tuple[str, str, str]]]:
    ids: set[str] = set()
    dimensions: set[tuple[str, str, str]] = set()
    if matrix is None:
        return ids, dimensions
    for requirement in matrix.get("requirements") or []:
        if not isinstance(requirement, dict):
            continue
        for control in requirement.get("negative_controls") or []:
            if not isinstance(control, dict):
                continue
            cid = str(control.get("id") or "").strip()
            family = str(control.get("risk_family") or "").strip()
            surface = str(control.get("surface") or "").strip()
            dimension = str(control.get("dimension") or "").strip()
            if cid:
                ids.add(cid)
            if family and surface and dimension:
                dimensions.add((family, surface, dimension))
            for sibling in control.get("sibling_cases") or []:
                if not isinstance(sibling, dict):
                    continue
                ssurface = str(sibling.get("surface") or "").strip()
                sdimension = str(sibling.get("dimension") or "").strip()
                if family and ssurface and sdimension:
                    dimensions.add((family, ssurface, sdimension))
    return ids, dimensions


def audit_key(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def controls_by_id(data: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in data.get("controls") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if cid:
            result[cid] = item
    return result


def retired_controls_by_id(data: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in data.get("retired_controls") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if cid:
            result[cid] = item
    return result


def validate_retirement(
    item: dict,
    *,
    head_sha: str,
    active_controls: dict[str, dict],
    previous_id: str,
    previous_control: dict,
    required_families: set[str],
    required_surfaces: set[tuple[str, str]],
    errors: list[str],
) -> None:
    label = f"retired inherited control {previous_id}"
    if str(item.get("id") or "").strip() != previous_id:
        errors.append(f"{label} id mismatch")
    disposition = str(item.get("disposition") or "").strip()
    if disposition not in RETIREMENT_DISPOSITIONS:
        errors.append(f"{label} has invalid disposition")
        return
    meaningful(item.get("reason"), 20, f"{label} reason", errors)
    if item.get("subject_sha") != head_sha:
        errors.append(f"{label} subject_sha differs from candidate")
    evidence = meaningful(item.get("evidence"), 3, f"{label} evidence", errors)
    if evidence and GENERIC_PASS_RE.search(evidence):
        errors.append(f"{label} evidence cannot be generic CI/diff status")
    if not SHA256_RE.match(str(item.get("evidence_sha256") or "").strip()):
        errors.append(f"{label} lacks valid evidence_sha256")
    meaningful(item.get("procedure"), 12, f"{label} procedure", errors)
    meaningful(item.get("expected"), 8, f"{label} expected", errors)
    meaningful(item.get("observed"), 8, f"{label} observed", errors)

    replacement = str(item.get("replacement_control_id") or "").strip()
    if disposition == "superseded":
        if not replacement:
            errors.append(f"{label} superseded disposition requires replacement_control_id")
        elif replacement == previous_id:
            errors.append(f"{label} replacement_control_id must differ from retired id")
        elif replacement not in active_controls:
            errors.append(f"{label} replacement control {replacement} is not active on candidate")
        elif active_controls[replacement].get("status") != "passed":
            errors.append(f"{label} replacement control {replacement} is not passed")
    elif replacement:
        errors.append(f"{label} not-applicable disposition must not declare replacement_control_id")

    if disposition == "not-applicable":
        previous_family = str(previous_control.get("risk_family") or "").strip()
        previous_surface = str(previous_control.get("surface") or "").strip()
        if previous_family and previous_family in required_families:
            errors.append(
                f"{label} cannot become not-applicable while canonical requirement closure still requires risk family {previous_family}"
            )
        if previous_family and previous_surface and (previous_family, previous_surface) in required_surfaces:
            errors.append(
                f"{label} cannot become not-applicable while canonical requirement closure still requires surface "
                f"{previous_family}:{previous_surface}"
            )


def validate_monotonic_lineage(
    current: dict,
    previous: dict,
    *,
    head_sha: str,
    required_families: set[str],
    required_surfaces: set[tuple[str, str]],
    historical_controls: dict[str, dict] | None = None,
    errors: list[str],
) -> None:
    active = controls_by_id(current)
    prior_active = controls_by_id(previous)
    prior_retired = retired_controls_by_id(previous)
    retired_entries = current.get("retired_controls") or []
    retired: dict[str, dict] = {}
    for index, item in enumerate(retired_entries):
        if not isinstance(item, dict):
            errors.append(f"retired inherited control {index} is invalid")
            continue
        cid = str(item.get("id") or "").strip()
        if not cid:
            errors.append(f"retired inherited control {index} lacks id")
            continue
        if cid in retired:
            errors.append(f"retired inherited control {cid} is duplicated")
        retired[cid] = item

    prior_ids = set(prior_active) | set(prior_retired)
    missing = sorted(prior_ids - set(active) - set(retired))
    for cid in missing:
        errors.append(f"inherited control {cid} disappeared from cumulative lineage without explicit disposition")

    for cid in sorted(prior_ids & set(retired)):
        if cid in active:
            errors.append(f"inherited control {cid} cannot be both active and retired")

    for cid, item in retired.items():
        previous_control = prior_active.get(cid) or prior_retired.get(cid)
        if previous_control is None and historical_controls:
            previous_control = historical_controls.get(cid)
        if previous_control is None:
            errors.append(f"retired inherited control {cid} does not exist in previous or trusted historical snapshot")
            continue
        validate_retirement(
            item,
            head_sha=head_sha,
            active_controls=active,
            previous_id=cid,
            previous_control=previous_control,
            required_families=required_families,
            required_surfaces=required_surfaces,
            errors=errors,
        )

    previous_audits = {audit_key(item) for item in previous.get("source_audits") or []}
    current_audits = {audit_key(item) for item in current.get("source_audits") or []}
    dropped_audits = sorted(previous_audits - current_audits)
    if dropped_audits:
        errors.append("source_audits is not cumulative; previous audit entries disappeared")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--inherited-controls", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--attack-matrix")
    p.add_argument("--requirement-closure")
    p.add_argument("--previous-independent-rejection", action="store_true")
    p.add_argument("--previous-inherited-controls")
    p.add_argument("--historical-inherited-controls", action="append", default=[])
    a = p.parse_args()

    path = Path(a.inherited_controls)
    if not path.is_file():
        print("BLOCK: inherited-controls.json is missing")
        return 2
    data = load(path)
    errors: list[str] = []
    matrix = load(Path(a.attack_matrix)) if a.attack_matrix else None
    attack_ids, attack_dimensions = matrix_controls(matrix)
    required_families: set[str] = set()
    required_surfaces: set[tuple[str, str]] = set()
    if a.requirement_closure:
        closure_path = Path(a.requirement_closure)
        if not closure_path.is_file():
            errors.append("requirement closure for inherited-control retirement validation is missing")
        else:
            closure = load(closure_path)
            required_families = required_canonical_families_from_closure(closure)
            required_surfaces = required_canonical_surfaces_from_closure(closure)
            documentation = closure.get("documentation_consistency") or {}
            if documentation.get("status") == "passed":
                required_families.add("documentation")

    if data.get("schema_version") != 1:
        errors.append("inherited controls schema_version must be 1")
    if data.get("head_sha") != a.head_sha:
        errors.append("inherited controls head_sha does not match candidate")
    controls = data.get("controls") or []
    if a.previous_independent_rejection and not data.get("source_audits"):
        errors.append("previous independent rejection requires source_audits")
    if a.previous_independent_rejection and not controls:
        errors.append("previous independent rejection requires inherited controls")
    if a.previous_independent_rejection and not a.previous_inherited_controls:
        errors.append("previous independent rejection requires previous inherited-controls snapshot for monotonic validation")

    seen_ids: set[str] = set()
    for idx, item in enumerate(controls):
        if not isinstance(item, dict):
            errors.append(f"inherited control {idx} is invalid")
            continue
        cid = str(item.get("id") or idx)
        if cid in seen_ids:
            errors.append(f"inherited control {cid} is duplicated")
        seen_ids.add(cid)
        label = f"inherited control {cid}"
        if item.get("status") != "passed":
            errors.append(f"{label} is not passed")
        if item.get("head_sha") != a.head_sha:
            errors.append(f"{label} head_sha differs from candidate")
        if item.get("subject_sha") != a.head_sha:
            errors.append(f"{label} subject_sha differs from candidate")
        evidence = meaningful(item.get("evidence"), 3, f"{label} evidence", errors)
        if evidence and GENERIC_PASS_RE.search(evidence):
            errors.append(f"{label} evidence cannot be generic CI/diff status")
        evidence_sha = str(item.get("evidence_sha256") or "").strip()
        if not SHA256_RE.match(evidence_sha):
            errors.append(f"{label} lacks valid evidence_sha256")
        if str(item.get("control_type") or "") not in CONTROL_TYPES:
            errors.append(f"{label} has invalid control_type")
        meaningful(item.get("procedure"), 12, f"{label} procedure", errors)
        meaningful(item.get("expected"), 8, f"{label} expected", errors)
        observed = meaningful(item.get("observed"), 8, f"{label} observed", errors)
        conflicting_shas = conflicting_current_sha_claims(observed, a.head_sha)
        if conflicting_shas:
            errors.append(
                f"{label} observed narrative asserts non-current SHA(s) as current/exact-head: {conflicting_shas}"
            )

        attack_control_id = str(item.get("attack_control_id") or "").strip()
        if attack_control_id and matrix is not None and attack_control_id not in attack_ids:
            errors.append(f"{label} references unknown attack_control_id {attack_control_id}")

        family = str(item.get("risk_family") or "").strip()
        surface = str(item.get("surface") or "").strip()
        dimension = str(item.get("dimension") or "").strip()
        if any((family, surface, dimension)) and not all((family, surface, dimension)):
            errors.append(f"{label} risk binding must include risk_family, surface and dimension together")
        if family and surface and dimension and matrix is not None:
            if (family, surface, dimension) not in attack_dimensions:
                errors.append(f"{label} risk binding is not executed in the current attack matrix")

    historical_controls: dict[str, dict] = {}
    for historical_name in a.historical_inherited_controls:
        historical_path = Path(historical_name)
        if not historical_path.is_file():
            errors.append(f"historical inherited-controls snapshot is missing: {historical_name}")
            continue
        historical = load(historical_path)
        historical_controls.update(controls_by_id(historical))
        historical_controls.update(retired_controls_by_id(historical))

    if a.previous_inherited_controls:
        previous_path = Path(a.previous_inherited_controls)
        if not previous_path.is_file():
            errors.append("previous inherited-controls snapshot is missing")
        else:
            previous = load(previous_path)
            validate_monotonic_lineage(
                data,
                previous,
                head_sha=a.head_sha,
                required_families=required_families,
                required_surfaces=required_surfaces,
                historical_controls=historical_controls,
                errors=errors,
            )

    if data.get("unresolved_controls"):
        errors.append("inherited controls has unresolved_controls")
    if errors:
        for e in errors:
            print(f"BLOCK: {e}")
        return 2
    print("READY: cumulative inherited audit controls have monotonic discriminant exact-head lineage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
