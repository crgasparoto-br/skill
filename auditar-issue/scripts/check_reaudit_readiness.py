#!/usr/bin/env python3
"""Validate a remediation packet before spending a full independent re-audit."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact

from preflight_semantic_guards import conflicting_current_sha_claims

SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
RETIREMENT_DISPOSITIONS = {"superseded", "not-applicable"}
REJECTION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


def load(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def escape_entries(data: dict) -> list[dict]:
    raw = data.get("escapes") if isinstance(data.get("escapes"), list) else [data]
    return [item for item in raw if isinstance(item, dict)]


def controls_by_id(data: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in data.get("controls") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if cid:
            result[cid] = item
    return result


def retired_controls_by_id(data: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in data.get("retired_controls") or []:
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if cid:
            result[cid] = item
    return result


def audit_key(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def independent_rejection(kind: object) -> bool:
    value = str(kind or "").strip().lower().replace("_", "-")
    return "independent" in value and "rejection" in value


def finding_ids(value: dict) -> set[str]:
    result = {str(item).strip() for item in value.get("finding_ids") or [] if str(item).strip()}
    single = str(value.get("finding_id") or "").strip()
    if single:
        result.add(single)
    return result


def validate_latest_rejection(learning: dict, current_escapes: list[dict], errors: list[str]) -> None:
    source = learning.get("source_event")
    if not isinstance(source, dict):
        errors.append("learning closure lacks source_event")
        return
    if not independent_rejection(source.get("kind")):
        errors.append("learning closure source_event is not an independent rejection")
        return
    rejection_id = str(source.get("rejection_id") or "").strip()
    if not REJECTION_ID_RE.fullmatch(rejection_id):
        errors.append("independent rejection source_event lacks stable rejection_id")
        return
    expected = finding_ids(source)
    matched: list[dict] = []
    observed: set[str] = set()
    for item in current_escapes:
        audit = item.get("source_audit")
        if not isinstance(audit, dict):
            continue
        if str(audit.get("rejection_id") or "").strip() == rejection_id:
            matched.append(item)
            observed.update(finding_ids(audit))
    if not matched:
        errors.append(f"independent rejection {rejection_id} has no audit escape closure")
        return
    missing = sorted(expected - observed)
    if missing:
        errors.append(
            f"independent rejection {rejection_id} lacks audit escape closure for finding ids: "
            + ", ".join(missing)
        )


def validate_escape(item: dict, index: int, errors: list[str], head_sha: str | None = None) -> None:
    eid = item.get("escape_id") or index
    if item.get("status") != "passed":
        errors.append(f"escape {eid} is not passed")
    if not str(item.get("escape_class") or "").strip():
        errors.append(f"escape {eid} lacks escape_class")
    if len(str(item.get("plausible_wrong_implementation") or "").strip()) < 20:
        errors.append(f"escape {eid} lacks plausible wrong implementation")
    siblings = item.get("sibling_cases") or []
    if len(siblings) < 2 or any(not isinstance(case, dict) or case.get("status") != "passed" for case in siblings):
        errors.append(f"escape {eid} sibling cases are incomplete")
    for key in ("prevention_change", "detection_change"):
        if not isinstance(item.get(key), dict) or not item[key].get("evidence"):
            errors.append(f"escape {eid} lacks {key} evidence")
    if head_sha:
        if item.get("revalidated_head_sha") != head_sha:
            errors.append(f"escape {eid} revalidated_head_sha differs from candidate")
        literal = item.get("literal_case") or {}
        if isinstance(literal, dict):
            conflicts = conflicting_current_sha_claims(literal.get("observed"), head_sha)
            if conflicts:
                errors.append(f"escape {eid} literal_case.observed asserts non-current SHA(s) as current/exact-head: {conflicts}")


def validate_retirement(
    item: dict,
    *,
    previous_id: str,
    head_sha: str | None,
    active: dict[str, dict],
    errors: list[str],
) -> None:
    label = f"retired inherited control {previous_id}"
    disposition = str(item.get("disposition") or "").strip()
    if disposition not in RETIREMENT_DISPOSITIONS:
        errors.append(f"{label} has invalid disposition")
        return
    if len(str(item.get("reason") or "").strip()) < 20:
        errors.append(f"{label} lacks disposition reason")
    if head_sha and item.get("subject_sha") != head_sha:
        errors.append(f"{label} subject_sha differs from candidate")
    if not str(item.get("evidence") or "").strip():
        errors.append(f"{label} lacks evidence")
    if not SHA256_RE.match(str(item.get("evidence_sha256") or "").strip()):
        errors.append(f"{label} lacks valid evidence_sha256")
    for key, minimum in (("procedure", 12), ("expected", 8), ("observed", 8)):
        if len(str(item.get(key) or "").strip()) < minimum:
            errors.append(f"{label} lacks {key}")
    replacement = str(item.get("replacement_control_id") or "").strip()
    if disposition == "superseded":
        if not replacement:
            errors.append(f"{label} superseded disposition requires replacement_control_id")
        elif replacement not in active:
            errors.append(f"{label} replacement control {replacement} is not active on candidate")
        elif active[replacement].get("status") != "passed":
            errors.append(f"{label} replacement control {replacement} is not passed")
    elif replacement:
        errors.append(f"{label} not-applicable disposition must not declare replacement_control_id")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--closure", required=True)
    parser.add_argument("--learning-closure", required=True)
    parser.add_argument("--inherited-controls")
    parser.add_argument("--head-sha")
    parser.add_argument("--previous-closure")
    parser.add_argument("--previous-inherited-controls")
    args = parser.parse_args()

    path = Path(args.closure)
    if not path.is_file():
        print("BLOCK: audit-escape-closure.json is missing")
        return 2
    try:
        data = load(path)
    except Exception as exc:
        print(f"BLOCK: invalid audit escape closure: {exc}")
        return 2

    errors: list[str] = []
    try:
        learning = load(Path(args.learning_closure))
    except Exception as exc:
        print(f"BLOCK: invalid learning closure: {exc}")
        return 2

    current_escapes = escape_entries(data)
    validate_latest_rejection(learning, current_escapes, errors)
    current_escape_ids: set[str] = set()
    for index, item in enumerate(current_escapes):
        validate_escape(item, index, errors, args.head_sha)
        eid = str(item.get("escape_id") or "").strip()
        if eid:
            if eid in current_escape_ids:
                errors.append(f"escape {eid} is duplicated")
            current_escape_ids.add(eid)

    if not args.previous_closure:
        errors.append("re-audit requires previous audit-escape-closure snapshot for monotonic validation")
    else:
        try:
            previous_closure = load(Path(args.previous_closure))
        except Exception as exc:
            errors.append(f"invalid previous audit escape closure: {exc}")
        else:
            previous_ids = {
                str(item.get("escape_id") or "").strip()
                for item in escape_entries(previous_closure)
                if str(item.get("escape_id") or "").strip()
            }
            missing = sorted(previous_ids - current_escape_ids)
            if missing:
                errors.append("audit escape closure is not cumulative; previous escape ids disappeared: " + ", ".join(missing))

    if args.inherited_controls:
        try:
            inherited = load(Path(args.inherited_controls))
        except Exception as exc:
            errors.append(f"invalid inherited controls: {exc}")
            inherited = None
        if inherited is not None:
            if args.head_sha and inherited.get("head_sha") != args.head_sha:
                errors.append("inherited controls head_sha differs from candidate")
            controls = inherited.get("controls") or []
            if not controls:
                errors.append("re-audit requires cumulative inherited controls")
            active = controls_by_id(inherited)
            for idx, item in enumerate(controls):
                cid = item.get("id") if isinstance(item, dict) else idx
                if not isinstance(item, dict) or item.get("status") != "passed":
                    errors.append(f"inherited control {cid} is not passed")
                    continue
                if args.head_sha and item.get("head_sha") != args.head_sha:
                    errors.append(f"inherited control {cid} was not executed on candidate head")
                if args.head_sha and item.get("subject_sha") != args.head_sha:
                    errors.append(f"inherited control {cid} subject_sha differs from candidate")
                if not str(item.get("evidence") or "").strip():
                    errors.append(f"inherited control {cid} lacks evidence")
                if not SHA256_RE.match(str(item.get("evidence_sha256") or "").strip()):
                    errors.append(f"inherited control {cid} lacks valid evidence_sha256")
                if args.head_sha:
                    conflicts = conflicting_current_sha_claims(item.get("observed"), args.head_sha)
                    if conflicts:
                        errors.append(f"inherited control {cid} observed narrative asserts non-current SHA(s) as current/exact-head: {conflicts}")
            if inherited.get("unresolved_controls"):
                errors.append("inherited controls has unresolved_controls")

            if not args.previous_inherited_controls:
                errors.append("re-audit requires previous inherited-controls snapshot for monotonic validation")
            else:
                try:
                    previous = load(Path(args.previous_inherited_controls))
                except Exception as exc:
                    errors.append(f"invalid previous inherited controls: {exc}")
                else:
                    prior_active = controls_by_id(previous)
                    prior_retired = retired_controls_by_id(previous)
                    prior = {**prior_retired, **prior_active}
                    retired_list = inherited.get("retired_controls") or []
                    retired: dict[str, dict] = {}
                    for index, item in enumerate(retired_list):
                        if not isinstance(item, dict):
                            errors.append(f"retired inherited control {index} is invalid")
                            continue
                        cid = str(item.get("id") or "").strip()
                        if not cid:
                            errors.append(f"retired inherited control {index} lacks id")
                            continue
                        retired[cid] = item
                    missing = sorted(set(prior) - set(active) - set(retired))
                    for cid in missing:
                        errors.append(f"inherited control {cid} disappeared from cumulative lineage without explicit disposition")
                    for cid, item in retired.items():
                        if cid not in prior:
                            errors.append(f"retired inherited control {cid} does not exist in previous snapshot")
                            continue
                        if cid in active:
                            errors.append(f"inherited control {cid} cannot be both active and retired")
                        validate_retirement(item, previous_id=cid, head_sha=args.head_sha, active=active, errors=errors)
                    previous_audits = {audit_key(item) for item in previous.get("source_audits") or []}
                    current_audits = {audit_key(item) for item in inherited.get("source_audits") or []}
                    if previous_audits - current_audits:
                        errors.append("source_audits is not cumulative; previous audit entries disappeared")
    else:
        errors.append("re-audit requires inherited-controls.json")

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print("READY: latest independent rejection, remediation class and inherited control lineage are cumulative for independent re-audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
