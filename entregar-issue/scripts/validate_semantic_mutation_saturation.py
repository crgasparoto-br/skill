#!/usr/bin/env python3
"""Fail-closed, language-neutral validation of exact-head semantic saturation."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
from pathlib import Path

AXES = ("origin", "binding", "transformation", "control_flow", "consumption", "boundary")
EXPECTED = {"violation": "reject", "benign": "accept", "mutation": "reject"}
SHA = re.compile(r"^[0-9a-f]{40,64}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def check_file(root: Path, relative: object, digest: object, label: str,
               errors: list[str], *, json_proof: bool) -> dict:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        errors.append(f"{label}: invalid relative evidence path")
        return {}
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        errors.append(f"{label}: missing evidence or path escapes workspace")
        return {}
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        errors.append(f"{label}: invalid sha256")
        return {}
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        errors.append(f"{label}: sha256 mismatch")
        return {}
    if not json_proof:
        return {}
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        errors.append(f"{label}: invalid proof JSON")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label}: proof must be JSON object")
        return {}
    return value


def validate(manifest: dict, matrix: dict, root: Path, head: str) -> list[str]:
    errors: list[str] = []
    if not SHA.fullmatch(head):
        errors.append("invalid current head SHA")
    if manifest.get("schema_version") != 1 or manifest.get("head_sha") != head:
        errors.append("manifest schema or head is stale")
    if matrix.get("head_sha") != head:
        errors.append("attack matrix head is stale")
    required = set()
    for req in matrix.get("requirements", []):
        if not isinstance(req, dict):
            errors.append("invalid matrix requirement")
            continue
        for surface in req.get("risk_surfaces", []):
            if isinstance(surface, dict) and surface.get("semantic_saturation_required") is True:
                required.add((str(req.get("requirement_id") or ""),
                              str(surface.get("risk_family") or ""),
                              str(surface.get("surface") or "")))
    if not required:
        errors.append("no semantic saturation surfaces declared in attack matrix")
    rules = manifest.get("rules")
    if not isinstance(rules, list) or not rules:
        return errors + ["missing semantic saturation evidence rules"]
    seen = set()
    ids = set()
    for ri, rule in enumerate(rules):
        tag = f"rule {ri}"
        if not isinstance(rule, dict):
            errors.append(f"{tag}: invalid rule")
            continue
        identity = tuple(str(rule.get(k) or "") for k in ("requirement_id", "risk_family", "surface"))
        if identity in seen or identity not in required:
            errors.append(f"{tag}: duplicate or undeclared semantic surface")
        seen.add(identity)
        if rule.get("status") != "covered":
            errors.append(f"{tag}: required surface not covered")
        variants = rule.get("axis_variants")
        if not isinstance(variants, dict) or set(variants) != set(AXES):
            errors.append(f"{tag}: missing six axis variants")
            continue
        if any(not isinstance(variants[a], list) or not variants[a]
               or any(not isinstance(v, str) or not v.strip() for v in variants[a])
               or len(set(variants[a])) != len(variants[a]) for a in AXES):
            errors.append(f"{tag}: invalid axis variants")
            continue
        if all(len(variants[a]) == 1 for a in AXES):
            errors.append(f"{tag}: missing metamorphic variation")
        cases = rule.get("cases")
        if not isinstance(cases, list) or not cases:
            errors.append(f"{tag}: cases missing")
            continue
        covered = set()
        kinds = set()
        by_id = {}
        for ci, case in enumerate(cases):
            label = f"{tag} case {ci}"
            if not isinstance(case, dict):
                errors.append(f"{label}: invalid case")
                continue
            cid = case.get("id")
            if not isinstance(cid, str) or not cid or cid in ids:
                errors.append(f"{label}: missing or duplicated ID")
                continue
            ids.add(cid)
            by_id[cid] = case
            kind = case.get("kind")
            kinds.add(kind)
            verdict = EXPECTED.get(kind)
            if verdict is None or case.get("expected") != verdict or case.get("observed") != verdict:
                errors.append(f"{label}: mutant survivor, false positive or incorrect oracle")
            if case.get("status") != "passed" or case.get("head_sha") != head:
                errors.append(f"{label}: not executed on exact head")
            if kind == "mutation" and not str(case.get("mutation_id") or "").strip():
                errors.append(f"{label}: missing mutation ID")
            procedure = case.get("procedure")
            if not isinstance(procedure, str) or len(procedure.strip()) < 12:
                errors.append(f"{label}: non-reproducible procedure")
            axes = case.get("axes")
            if not isinstance(axes, dict) or set(axes) != set(AXES):
                errors.append(f"{label}: incomplete axis values")
                continue
            if any(axes[a] not in variants[a] for a in AXES):
                errors.append(f"{label}: undeclared axis value")
                continue
            for a, b in itertools.combinations(AXES, 2):
                covered.add((a, axes[a], b, axes[b]))
            proof = check_file(root, case.get("proof_path"), case.get("proof_sha256"),
                               label, errors, json_proof=True)
            if (proof.get("case_id") != cid or proof.get("head_sha") != head
                    or proof.get("observed") != case.get("observed")
                    or proof.get("procedure") != procedure):
                errors.append(f"{label}: proof contradicts recorded result")
            check_file(root, case.get("source_path"), case.get("source_sha256"),
                       label, errors, json_proof=False)
        for kind in EXPECTED:
            if kind not in kinds:
                errors.append(f"{tag}: missing {kind} control")
        for a, b in itertools.combinations(AXES, 2):
            for va, vb in itertools.product(variants[a], variants[b]):
                if (a, va, b, vb) not in covered:
                    errors.append(f"{tag}: uncovered pairwise {a}={va} x {b}={vb}")
        pairs = rule.get("metamorphic_pairs")
        if not isinstance(pairs, list) or not pairs:
            errors.append(f"{tag}: metamorphic pairs missing")
        else:
            for pair in pairs:
                if (not isinstance(pair, list) or len(pair) != 2
                        or pair[0] not in by_id or pair[1] not in by_id or pair[0] == pair[1]):
                    errors.append(f"{tag}: invalid metamorphic pair")
                    continue
                left, right = by_id[pair[0]], by_id[pair[1]]
                if (left.get("axes") == right.get("axes")
                        or any(case.get("observed") != "reject"
                               or case.get("kind") not in ("violation", "mutation")
                               for case in (left, right))):
                    errors.append(f"{tag}: metamorphic pair not discriminating")
    if required - seen:
        errors.append(f"omitted semantic surfaces: {sorted(required - seen)}")
    return errors


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--attack-matrix", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--root", default=".")
    a = p.parse_args()
    try:
        errors = validate(load(Path(a.manifest)), load(Path(a.attack_matrix)),
                          Path(a.root).resolve(), a.head_sha)
    except (OSError, ValueError, TypeError) as exc:
        errors = [f"missing or invalid evidence: {exc}"]
    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print("READY: exact-head semantic mutation, benign controls and pairwise coverage verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
