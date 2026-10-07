#!/usr/bin/env python3
from __future__ import annotations

import argparse
import posixpath
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact

SHA_RE = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
KINDS = {"behavioral", "structural", "quantitative", "documentation"}
POLICIES = {"exact-material-head", "reusable"}


def load(path: Path) -> dict:
    try:
        value = load_json_artifact(path)
    except Exception as exc:
        raise SystemExit(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def safe_repo_path(value: object) -> bool:
    raw = str(value or "").replace("\\", "/").strip()
    normalized = posixpath.normpath(raw)
    return bool(raw) and not raw.startswith("/") and normalized not in {".", ".."} and not normalized.startswith("../")


def validate_manifest(payload: dict, material_head_sha: str) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("evidence provenance schema_version must be 1")
    declared_head = str(payload.get("material_head_sha") or "")
    if not SHA_RE.match(material_head_sha):
        errors.append("material head SHA is invalid")
    if declared_head != material_head_sha:
        errors.append("evidence provenance material_head_sha does not match frozen material head")
    base_sha = payload.get("base_sha")
    if base_sha not in (None, "") and not SHA_RE.match(str(base_sha)):
        errors.append("evidence provenance base_sha is invalid")

    entries = payload.get("evidence")
    if not isinstance(entries, list):
        errors.append("evidence provenance evidence must be an array")
        return errors
    seen: set[str] = set()
    for index, item in enumerate(entries):
        label = f"evidence provenance entry {index}"
        if not isinstance(item, dict):
            errors.append(f"{label} is invalid")
            continue
        evidence_id = str(item.get("evidence_id") or "").strip()
        if not evidence_id:
            errors.append(f"{label} lacks evidence_id")
        elif evidence_id in seen:
            errors.append(f"duplicate evidence_id {evidence_id}")
        else:
            seen.add(evidence_id)
        kind = str(item.get("kind") or "").strip()
        if kind not in KINDS:
            errors.append(f"{label} has invalid kind")
        if not safe_repo_path(item.get("path")):
            errors.append(f"{label} has invalid repository-relative path")
        if not SHA256_RE.match(str(item.get("sha256") or "")):
            errors.append(f"{label} lacks valid sha256")
        subject_sha = str(item.get("subject_sha") or "")
        if not SHA_RE.match(subject_sha):
            errors.append(f"{label} lacks valid subject_sha")
        policy = str(item.get("freshness_policy") or "")
        if policy not in POLICIES:
            errors.append(f"{label} has invalid freshness_policy")
        if len(str(item.get("producer") or "").strip()) < 3:
            errors.append(f"{label} lacks producer")
        if item.get("status") != "passed":
            errors.append(f"{label} is not passed")
        if policy == "exact-material-head" and subject_sha != material_head_sha:
            errors.append(f"{label} is stale: subject_sha does not match material head")
        if kind == "quantitative":
            if policy != "exact-material-head":
                errors.append(f"{label} quantitative evidence must use exact-material-head freshness")
            if subject_sha != material_head_sha:
                errors.append(f"{label} quantitative evidence was not measured on the material head")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-provenance", required=True)
    parser.add_argument("--material-head-sha", required=True)
    args = parser.parse_args()
    payload = load(Path(args.evidence_provenance))
    errors = validate_manifest(payload, args.material_head_sha)
    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print(f"READY: evidence provenance is fresh for material head {args.material_head_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
