#!/usr/bin/env python3
"""Validate one-to-one remediation and exact replay of deterministic failed gates."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact
from handoff_postcondition_records import pending_ledger_errors, phase_plan, planned_items, preparation_ledger_schema
from jsonschema import Draft202012Validator

VERSION = "2026-08-20.3"
MODES = {"targeted-remediation", "systemic-remediation"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "audit-remediation.schema.json"


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


def validate_gate_replay(item: dict, expected_gate: dict, head_sha: str, label: str, errors: list[str], *, preparation: bool = False) -> None:
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
    if original.get("name") != expected_gate["name"]:
        errors.append(f"{label} original failed gate name differs from audit result")
    if expected_gate.get("subject_sha") and original.get("subject_sha") != expected_gate["subject_sha"]:
        errors.append(f"{label} original failed gate subject differs from audit result")
    if normalize_command(original.get("command")) != expected_command:
        errors.append(f"{label} original failed gate command differs from audit result")
    if normalize_command(replay.get("command")) != expected_command:
        errors.append(f"{label} must replay the exact failed gate command")
    if replay.get("equivalence") != "exact-command-replay":
        errors.append(f"{label} gate replay equivalence must be exact-command-replay")
    if replay.get("subject_sha") != head_sha:
        errors.append(f"{label} gate replay subject_sha differs from candidate")
    if preparation:
        if replay.get("exit_code") is not None or replay.get("evidence_sha256") is not None or replay.get("status") != "not-passed":
            errors.append(f"{label} prepared replay must retain null exit/hash and not-passed status")
    else:
        if replay.get("exit_code") != 0:
            errors.append(f"{label} gate replay must exit 0")
        if not SHA256_RE.fullmatch(str(replay.get("evidence_sha256") or "")):
            errors.append(f"{label} gate replay lacks valid evidence_sha256")
    if original.get("exit_code") == 0:
        errors.append(f"{label} original failed gate exit_code must be non-zero")
    if expected_gate.get("exit_code") is not None and original.get("exit_code") != expected_gate.get("exit_code"):
        errors.append(f"{label} original failed gate exit_code differs from audit result")
    expected_evidence = expected_gate.get("evidence_sha256") or ""
    if expected_evidence and SHA256_RE.fullmatch(expected_evidence) and original.get("evidence_sha256") != expected_evidence:
        errors.append(f"{label} original failed gate evidence hash differs from audit result")


def validate_ledger_identity(ledger: dict, report: dict, report_sha256: str, head_sha: str, plan: dict | None, errors: list[str]) -> None:
    schema_data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if plan is not None:
        schema_data = preparation_ledger_schema(schema_data, plan)
        errors.extend(pending_ledger_errors(ledger, plan, report_sha256, head_sha))
    schema = Draft202012Validator(schema_data)
    for error in sorted(schema.iter_errors(ledger), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        errors.append(f"audit remediation schema violation at {location}: {error.message}")
    if ledger.get("schema_version") != 1:
        errors.append("audit remediation schema_version must be 1")
    if ledger.get("contract_version") != VERSION:
        errors.append(f"audit remediation contract_version must be {VERSION}")
    if ledger.get("resolution_policy") != "all-actionable-items":
        errors.append("audit remediation resolution_policy must be all-actionable-items")
    if plan is None and ledger.get("status") != "closed":
        errors.append("audit remediation ledger is not closed")
    if ledger.get("candidate_head_sha") != head_sha:
        errors.append("audit remediation candidate_head_sha differs from candidate")

    rejection, audited_head, _ = normalize_source(report)
    source = ledger.get("source") or {}
    if rejection and source.get("rejection_id") != rejection:
        errors.append("audit remediation rejection_id differs from audit result")
    if audited_head and source.get("audited_head_sha") != audited_head:
        errors.append("audit remediation audited_head_sha differs from audit result")
    if source.get("audit_report_sha256") != report_sha256:
        errors.append("audit remediation audit_report_sha256 differs from source bytes")


def ledger_index(ledger: dict, errors: list[str]) -> dict[tuple[str, str], dict]:
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
    return seen


def validate_actionable_items(expected: list[dict], seen: dict, selected: dict, head_sha: str, errors: list[str]) -> None:
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
        if key not in selected and item.get("status") != "fixed":
            errors.append(f"{label} is actionable and must be fixed")
        if not item.get("evidence"):
            errors.append(f"{label} lacks closure evidence")
        if not item.get("validations"):
            errors.append(f"{label} lacks closure validations")
        if exp.get("failed_gate"):
            validate_gate_replay(item, exp["failed_gate"], head_sha, label, errors, preparation=key in selected)
    if selected and not set(selected).issubset(expected_keys):
        errors.append("preparation postconditions are absent from the original actionable audit items")


def validate_ledger(ledger: dict, report: dict, report_sha256: str, head_sha: str, *, plan: dict | None = None) -> list[str]:
    errors: list[str] = []
    selected = planned_items(plan) if plan is not None else {}
    validate_ledger_identity(ledger, report, report_sha256, head_sha, plan, errors)
    expected = normalize_source(report)[2]
    validate_actionable_items(expected, ledger_index(ledger, errors), selected, head_sha, errors)
    expected_systemic = any(item["remediation_mode"] == "systemic-remediation" for item in expected)
    expected_targeted = any(item["remediation_mode"] == "targeted-remediation" for item in expected)
    expected_mode = "mixed-remediation" if expected_systemic and expected_targeted else ("systemic-remediation" if expected_systemic else "targeted-remediation")
    if expected and ledger.get("remediation_mode") != expected_mode:
        errors.append(f"audit remediation mode must be {expected_mode}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--audit-result", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--phase", choices=("final", "preparation"), default="final")
    parser.add_argument("--postcondition-plan", type=Path)
    parser.add_argument("--repository", type=Path)
    parser.add_argument("--base-sha")
    args = parser.parse_args()
    report_path = Path(args.audit_result)
    try:
        ledger = load(Path(args.ledger))
        report = load(report_path)
        plan = phase_plan(args.phase, args.postcondition_plan, report_path, args.repository, args.head_sha, args.base_sha)
        errors = validate_ledger(ledger, report, sha256(report_path), args.head_sha, plan=plan)
    except Exception as exc:
        print(f"BLOCK: invalid audit remediation input: {exc}")
        return 2

    if errors:
        for error in errors:
            print("BLOCK: " + error)
        return 2
    if plan is not None:
        print(f"PREPARED: {len(planned_items(plan))} source-bound certificate postconditions remain blocked; no final readiness asserted")
        return 0
    expected = normalize_source(report)[2]
    gate_count = sum(1 for item in expected if item.get("failed_gate"))
    print(f"READY: {len(expected)} actionable audit items closed on {args.head_sha}; exact_failed_gate_replays={gate_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
