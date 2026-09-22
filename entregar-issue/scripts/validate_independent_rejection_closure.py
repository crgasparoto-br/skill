#!/usr/bin/env python3
"""Cross-check the latest independent rejection against the cumulative escape ledger."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact

REJECTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def escape_entries(data: dict) -> list[dict]:
    raw = data.get("escapes") if isinstance(data.get("escapes"), list) else [data]
    return [item for item in raw if isinstance(item, dict)]


def independent_rejection(kind: object) -> bool:
    value = str(kind or "").strip().lower().replace("_", "-")
    return "independent" in value and "rejection" in value


def normalized_finding_ids(source: dict) -> set[str]:
    result = {str(item).strip() for item in source.get("finding_ids") or [] if str(item).strip()}
    single = str(source.get("finding_id") or "").strip()
    if single:
        result.add(single)
    return result


def source_finding_ids(source: dict) -> set[str]:
    result = {str(item).strip() for item in source.get("finding_ids") or [] if str(item).strip()}
    single = str(source.get("finding_id") or "").strip()
    if single:
        result.add(single)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--learning-closure", required=True)
    parser.add_argument("--closure", required=True)
    args = parser.parse_args()

    try:
        learning = load(Path(args.learning_closure))
        closure = load(Path(args.closure))
    except Exception as exc:
        print(f"BLOCK: invalid independent rejection closure input: {exc}")
        return 2

    errors: list[str] = []
    source = learning.get("source_event")
    if not isinstance(source, dict):
        errors.append("learning closure lacks source_event")
        source = {}

    if not independent_rejection(source.get("kind")):
        errors.append("learning closure source_event is not an independent rejection")

    rejection_id = str(source.get("rejection_id") or "").strip()
    if not REJECTION_ID_RE.fullmatch(rejection_id):
        errors.append("independent rejection source_event lacks stable rejection_id")

    report_sha = str(source.get("audit_report_sha256") or "").strip()
    if report_sha and not SHA256_RE.fullmatch(report_sha):
        errors.append("independent rejection source_event audit_report_sha256 is invalid")

    expected_findings = normalized_finding_ids(source)
    matches: list[dict] = []
    for item in escape_entries(closure):
        audit = item.get("source_audit")
        if not isinstance(audit, dict):
            continue
        if str(audit.get("rejection_id") or "").strip() == rejection_id and rejection_id:
            matches.append(item)

    if rejection_id and not matches:
        errors.append(f"independent rejection {rejection_id} has no audit escape closure")

    represented_findings: set[str] = set()
    matching_report = not report_sha
    for item in matches:
        audit = item.get("source_audit") or {}
        represented_findings.update(source_finding_ids(audit))
        if report_sha and str(audit.get("audit_report_sha256") or "").strip().lower() == report_sha.lower():
            matching_report = True
        if item.get("status") != "passed":
            errors.append(f"independent rejection {rejection_id} is represented by an escape that is not passed")

    missing_findings = sorted(expected_findings - represented_findings)
    if missing_findings:
        errors.append(
            f"independent rejection {rejection_id} lacks audit escape closure for finding ids: "
            + ", ".join(missing_findings)
        )
    if matches and report_sha and not matching_report:
        errors.append(f"independent rejection {rejection_id} audit report hash is not bound to its escape closure")

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print(f"READY: independent rejection {rejection_id} is explicitly closed in the cumulative audit escape ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
