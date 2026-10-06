#!/usr/bin/env python3
"""Map dependencies and reverse callers of changed production files via the runtime graph."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime_graph import build_runtime_context


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="checkout of the exact SHA being analysed")
    parser.add_argument("--changed", action="append", default=[], help="repository-relative production path; repeatable")
    parser.add_argument("--out", help="write the JSON report here instead of stdout")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"BLOCK: repository path is not a directory: {repo}")
        return 2
    files, edges, unresolved, coverage = build_runtime_context(repo, sorted(set(args.changed)))
    report = {
        "schema_version": 1,
        "changed": sorted(set(args.changed)),
        "files": files,
        "edges": edges,
        "unresolved": unresolved,
        "coverage": coverage,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")
    # An incomplete graph is evidence of UNKNOWN, never of "no consumers".
    return 0 if coverage.get("complete") else 1


if __name__ == "__main__":
    raise SystemExit(main())
