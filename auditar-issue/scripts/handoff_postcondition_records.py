#!/usr/bin/env python3
"""Typed preparation and deterministic closure of certificate postconditions.

Preparation preserves the blocked records. Only a separately authenticated literal
replay can supply the fields changed by ``expected_final_records``; that pure
function is also the consumer's exact transition oracle, not an authenticator.
"""
from __future__ import annotations

import copy
import hashlib
import re
from typing import TYPE_CHECKING

from audit_artifact_io import load_json_artifact

if TYPE_CHECKING:
    from pathlib import Path

PLAN_TYPE = "certificate-preparation-postconditions"
REPLAY_KIND = "certificate-postcondition-literal-replay"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def item_key(item: dict) -> tuple[str, str]:
    return str(item.get("source_kind") or ""), str(item.get("source_id") or "")


def planned_items(plan: dict) -> dict[tuple[str, str], dict]:
    if plan.get("schema_version") != 1 or plan.get("type") != PLAN_TYPE:
        raise ValueError("unrecognized certificate postcondition preparation type")
    items = plan.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("certificate preparation requires recognized postconditions")
    result: dict[tuple[str, str], dict] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("postcondition plan item must be an object")
        key = item_key(item)
        if key[0] not in {"finding", "recommendation"} or not key[1] or key in result:
            raise ValueError("postcondition plan has invalid or duplicate source items")
        result[key] = item
    return result


def phase_plan(
    phase: str, plan_path: Path | None, audit_result: Path | None,
    repository: Path | None, head_sha: str | None, base_sha: str | None,
) -> dict | None:
    if phase == "final":
        if plan_path is not None:
            raise ValueError("final validation cannot use a preparation postcondition plan")
        return None
    if phase != "preparation" or not all((plan_path, audit_result, repository, head_sha, base_sha)):
        raise ValueError("preparation requires a plan, original audit result, repository, material head and authenticated base")
    from certificate_postcondition_replay import verify_postcondition_plan

    plan = verify_postcondition_plan(plan_path, audit_result, head_sha, repository, expected_base=base_sha)
    planned_items(plan)
    return plan


def preparation_ledger_schema(final_schema: dict, plan: dict) -> dict:
    """Build a separate blocked model, preserving every unrelated constraint."""
    selected = planned_items(plan)
    schema = copy.deepcopy(final_schema)
    schema["$id"] = "certificate-postcondition-preparation-ledger.schema.json"
    schema["properties"]["status"] = {"const": "blocked"}
    final_item = schema["properties"]["items"]["items"]
    prepared_item = copy.deepcopy(final_item)
    prepared_item["properties"]["status"] = {"const": "implemented-unverified"}
    prepared_item["properties"]["closure_kind"] = {"const": "deterministic-gate-replay"}
    replay = prepared_item["properties"]["revalidation"]
    replay["required"] = sorted(set(replay["required"]) | {"status"})
    replay["properties"].update({
        "exit_code": {"const": None}, "evidence_sha256": {"const": None},
        "status": {"const": "not-passed"},
    })
    selected_schema = {"anyOf": [
        {"required": ["source_kind", "source_id"], "properties": {
            "source_kind": {"const": kind}, "source_id": {"const": source_id},
        }} for kind, source_id in selected
    ]}
    schema["properties"]["items"]["items"] = {
        "if": selected_schema, "then": prepared_item, "else": final_item,
    }
    return schema


def pending_ledger_errors(ledger: dict, plan: dict, report_sha256: str, head_sha: str) -> list[str]:
    selected = planned_items(plan)
    errors: list[str] = []
    if plan.get("material_head_sha") != head_sha or ledger.get("candidate_head_sha") != head_sha:
        errors.append("postcondition material head differs from candidate")
    source = ledger.get("source") or {}
    if plan.get("audit_report_sha256") != report_sha256 or source.get("audit_report_sha256") != report_sha256:
        errors.append("postcondition source audit bytes differ from preparation")
    if source.get("rejection_id") != plan.get("rejection_id"):
        errors.append("postcondition rejection differs from source audit")
    if ledger.get("status") != "blocked":
        errors.append("preparation remediation ledger must remain blocked")
    seen: set[tuple[str, str]] = set()
    for item in ledger.get("items") or []:
        if not isinstance(item, dict):
            continue
        key = item_key(item)
        if key not in selected:
            if item.get("status") != "fixed":
                errors.append(f"unselected audit item {key} must be fixed before preparation")
            continue
        if key in seen:
            errors.append(f"duplicate prepared audit item {key}")
        seen.add(key)
        errors.extend(pending_item_errors(item, selected[key], source))
    if seen != set(selected):
        errors.append("recognized postconditions are not represented exactly in remediation ledger")
    return errors


