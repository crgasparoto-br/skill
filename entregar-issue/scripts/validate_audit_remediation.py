#!/usr/bin/env python3
"""Validate one-to-one remediation and exact replay of deterministic failed gates."""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact

VERSION = "2026-08-20.3"
MODES = {"targeted-remediation", "systemic-remediation"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_command(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def failed_gate(item: dict) -> dict | None:
    value = item.get("failed_gate")
    if not isinstance(value, dict) or value.get("deterministic") is not True:
        return None
    command = normalize_command(value.get("command"))
    if not command:
        return None
    return {
        "name": str(value.get("name") or "deterministic-gate"),
        "command": command,
        "subject_sha": str(value.get("subject_sha") or ""),
        "exit_code": value.get("observed_exit_code"),
        "evidence_sha256": str(value.get("evidence_sha256") or ""),
    }


def normalize_source(report: dict) -> tuple[str, str, list[dict]]:
    rejection = str(report.get("rejection_id") or "").strip()
    audited_head = str(report.get("head_sha") or (report.get("identity") or {}).get("head_sha") or "").strip()
    items: list[dict] = []
    for finding in report.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        fid = str(finding.get("id") or "").strip()
        if not fid:
            continue
        disposition = str(finding.get("disposition") or "blocking")
        status = str(finding.get("status") or "open")
        if status == "closed":
            continue
        actionable = finding.get("actionable") is not False
        kind = "recommendation" if disposition == "recommendation" else "finding"
        if kind == "finding" or actionable:
            items.append({
                "source_kind": kind,
                "source_id": fid,
                "remediation_mode": str(finding.get("remediation_mode") or "targeted-remediation"),
                "failed_gate": failed_gate(finding),
            })
    for recommendation in report.get("recommendations") or []:
        if not isinstance(recommendation, dict) or recommendation.get("actionable") is False:
            continue
        rid = str(recommendation.get("id") or "").strip()
        if rid:
            items.append({
                "source_kind": "recommendation",
                "source_id": rid,
                "remediation_mode": str(recommendation.get("remediation_mode") or "targeted-remediation"),
                "failed_gate": failed_gate(recommendation),
            })
    return rejection, audited_head, items


def validate_gate_replay(item: dict, expected_gate: dict, head_sha: str, label: str, errors: list[str]) -> None:
    if item.get("closure_kind") != "deterministic-gate-replay":
        errors.append(f"{label} deterministic failed gate requires closure_kind=deterministic-gate-replay")
        return
    original = item.get("original_failed_gate")
    replay = item.get("revalidation")
    if not isinstance(original, dict):
        errors.append(f"{label} lacks original_failed_gate")
        return
    if not isinstance(replay, dict):
        errors.append(f"{label} lacks revalidation")
        return
    expected_command = expected_gate["command"]
    if normalize_command(original.get("command")) != expected_command:
        errors.append(f"{label} original failed gate command differs from audit result")
    if normalize_command(replay.get("command")) != expected_command:
        errors.append(f"{label} must replay the exact failed gate command")
    if replay.get("equivalence") != "exact-command-replay":
        errors.append(f"{label} gate replay equivalence must be exact-command-replay")
    if replay.get("subject_sha") != head_sha:
        errors.append(f"{label} gate replay subject_sha differs from candidate")
    if replay.get("exit_code") != 0:
        errors.append(f"{label} gate replay must exit 0")
    if not SHA256_RE.fullmatch(str(replay.get("evidence_sha256") or "")):
        errors.append(f"{label} gate replay lacks valid evidence_sha256")
    if original.get("exit_code") == 0:
        errors.append(f"{label} original failed gate exit_code must be non-zero")
    if expected_gate.get("exit_code") is not None and original.get("exit_code") != expected_gate.get("exit_code"):
        errors.append(f"{label} original failed gate exit_code differs from audit result")
    expected_evidence = expected_gate.get("evidence_sha256") or ""
    if expected_evidence and SHA256_RE.fullmatch(expected_evidence):
        if original.get("evidence_sha256") != expected_evidence:
            errors.append(f"{label} original failed gate evidence hash differs from audit result")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--audit-result", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()
    errors: list[str] = []
    ledger_path = Path(args.ledger)
    report_path = Path(args.audit_result)
    try:
        ledger = load(ledger_path)
        report = load(report_path)
    except Exception as exc:
        print(f"BLOCK: invalid audit remediation input: {exc}")
        return 2

    if ledger.get("schema_version") != 1:
        errors.append("audit remediation schema_version must be 1")
    if ledger.get("contract_version") != VERSION:
        errors.append(f"audit remediation contract_version must be {VERSION}")
    if ledger.get("resolution_policy") != "all-actionable-items":
        errors.append("audit remediation resolution_policy must be all-actionable-items")
    if ledger.get("status") != "closed":
        errors.append("audit remediation ledger is not closed")
    if ledger.get("candidate_head_sha") != args.head_sha:
        errors.append("audit remediation candidate_head_sha differs from candidate")

    rejection, audited_head, expected = normalize_source(report)
    source = ledger.get("source") or {}
    if rejection and source.get("rejection_id") != rejection:
        errors.append("audit remediation rejection_id differs from audit result")
    if audited_head and source.get("audited_head_sha") != audited_head:
        errors.append("audit remediation audited_head_sha differs from audit result")
    if source.get("audit_report_sha256") != sha256(report_path):
        errors.append("audit remediation audit_report_sha256 differs from source bytes")

    seen: dict[tuple[str, str], dict] = {}
    duplicates: list[str] = []
    for item in ledger.get("items") or []:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("source_kind") or ""), str(item.get("source_id") or ""))
        if key in seen:
            duplicates.append(":".join(key))
        seen[key] = item
    if duplicates:
        errors.append("duplicate remediation items: " + ", ".join(sorted(duplicates)))

    expected_keys = {(item["source_kind"], item["source_id"]): item for item in expected}
    missing = sorted(f"{key[0]}:{key[1]}" for key in expected_keys if key not in seen)
    if missing:
        errors.append("actionable audit items missing from remediation ledger: " + ", ".join(missing))

    for key, exp in expected_keys.items():
        item = seen.get(key)
        if not item:
            continue
        label = f"{key[0]} {key[1]}"
        mode = str(item.get("remediation_mode") or "")
        if mode not in MODES:
            errors.append(f"{label} has invalid remediation_mode")
        if exp["remediation_mode"] in MODES and mode != exp["remediation_mode"]:
            errors.append(f"{label} remediation_mode differs from audit result")
        if item.get("status") != "fixed":
            errors.append(f"{label} is actionable and must be fixed")
        if not item.get("evidence"):
            errors.append(f"{label} lacks closure evidence")
        if not item.get("validations"):
            errors.append(f"{label} lacks closure validations")
        if exp.get("failed_gate"):
            validate_gate_replay(item, exp["failed_gate"], args.head_sha, label, errors)

    expected_systemic = any(item["remediation_mode"] == "systemic-remediation" for item in expected)
    expected_targeted = any(item["remediation_mode"] == "targeted-remediation" for item in expected)
    expected_mode = "mixed-remediation" if expected_systemic and expected_targeted else ("systemic-remediation" if expected_systemic else "targeted-remediation")
    if expected and ledger.get("remediation_mode") != expected_mode:
        errors.append(f"audit remediation mode must be {expected_mode}")

    if errors:
        for error in errors:
            print("BLOCK: " + error)
        return 2
    gate_count = sum(1 for item in expected if item.get("failed_gate"))
    print(f"READY: {len(expected)} actionable audit items closed on {args.head_sha}; exact_failed_gate_replays={gate_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
