#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import jsonschema
from audit_signature import report_semantic_errors, verify_report


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _load_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_constant,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("--trusted-auditors", required=True)
    parser.add_argument(
        "--exact-repository-only",
        action="store_true",
        help="reject wildcard/glob repository authorization entries",
    )
    args = parser.parse_args()
    report_path = Path(args.report).resolve()
    registry_path = Path(args.trusted_auditors).resolve()
    schema_dir = Path(__file__).resolve().parents[1] / "schemas"
    try:
        report = _load_json(report_path)
        registry = _load_json(registry_path)
        report_schema = _load_json(schema_dir / "external-audit.schema.json")
        registry_schema = _load_json(schema_dir / "trusted-auditors.schema.json")
        jsonschema.Draft202012Validator(report_schema).validate(report)
        jsonschema.Draft202012Validator(registry_schema).validate(registry)
        datetime.fromisoformat(str(report["issued_at"]))
        datetime.fromisoformat(str(report["signature"]["signed_at"]))
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    errors = report_semantic_errors(report, require_signature=True)
    errors.extend(verify_report(report, registry, exact_repository_only=args.exact_repository_only))
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: signed external audit report accepted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