def pending_item_errors(item: dict, planned: dict, source: dict) -> list[str]:
    errors: list[str] = []
    label = ":".join(item_key(item))
    original = item.get("original_failed_gate") or {}
    replay = item.get("revalidation") or {}
    if item.get("status") != "implemented-unverified" or item.get("closure_kind") != "deterministic-gate-replay":
        errors.append(f"postcondition {label} must remain an implemented-unverified deterministic replay")
    if original.get("command") != planned.get("command") or replay.get("command") != planned.get("command"):
        errors.append(f"postcondition {label} must preserve the literal source command")
    if original.get("subject_sha") != planned.get("original_subject_sha") or source.get("audited_head_sha") != planned.get("original_subject_sha"):
        errors.append(f"postcondition {label} original subject differs from immutable audit")
    if original.get("exit_code") != planned.get("original_exit_code"):
        errors.append(f"postcondition {label} original exit differs from immutable audit")
    if replay.get("exit_code") is not None or replay.get("evidence_sha256") is not None or replay.get("status") != "not-passed":
        errors.append(f"postcondition {label} pending replay must retain null exit/hash and not-passed status")
    if "replay_evidence" in replay:
        errors.append(f"postcondition {label} preparation cannot contain a finalized replay receipt")
    return errors


def escape_key(item: dict, plan: dict) -> tuple[str, str] | None:
    source = item.get("source_audit") or {}
    if not isinstance(source, dict):
        return None
    if source.get("rejection_id") != plan.get("rejection_id"):
        return None
    for key in planned_items(plan):
        field = "finding" if key[0] == "finding" else "recommendation"
        ids = source.get(f"{field}_ids") or []
        if not isinstance(ids, list):
            continue
        actual = {str(value) for value in ids}
        if source.get(f"{field}_id"):
            actual.add(str(source[f"{field}_id"]))
        if actual == {key[1]}:
            return key
    return None


def pending_escape_errors(closure: dict, plan: dict) -> list[str]:
    selected = planned_items(plan)
    errors: list[str] = []
    if closure.get("status") != "blocked":
        errors.append("preparation audit escape closure must remain blocked")
    seen: set[tuple[str, str]] = set()
    for item in closure.get("escapes") or []:
        if not isinstance(item, dict):
            errors.append("preparation audit escape entry must be an object")
            continue
        key = escape_key(item, plan)
        if key is None:
            if item.get("status") != "passed":
                errors.append("unselected audit escape must be passed before preparation")
            continue
        if key in seen:
            errors.append(f"duplicate postcondition audit escape for {key}")
        seen.add(key)
        source = item.get("source_audit") or {}
        literal = item.get("literal_case") or {}
        if source.get("audit_report_sha256") != plan.get("audit_report_sha256") or source.get("head_sha") != selected[key].get("original_subject_sha"):
            errors.append(f"postcondition escape {key} differs from original source audit")
        if item.get("status") != "blocked" or literal.get("status") != "not-passed":
            errors.append(f"postcondition escape {key} and its literal case must remain blocked/not-passed")
        if "replay_evidence" in literal:
            errors.append(f"postcondition escape {key} cannot contain a finalized replay receipt")
    if seen != set(selected):
        errors.append("recognized postconditions require exactly one source-bound audit escape each")
    return errors


