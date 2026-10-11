#!/usr/bin/env python3
"""Fail-closed terminal findings gate; evidence is provided by a separate verifier."""
import argparse
import json
import re
from pathlib import Path

SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
APPLICABLE = {"blocking", "actionable-recommendation"}
DISPOSITIONS = APPLICABLE | {"optional-recommendation", "out-of-scope", "invalid-finding"}
STATES = {"open", "implementing", "implemented-unverified", "verified", "blocked", "not-applicable"}


def validate(data, manifest=None, attestation=None):
    errors = []
    if not isinstance(data, dict):
        return False, ["ledger must be an object"]
    head = data.get("head_sha")
    if not isinstance(head, str) or not SHA_RE.fullmatch(head):
        errors.append("invalid head_sha")
    if not isinstance(manifest, dict):
        errors.append("trusted audit manifest required")
        manifest = {}
    if not isinstance(attestation, dict):
        errors.append("independently verified attestation required")
        attestation = {}
    identity = ("repository", "pr_number", "audit_round")
    for key in identity:
        if not data.get(key) or data.get(key) != manifest.get(key) or data.get(key) != attestation.get(key):
            errors.append(f"{key}: identity mismatch")
    expected = manifest.get("finding_ids")
    if not isinstance(expected, list) or not expected or any(not isinstance(i, str) or not i.strip() for i in expected) or len(set(expected)) != len(expected):
        errors.append("trusted manifest finding_ids invalid")
        expected = []
    findings = data.get("findings")
    if not isinstance(findings, list) or not findings:
        return False, errors + ["findings must be nonempty"]
    seen = set()
    for index, finding in enumerate(findings):
        if not isinstance(finding, dict):
            errors.append(f"findings[{index}] invalid")
            continue
        fid = finding.get("finding_id")
        if not isinstance(fid, str) or not fid.strip() or fid in seen:
            errors.append(f"findings[{index}] missing/duplicate finding_id")
            continue
        seen.add(fid)
        disposition, status = finding.get("disposition"), finding.get("status")
        if disposition not in DISPOSITIONS or status not in STATES:
            errors.append(f"{fid}: invalid disposition/status")
            continue
        if disposition in APPLICABLE:
            if status != "verified":
                errors.append(f"{fid}: applicable finding not verified")
            if finding.get("evidence_head_sha") != head or not finding.get("validation_evidence"):
                errors.append(f"{fid}: missing exact-head evidence")
            verified = attestation.get("verified_findings")
            if not isinstance(verified, dict) or verified.get(fid) != head:
                errors.append(f"{fid}: evidence not independently verified")
        elif disposition in {"out-of-scope", "invalid-finding", "optional-recommendation"}:
            if status != "not-applicable" or not finding.get("justification"):
                errors.append(f"{fid}: non-applicable disposition requires documented decision")
            decisions = attestation.get("accepted_exclusions")
            if not isinstance(decisions, list) or fid not in decisions:
                errors.append(f"{fid}: exclusion not independently accepted")
    if set(expected) != seen:
        errors.append("findings differ from trusted audit manifest")
    if attestation.get("head_sha") != head:
        errors.append("attestation head mismatch")
    ci = attestation.get("ci")
    if not isinstance(ci, dict) or ci.get("head_sha") != head or ci.get("conclusion") != "success" or not ci.get("run_url"):
        errors.append("trusted exact-head CI evidence missing")
    if attestation.get("independent_audit") != "approved" or not attestation.get("auditor") or not attestation.get("audit_url") or attestation.get("implementer") == attestation.get("auditor"):
        errors.append("independent auditor approval not demonstrated")
    return not errors, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--manifest", type=Path, required=True, help="Audit findings manifest fetched independently")
    parser.add_argument("--attestation", type=Path, required=True, help="Evidence verified separately against GitHub APIs")
    args = parser.parse_args()
    try:
        ok, reasons = validate(*(json.loads(p.read_text(encoding="utf-8")) for p in (args.ledger, args.manifest, args.attestation)))
    except (OSError, ValueError, TypeError) as exc:
        ok, reasons = False, [f"invalid input: {exc}"]
    print(json.dumps({"verdict": "CONCLUIDO" if ok else "NAO_CONCLUIDO", "reasons": reasons}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
