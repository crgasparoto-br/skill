#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_artifact_io import load_json_artifact

from handoff_semantic_guards import conflicting_current_sha_claims


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def entries(data: dict) -> list[dict]:
    raw = data.get("escapes") if isinstance(data.get("escapes"), list) else [data]
    return [item for item in raw if isinstance(item, dict)]


def by_id(data: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for index, item in enumerate(entries(data)):
        eid = str(item.get("escape_id") or "").strip()
        if not eid:
            eid = f"__missing_{index}"
        result[eid] = item
    return result


def validate_entry(item: dict, index: int, errors: list[str], head_sha: str | None = None) -> None:
    eid = str(item.get("escape_id") or index)
    if not str(item.get("escape_id") or "").strip():
        errors.append(f"audit escape entry {index} lacks escape_id")
    if item.get("status") != "passed":
        errors.append(f"audit escape {eid} is not passed")
    if not str(item.get("escape_class") or "").strip():
        errors.append(f"audit escape {eid} lacks escape_class")
    if len(str(item.get("plausible_wrong_implementation") or "").strip()) < 20:
        errors.append(f"audit escape {eid} lacks plausible wrong implementation")
    siblings = item.get("sibling_cases") or []
    if len(siblings) < 2:
        errors.append(f"audit escape {eid} has fewer than two sibling cases")
    if any(not isinstance(case, dict) or case.get("status") != "passed" for case in siblings):
        errors.append(f"audit escape {eid} has sibling cases not passed")
    for key in ("prevention_change", "detection_change"):
        if not isinstance(item.get(key), dict) or not item[key].get("evidence"):
            errors.append(f"audit escape {eid} lacks {key} evidence")
    if head_sha:
        if item.get("revalidated_head_sha") != head_sha:
            errors.append(f"audit escape {eid} revalidated_head_sha differs from candidate")
        literal = item.get("literal_case") or {}
        if isinstance(literal, dict):
            conflicts = conflicting_current_sha_claims(literal.get("observed"), head_sha)
            if conflicts:
                errors.append(
                    f"audit escape {eid} literal_case.observed asserts non-current SHA(s) as current/exact-head: {conflicts}"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", required=True)
    parser.add_argument("--previous-closure")
    parser.add_argument("--head-sha")
    parser.add_argument("--require-previous", action="store_true")
    args = parser.parse_args()

    current_path = Path(args.closure)
    if not current_path.is_file():
        print("BLOCK: audit-escape-closure.json is missing")
        return 2
    try:
        current = load(current_path)
    except Exception as exc:
        print(f"BLOCK: invalid audit escape closure: {exc}")
        return 2

    errors: list[str] = []
    current_entries = entries(current)
    if not current_entries:
        errors.append("audit escape closure has no entries")
    current_ids: set[str] = set()
    for index, item in enumerate(current_entries):
        validate_entry(item, index, errors, args.head_sha)
        eid = str(item.get("escape_id") or "").strip()
        if eid:
            if eid in current_ids:
                errors.append(f"audit escape {eid} is duplicated")
            current_ids.add(eid)

    if args.require_previous and not args.previous_closure:
        errors.append("re-audit remediation requires previous audit-escape-closure snapshot for monotonic validation")
    if args.previous_closure:
        previous_path = Path(args.previous_closure)
        if not previous_path.is_file():
            errors.append("previous audit-escape-closure snapshot is missing")
        else:
            try:
                previous = load(previous_path)
            except Exception as exc:
                errors.append(f"invalid previous audit escape closure: {exc}")
            else:
                previous_ids = set(by_id(previous))
                missing = sorted(eid for eid in previous_ids if not eid.startswith("__missing_") and eid not in current_ids)
                if missing:
                    errors.append("audit escape closure is not cumulative; previous escape ids disappeared: " + ", ".join(missing))

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print("READY: audit escape closure is complete and monotonic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