def validate_preparation_records(
    *, ledger: dict, escape_closure: dict | None, plan: dict, audit_report: dict,
    audit_report_sha256: str, head_sha: str,
) -> None:
    from validate_audit_remediation import validate_ledger

    errors = validate_ledger(ledger, audit_report, audit_report_sha256, head_sha, plan=plan)
    if escape_closure is not None:
        from validate_audit_escape_lineage import validate_entry

        errors.extend(pending_escape_errors(escape_closure, plan))
        for index, item in enumerate(escape_closure.get("escapes") or []):
            validate_entry(item, index, errors, head_sha, preparation=escape_key(item, plan) is not None)
    if errors:
        raise ValueError("; ".join(errors))


def validated_preparation_plan(
    *, phase: str, plan_path: Path | None, audit_result: Path | None,
    ledger_path: Path | None, repository: Path | None, head_sha: str | None, base_sha: str | None,
    escape_closure: dict | None = None,
) -> dict | None:
    plan = phase_plan(phase, plan_path, audit_result, repository, head_sha, base_sha)
    if plan is None:
        return None
    if ledger_path is None:
        raise ValueError("preparation requires the source-bound audit remediation ledger")
    validate_preparation_records(
        ledger=load_json_artifact(ledger_path, require_object=True), escape_closure=escape_closure,
        plan=plan, audit_report=load_json_artifact(audit_result, require_object=True),
        audit_report_sha256=hashlib.sha256(audit_result.read_bytes()).hexdigest(), head_sha=head_sha,
    )
    return plan


def finalization_projection(ledger: dict, escape_closure: dict, plan: dict) -> dict:
    """Remove only fields whose exact new values are checked by the transition oracle."""
    result = {"audit_remediation": copy.deepcopy(ledger), "audit_escape_closure": copy.deepcopy(escape_closure)}
    result["audit_remediation"].pop("status", None)
    result["audit_escape_closure"].pop("status", None)
    selected = planned_items(plan)
    for item in result["audit_remediation"].get("items") or []:
        if item_key(item) in selected:
            item.pop("status", None)
            for field in ("exit_code", "evidence_sha256", "status", "replay_evidence"):
                (item.get("revalidation") or {}).pop(field, None)
    for item in result["audit_escape_closure"].get("escapes") or []:
        if escape_key(item, plan) is not None:
            item.pop("status", None)
            for field in ("status", "replay_evidence"):
                (item.get("literal_case") or {}).pop(field, None)
    return result


def receipt_evidence(receipt: dict, planned: dict, plan: dict) -> dict:
    key = item_key(planned)
    identity = receipt.get("identity") or {}
    source = receipt.get("trusted_source") or {}
    execution = receipt.get("execution") or {}
    expected = {
        "schema_version": 1, "kind": REPLAY_KIND, "source_kind": key[0], "source_id": key[1],
        "command": planned["command"], "equivalence": "exact-command-replay",
    }
    if any(receipt.get(field) != value for field, value in expected.items()):
        raise ValueError(f"verified replay receipt differs from postcondition {key}")
    if identity.get("material_head_sha") != plan.get("material_head_sha") or source.get("anchor") != plan.get("trusted_anchor_sha"):
        raise ValueError(f"verified replay receipt has another material head or trusted anchor for {key}")
    if identity.get("base_sha") != plan.get("base_sha") or identity.get("repository") != plan.get("repository"):
        raise ValueError(f"verified replay receipt has another authenticated base or repository for {key}")
    if receipt.get("argv") != planned.get("argv") or source.get("path") != planned.get("gate_path"):
        raise ValueError(f"verified replay receipt changed the literal invocation or canonical source for {key}")
    if source.get("sha256") != planned.get("gate_source_sha256") or source.get("git_blob") != planned.get("gate_blob_sha"):
        raise ValueError(f"verified replay receipt has another trusted source for {key}")
    if type(execution.get("exit_code")) is not int or execution["exit_code"] != 0:
        raise ValueError(f"postcondition {key} does not have a successful literal replay")
    digests = {
        "preparation_sha256": receipt.get("preparation_sha256"),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "raw_log_sha256": execution.get("raw_log_sha256"),
    }
    if any(not SHA256_RE.fullmatch(str(value or "")) for value in digests.values()):
        raise ValueError(f"postcondition {key} lacks verified replay digests")
    return {
        "type": REPLAY_KIND, "source_kind": key[0], "source_id": key[1],
        "command": planned["command"], "material_head_sha": plan["material_head_sha"],
        "trusted_anchor_sha": plan["trusted_anchor_sha"], "exit_code": 0, **digests,
    }


