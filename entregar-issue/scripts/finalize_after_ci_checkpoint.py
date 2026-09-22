#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
VERSION = "2026-08-20.3"

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    a = p.parse_args()
    try:
        v = json.loads(Path(a.input).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"BLOCK: invalid finalize-after-ci envelope: {exc}")
        return 2
    errors=[]
    required=["schema_version","contract_version","return_control_to","next_phase","ci_owner_closed","reason","previous_frozen_sha","material_head_sha","ci_state","recovery_hint"]
    for key in required:
        if key not in v: errors.append(f"missing {key}")
    if v.get("schema_version") != 2: errors.append("schema_version must be 2")
    if v.get("contract_version") != VERSION: errors.append("contract_version mismatch")
    if v.get("return_control_to") != "entregar-issue": errors.append("return_control_to must be entregar-issue")
    if v.get("next_phase") != "finalize-after-ci": errors.append("next_phase must be finalize-after-ci")
    if v.get("ci_owner_closed") is not True: errors.append("ci_owner_closed must be true")
    if v.get("ci_state") != "green": errors.append("ci_state must be green")
    hint=v.get("recovery_hint")
    if not isinstance(hint,dict): errors.append("recovery_hint must be object")
    else:
        if not isinstance(hint.get("changed_files"),list): errors.append("changed_files must be array")
        if hint.get("material_change") is True and hint.get("resume_from") != "hygiene": errors.append("material change must resume from hygiene")
        if hint.get("material_change") is False and hint.get("resume_from") not in ("handoff","freeze",None): errors.append("unchanged material may resume only from freeze/handoff")
    if errors:
        for e in errors: print(f"BLOCK: {e}")
        return 2
    print("READY: finalize-after-ci checkpoint accepted")
    print(f"material_head_sha={v['material_head_sha']}")
    print(f"resume_from={hint.get('resume_from')}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
