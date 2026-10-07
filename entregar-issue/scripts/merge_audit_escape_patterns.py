#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_artifact_io import load_json_artifact


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--closure", required=True); p.add_argument("--catalog", required=True); a=p.parse_args()
    closure=load_json_artifact(Path(a.closure)); entries=closure.get("escapes") if isinstance(closure,dict) and isinstance(closure.get("escapes"),list) else [closure]
    path=Path(a.catalog)
    catalog=load_json_artifact(path) if path.is_file() else {"schema_version":1,"patterns":[]}
    patterns={str(item.get("escape_class")):item for item in catalog.get("patterns") or [] if isinstance(item,dict) and item.get("escape_class")}
    for item in entries:
        if not isinstance(item,dict) or item.get("status") != "passed": continue
        cls=str(item.get("escape_class") or "").strip()
        if not cls: continue
        patterns[cls]={
            "escape_class": cls,
            "source_audit": item.get("source_audit"),
            "plausible_wrong_implementation": item.get("plausible_wrong_implementation"),
            "sibling_cases": item.get("sibling_cases") or [],
            "prevention_change": item.get("prevention_change"),
            "detection_change": item.get("detection_change"),
            "trigger_terms": item.get("trigger_terms") or [],
            "required_risk_families": item.get("required_risk_families") or [],
            "required_attack_dimensions": item.get("required_attack_dimensions") or [],
        }
    catalog={"schema_version":1,"patterns":[patterns[key] for key in sorted(patterns)]}
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(path); return 0
if __name__ == "__main__": raise SystemExit(main())
