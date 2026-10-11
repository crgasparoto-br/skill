#!/usr/bin/env python3
"""Validate terminal completion against an exhaustive exact-HEAD findings ledger."""
import argparse
import json
import re
from pathlib import Path

APPLICABLE = {"blocking", "actionable-recommendation"}
DISPOSITIONS = APPLICABLE | {"optional-recommendation", "out-of-scope", "invalid-finding"}
STATES = {"open", "implementing", "implemented-unverified", "verified", "blocked", "not-applicable"}

def validate(data):
    errors = []
    head = data.get("head_sha")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        errors.append("head_sha must be a full lowercase hexadecimal SHA")
    findings = data.get("findings")
    if not isinstance(findings, list) or not findings:
        return False, errors + ["findings must be a nonempty exhaustive ledger"]
    previous = data.get("previous_finding_ids", [])
    if not isinstance(previous, list) or any(not isinstance(i, str) for i in previous):
        errors.append("previous_finding_ids must be strings")
        previous = []
    seen = set()
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"findings[{index}] must be an object")
            continue
        fid = finding.get("finding_id")
        if not isinstance(fid, str) or not fid.strip() or fid in seen:
            errors.append(f"findings[{index}]: missing/duplicate finding_id")
        else:
            seen.add(fid)
        disposition = finding.get("disposition")
        status = finding.get("status")
        if disposition not in DISPOSITIONS or status not in STATES:
            errors.append(f"{fid}: invalid disposition/status")
            continue
        if disposition in APPLICABLE:
            if status != "verified":
                errors.append(f"{fid}: applicable finding not verified ({status})")
            if finding.get("evidence_head_sha") != head or not finding.get("validation_evidence"):
                errors.append(f"{fid}: missing exact-head validation evidence")
        elif disposition in {"out-of-scope", "invalid-finding"}:
            if status != "not-applicable" or not finding.get("justification"):
                errors.append(f"{fid}: exclusion needs not-applicable and justification")
        elif not finding.get("justification"):
            errors.append(f"{fid}: optional classification needs justification")
    missing = set(previous) - seen
    if missing:
        errors.append("previous findings omitted: " + ", ".join(sorted(missing)))
    ci = data.get("ci")
    if not isinstance(ci, dict) or ci.get("head_sha") != head or ci.get("conclusion") != "success":
        errors.append("required CI must succeed at exact HEAD")
    if data.get("independent_audit") != "approved":
        errors.append("independent audit approval not demonstrated")
    return not errors, errors

def main():
    p = argparse.ArgumentParser()
    p.add_argument("ledger", type=Path)
    args = p.parse_args()
    try:
        ok, reasons = validate(json.loads(args.ledger.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        ok, reasons = False, [f"invalid ledger: {exc}"]
    print(json.dumps({"verdict": "CONCLUIDO" if ok else "NAO_CONCLUIDO", "reasons": reasons}, ensure_ascii=False))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
