#!/usr/bin/env python3
"""Initialize a compact standard-evidence packet from requirement closure."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_artifact_io import load_json_artifact


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--requirement-closure", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--contract-version", default="2026-08-20.3")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    closure = load_json_artifact(Path(a.requirement_closure), require_object=True)
    ids = sorted({
        str(rid).strip()
        for obligation in closure.get("obligations") or []
        if isinstance(obligation, dict) and obligation.get("disposition") == "covered"
        for rid in obligation.get("requirement_ids") or []
        if str(rid).strip()
    })
    payload = {
        "schema_version": 1,
        "contract_version": a.contract_version,
        "head_sha": a.head_sha,
        "requirements": [
            {
                "requirement_id": rid,
                "positive_evidence": [],
                "primary_negative_control": {
                    "id": "", "status": "pending", "procedure": "", "expected": "", "observed": ""
                },
                "regression_evidence": [],
            }
            for rid in ids
        ],
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"READY: initialized standard evidence for {len(ids)} requirements at {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
