#!/usr/bin/env python3
"""Fail closed before treating an entregar-issue handoff as applicable to the current CI target."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from handoff_target_binding import classify_handoff_subject


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--work-item-kind", choices=("issue", "pr"))
    parser.add_argument("--work-item-number", type=int)
    parser.add_argument("--pull-request", type=int)
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    args = parser.parse_args()

    try:
        cert = load(Path(args.certificate))
    except Exception as exc:
        print(f"BLOCK: invalid handoff certificate: {exc}")
        print("TARGET_BINDING: unbound-or-invalid")
        return 3

    result = classify_handoff_subject(
        cert,
        repository=args.repository,
        work_item_kind=args.work_item_kind,
        work_item_number=args.work_item_number,
        pull_request=args.pull_request,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
    )
    print(f"TARGET_BINDING: {result['status']}")
    for reason in result["reasons"]:
        print(reason)
    if result["applicable"]:
        print("READY: governed handoff belongs to the current CI target")
        return 0
    print("IGNORE: handoff must not activate governed_handoff_observed for this target")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