def expected_final_records(
    ledger: dict, escape_closure: dict, plan: dict,
    verified_receipts: dict[tuple[str, str], dict],
) -> dict:
    """Pure transition oracle; callers must authenticate each supplied receipt first."""
    selected = planned_items(plan)
    if set(verified_receipts) != set(selected):
        raise ValueError("verified receipts must cover exactly the recognized postconditions")
    errors = pending_ledger_errors(ledger, plan, plan["audit_report_sha256"], plan["material_head_sha"])
    errors.extend(pending_escape_errors(escape_closure, plan))
    if errors:
        raise ValueError("; ".join(errors))
    evidence = {key: receipt_evidence(verified_receipts[key], item, plan) for key, item in selected.items()}
    result = {"audit_remediation": copy.deepcopy(ledger), "audit_escape_closure": copy.deepcopy(escape_closure)}
    result["audit_remediation"]["status"] = "closed"
    result["audit_escape_closure"]["status"] = "passed"
    for item in result["audit_remediation"]["items"]:
        key = item_key(item)
        if key in selected:
            item["status"] = "fixed"
            item["revalidation"].update({
                "status": "passed", "exit_code": 0, "evidence_sha256": evidence[key]["raw_log_sha256"],
                "replay_evidence": copy.deepcopy(evidence[key]),
            })
    for item in result["audit_escape_closure"]["escapes"]:
        key = escape_key(item, plan)
        if key is not None:
            item["status"] = "passed"
            item["literal_case"]["status"] = "passed"
            item["literal_case"]["replay_evidence"] = copy.deepcopy(evidence[key])
    if finalization_projection(ledger, escape_closure, plan) != finalization_projection(result["audit_remediation"], result["audit_escape_closure"], plan):
        raise ValueError("postcondition finalization changed immutable record content")
    return result


def finalize_records(
    *, ledger: dict, escape_closure: dict, audit_result: Path, plan_path: Path,
    preparation: Path, event: Path, receipts: dict[tuple[str, str], Path],
    repository: Path, head_sha: str, expected_base: str,
) -> dict:
    from certificate_postcondition_replay import verify_replay
    from certificate_replay_io import read_object, safe_read
    from handoff_postcondition import report_path

    plan = phase_plan("preparation", plan_path, audit_result, repository, head_sha, expected_base)
    validate_preparation_records(
        ledger=ledger, escape_closure=escape_closure, plan=plan,
        audit_report=load_json_artifact(audit_result, require_object=True),
        audit_report_sha256=hashlib.sha256(audit_result.read_bytes()).hexdigest(), head_sha=head_sha,
    )
    prepared, _ = read_object(preparation)
    artifacts = prepared.get("prepared_artifacts") or {}
    for name, record in (("audit_remediation", ledger), ("audit_escape_closure", escape_closure)):
        snapshot = report_path(preparation.parent, artifacts.get(name))
        if load_json_artifact(snapshot, require_object=True) != record:
            raise ValueError(f"finalization input differs from authenticated preparation {name}")
    source_snapshot = report_path(preparation.parent, artifacts.get("audit_source_result"))
    if safe_read(source_snapshot) != safe_read(audit_result):
        raise ValueError("finalization changed the immutable source audit bytes")
    selected = planned_items(plan)
    if set(receipts) != set(selected):
        raise ValueError("replay paths must cover exactly the recognized postconditions")
    verified = {
        key: verify_replay(
            repository, preparation, event, receipts[key], expected_command=item["command"],
            expected_anchor=plan["trusted_anchor_sha"], expected_material=head_sha,
            expected_base=expected_base,
            expected_source_kind=key[0], expected_source_id=key[1],
        ) for key, item in selected.items()
    }
    return expected_final_records(ledger, escape_closure, plan, verified)
