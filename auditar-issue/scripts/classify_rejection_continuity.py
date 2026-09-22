#!/usr/bin/env python3
"""Classify whether a rejected re-audit continues an already-open rejection identity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("audit result must be an object")
    return value


def gate_command(item: dict) -> str:
    gate = item.get("failed_gate")
    if not isinstance(gate, dict):
        return ""
    return " ".join(str(gate.get("command") or "").strip().split())


def signature(item: dict) -> tuple[str, str, str, str, str, str]:
    return (
        str(item.get("id") or ""),
        str(item.get("requirement_id") or ""),
        str(item.get("escape_category") or ""),
        str(item.get("required_gate") or ""),
        str(item.get("remediation_mode") or ""),
        gate_command(item),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous-audit", required=True)
    parser.add_argument("--current-audit", required=True)
    args = parser.parse_args()
    previous = load(args.previous_audit)
    current = load(args.current_audit)
    previous_id = str(previous.get("rejection_id") or "")
    if not previous_id:
        print("NEW: previous audit has no rejection_id")
        return 0
    prior = {signature(item) for item in previous.get("findings") or [] if isinstance(item, dict) and str(item.get("status") or "open") != "closed"}
    now = {signature(item) for item in current.get("findings") or [] if isinstance(item, dict)}
    continued = sorted(sig[0] for sig in now if sig in prior and sig[0])
    novel = sorted(sig[0] for sig in now if sig not in prior and sig[0])
    if continued and not novel:
        if current.get("rejection_id") != previous_id:
            print(f"BLOCK: same open finding must reuse rejection_id {previous_id}")
            return 2
        print("CONTINUATION: " + previous_id + " findings=" + ",".join(continued))
        return 0
    if novel and current.get("rejection_id") == previous_id:
        print("BLOCK: materially new finding set requires a new rejection_id")
        return 2
    print("NEW: current rejection contains materially new findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
