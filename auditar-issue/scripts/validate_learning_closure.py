#!/usr/bin/env python3
"""Validate rejection learning and require generic promotion for systemic escapes."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact

ISSUE_REF = re.compile(r"\b(?:issue|pr|pull request)\s*#?\s*\d+\b", re.IGNORECASE)
REPO_ISSUE = re.compile(r"\b[a-z0-9_.-]+/[a-z0-9_.-]+#\d+\b", re.IGNORECASE)
SHA40 = re.compile(r"\b[a-f0-9]{40}\b", re.IGNORECASE)
REF_HEAD = re.compile(r"\brefs/heads/[A-Za-z0-9._/-]+\b")
REJECTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError("expected JSON object")
    return value


def generic_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--learning-closure", required=True)
    args = parser.parse_args()
    try:
        data = load(Path(args.learning_closure))
    except Exception as exc:
        print(f"BLOCK: invalid learning closure: {exc}")
        return 2

    errors: list[str] = []
    if data.get("schema_version") != 1:
        errors.append("learning closure schema_version must be 1")
    classification = data.get("classification")
    if classification not in {"implementation-only", "systemic-escape"}:
        errors.append("classification must be implementation-only or systemic-escape")
    source_event = data.get("source_event")
    if not isinstance(source_event, dict):
        errors.append("source_event is required")
        source_event = {}
    source_kind = str(source_event.get("kind") or "").strip().lower().replace("_", "-")
    if not ("independent" in source_kind and "rejection" in source_kind):
        errors.append("learning closure source_event must identify an independent rejection")
    rejection_id = str(source_event.get("rejection_id") or "").strip()
    if not REJECTION_ID.fullmatch(rejection_id):
        errors.append("independent rejection source_event requires stable rejection_id")
    report_sha = str(source_event.get("audit_report_sha256") or "").strip()
    if report_sha and not SHA256.fullmatch(report_sha):
        errors.append("independent rejection source_event audit_report_sha256 is invalid")
    finding_ids = source_event.get("finding_ids")
    if finding_ids is not None and (not isinstance(finding_ids, list) or any(not str(item).strip() for item in finding_ids)):
        errors.append("independent rejection source_event finding_ids must be a list of non-empty identifiers")

    learning = data.get("generalized_learning")
    if classification == "implementation-only":
        if not isinstance(learning, dict) or learning.get("promotion_status") != "not-required":
            errors.append("implementation-only rejection must record promotion_status=not-required")
        if not str((learning or {}).get("reason") or "").strip():
            errors.append("implementation-only rejection must justify why no global rule is promoted")
    elif classification == "systemic-escape":
        if not isinstance(learning, dict):
            errors.append("systemic escape requires generalized_learning")
        else:
            required = [
                "escape_class", "generalized_failure_pattern", "plausible_wrong_implementation",
                "trigger_signals", "risk_families", "reusable_control", "prevention_rule",
                "detection_rule", "transfer_cases", "promotion_status",
            ]
            for key in required:
                if not learning.get(key):
                    errors.append(f"generalized_learning lacks {key}")
            if learning.get("promotion_status") != "promoted":
                errors.append("systemic escape must be promoted before handoff")
            cases = learning.get("transfer_cases") or []
            if len(cases) < 2:
                errors.append("systemic escape requires at least two transfer cases")
            surfaces = {str(case.get("surface")) for case in cases if isinstance(case, dict)}
            if len(surfaces) < 2:
                errors.append("transfer cases must exercise at least two distinct synthetic surfaces")
            if any(not isinstance(case, dict) or case.get("status") != "passed" for case in cases):
                errors.append("all transfer cases must be passed")
            changes = data.get("skill_changes") or []
            roles = {str(item.get("role")) for item in changes if isinstance(item, dict) and item.get("status") == "passed"}
            if not {"prevention", "detection"}.issubset(roles):
                errors.append("systemic escape requires passed prevention and detection skill changes")

            promoted_text = generic_text(learning)
            for regex, label in (
                (ISSUE_REF, "issue/PR identifier"),
                (REPO_ISSUE, "repository issue locator"),
                (SHA40, "candidate SHA"),
                (REF_HEAD, "concrete branch ref"),
            ):
                if regex.search(promoted_text):
                    errors.append(f"promoted learning contains concrete {label}")

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print("READY: rejection learning is closed and generalized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
