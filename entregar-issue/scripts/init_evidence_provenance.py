#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40,64}$", re.I)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize normalized evidence provenance for a material candidate.")
    parser.add_argument("--material-head-sha", required=True)
    parser.add_argument("--base-sha")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if not SHA_RE.match(args.material_head_sha):
        raise SystemExit("material head SHA is invalid")
    if args.base_sha and not SHA_RE.match(args.base_sha):
        raise SystemExit("base SHA is invalid")
    payload = {
        "schema_version": 1,
        "material_head_sha": args.material_head_sha,
        "base_sha": args.base_sha,
        "evidence": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
