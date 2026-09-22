#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_artifact_io import DEFAULT_SHARD_BYTES, DEFAULT_THRESHOLD_BYTES, pack_json_artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack a large JSON audit artifact into deterministic gzip/base64 shards.")
    parser.add_argument("path")
    parser.add_argument("--threshold-bytes", type=int, default=DEFAULT_THRESHOLD_BYTES)
    parser.add_argument("--shard-bytes", type=int, default=DEFAULT_SHARD_BYTES)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--artifact-kind")
    args = parser.parse_args()
    meta = pack_json_artifact(
        Path(args.path),
        threshold_bytes=args.threshold_bytes,
        shard_bytes=args.shard_bytes,
        force=args.force,
        artifact_kind=args.artifact_kind,
    )
    print(json.dumps(meta, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
