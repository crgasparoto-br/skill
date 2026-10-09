#!/usr/bin/env python3
"""Reject incomplete deliveries before terminal success is reported."""
import argparse
import json
from pathlib import Path

SUCCESS = {"aprovado-operacionalmente-sem-ressalvas", "aprovado-internamente-pendente-auditoria-independente"}

def validate(data):
    errors = []
    obligations = data.get("obligations")
    if not isinstance(obligations, list) or not obligations:
        return ["DELIVERY-COMPLETE-001: obligations required"]
    identifiers = [item.get("id") for item in obligations if isinstance(item, dict)]
    if len(identifiers) != len(obligations) or any(not x for x in identifiers) or len(set(identifiers)) != len(identifiers):
        errors.append("DELIVERY-COMPLETE-001: invalid or duplicate obligation ids")
    for item in obligations:
        if not isinstance(item, dict):
            continue
        state = item.get("state")
        if state == "deferred-by-scope" and not item.get("scope_evidence"):
            errors.append("DELIVERY-COMPLETE-001: unproven scope deferral " + str(item.get("id")))
        if data.get("status") in SUCCESS and state not in ("passed", "deferred-by-scope"):
            errors.append("DELIVERY-COMPLETE-001: open obligation " + str(item.get("id")))
    if data.get("status") in SUCCESS:
        ci = data.get("ci", {})
        if ci.get("state") not in ("success", "green") or ci.get("subject_sha") != data.get("material_head_sha"):
            errors.append("DELIVERY-CI-002: CI not terminal green on material HEAD")
        if data.get("completion_gate") != "READY":
            errors.append("DELIVERY-HANDOFF-005: completion gate not READY")
    elif data.get("status") == "bloqueado-por-impedimento-real":
        blocker = data.get("blocker", {})
        if not isinstance(blocker, dict) or any(not blocker.get(k) for k in ("operation", "failure", "evidence", "recovery")):
            errors.append("DELIVERY-BLOCKER-004: missing concrete blocker proof")
    else:
        errors.append("DELIVERY-REPORT-006: unknown final status")
    checkpoint = data.get("checkpoint", {})
    if not isinstance(checkpoint, dict) or not checkpoint.get("work_item_fingerprint") or checkpoint.get("observed_head") != data.get("material_head_sha"):
        errors.append("DELIVERY-REENTRY-003: checkpoint identity missing or stale")
    return errors

def main():
    p = argparse.ArgumentParser()
    p.add_argument("snapshot", type=Path)
    args = p.parse_args()
    errors = validate(json.loads(args.snapshot.read_text(encoding="utf-8")))
    print(json.dumps({"status": "BLOCK" if errors else "READY", "errors": errors}, ensure_ascii=False))
    return 2 if errors else 0

if __name__ == "__main__":
    raise SystemExit(main())
