#!/usr/bin/env python3
"""Cross-check the latest independent rejection against the cumulative escape ledger."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact
from handoff_postcondition_records import escape_key, validated_preparation_plan

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


def represented_closures(matches: list[dict], plan: dict | None, report_sha: str, rejection_id: str, errors: list[str]) -> tuple[set[str], bool]:
    represented_findings: set[str] = set()
    matching_report = not report_sha
    for item in matches:
        audit = item.get("source_audit") or {}
        represented_findings.update(source_finding_ids(audit))
        if report_sha and str(audit.get("audit_report_sha256") or "").strip().lower() == report_sha.lower():
            matching_report = True
        prepared = plan is not None and escape_key(item, plan) is not None
        if not prepared and item.get("status") != "passed":
            errors.append(f"independent rejection {rejection_id} is represented by an escape that is not passed")
    return represented_findings, matching_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--learning-closure", required=True)
    parser.add_argument("--closure", required=True)
    parser.add_argument("--phase", choices=("final", "preparation"), default="final")
    parser.add_argument("--postcondition-plan", type=Path)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--audit-result", type=Path)
    parser.add_argument("--audit-remediation", type=Path)
    parser.add_argument("--head-sha")
    parser.add_argument("--base-sha")
    args = parser.parse_args()

    try:
        learning = load(Path(args.learning_closure))
        closure = load(Path(args.closure))
        plan = validated_preparation_plan(
            phase=args.phase, plan_path=args.postcondition_plan, audit_result=args.audit_result,
            ledger_path=args.audit_remediation, repository=args.repository, head_sha=args.head_sha,
            base_sha=args.base_sha,
            escape_closure=closure,
        )
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
    if plan is not None and (rejection_id != plan.get("rejection_id") or report_sha != plan.get("audit_report_sha256")):
        errors.append("preparation learning event differs from the immutable source audit")

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

    represented_findings, matching_report = represented_closures(matches, plan, report_sha, rejection_id, errors)

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
    if plan is not None:
        print(f"PREPARED: independent rejection {rejection_id} retains explicit blocked certificate postconditions")
    else:
        print(f"READY: independent rejection {rejection_id} is explicitly closed in the cumulative audit escape ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
