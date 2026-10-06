#!/usr/bin/env python3
"""Canonical controller utilities for the issue engineering skill ecosystem."""
from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from controller_contract_runtime import CONTRACT_VERSION, METRIC_NAMES, validate_controller_context
from delivery_target_binding import classify_delivery_target

ROOT = Path(__file__).resolve().parents[1]
MATERIAL_IDENTITY_FIELDS = {"head_sha", "base_sha", "merge_preview_sha"}
IDENTITY_PATCH_FIELDS = MATERIAL_IDENTITY_FIELDS | {"captured_at", "observed_at"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def load_array_or_key(path: Path, key: str) -> list[Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, dict):
        value = value.get(key)
    if not isinstance(value, list):
        raise ValueError(f"expected JSON array or object containing {key}: {path}")
    return value


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_context(payload: dict[str, Any]) -> None:
    validate_controller_context(payload)


def semantic_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = deepcopy(payload)
    for field in ("metrics", "controller_revision", "created_at", "updated_at"):
        snapshot.pop(field, None)
    identity = snapshot.get("identity")
    if isinstance(identity, dict):
        identity.pop("observed_at", None)
    return snapshot


def init_context(args: argparse.Namespace) -> int:
    timestamp = now()
    work_item_kind = args.work_item_kind
    work_item_number = args.work_item_number or args.issue
    artifact_reuse = classify_delivery_target(
        audit_dir=Path(args.repository_path).resolve() / ".audit" / "entregar-issue",
        repository=args.repository,
        issue_number=args.issue,
        work_item_kind=work_item_kind,
        work_item_number=work_item_number,
        pull_request=args.pull_request,
        base_ref=args.base_ref,
        head_ref=args.branch,
        repository_path=Path(args.repository_path).resolve(),
        base_sha=args.base_sha,
    )
    payload = {
        "schema_version": 1,
        "contract_version": CONTRACT_VERSION,
        "controller_context_id": args.controller_context_id or f"delivery-{uuid.uuid4()}",
        "controller_revision": 1,
        "controller_cycle": args.controller_cycle,
        "controller_cycle_limit": args.controller_cycle_limit,
        "repository": args.repository,
        "repository_path": str(Path(args.repository_path).resolve()),
        "issue": args.issue,
        "work_item_start_sha": args.work_item_start_sha or args.head_sha,
        "base_ref": args.base_ref,
        "branch": args.branch,
        "pull_request": args.pull_request,
        "identity": {
            "head_sha": args.head_sha,
            "base_sha": args.base_sha,
            "merge_preview_sha": args.merge_preview_sha,
            "captured_at": timestamp,
            "observed_at": timestamp,
        },
        "permissions": {
            "may_write_code": True,
            "may_update_issue": False,
            "may_merge": False,
            "may_execute_destructive_actions": False,
        },
        "workflow_policy": {
            "workflow_change_authorized": args.allow_workflow_changes,
            "manual_approval_workflow_authorized": False,
            "remote_action_mode": "observe-only",
            "publish_policy": "single-final-candidate",
        },
        "workflow_inventory": [],
        "baseline": {},
        "source_manifest": {},
        "artifact_reuse": artifact_reuse,
        "metrics": {name: 0 for name in METRIC_NAMES},
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    validate_context(payload)
    save(Path(args.out).resolve(), payload)
    print(f"{Path(args.out).resolve()} artifact-reuse={artifact_reuse['status']} fresh-handoff-required={str(artifact_reuse['requires_fresh_handoff']).lower()}")
    return 0


def record_metric(args: argparse.Namespace) -> int:
    path = Path(args.context).resolve()
    payload = load(path)
    validate_context(payload)
    if args.metric not in METRIC_NAMES:
        raise ValueError(f"unsupported metric: {args.metric}")
    if args.amount < 0 and payload["metrics"][args.metric] + args.amount < 0:
        raise ValueError("metric value cannot become negative")
    payload["metrics"][args.metric] += args.amount
    # Telemetry is deliberately non-semantic. It must not invalidate stage fingerprints.
    payload["updated_at"] = now()
    validate_context(payload)
    save(path, payload)
    print(path)
    return 0


def parse_metric_spec(spec: str) -> tuple[str, int]:
    name, separator, amount_text = spec.partition("=")
    name = name.strip()
    amount = int(amount_text) if separator else 1
    if name not in METRIC_NAMES:
        raise ValueError(f"unsupported metric: {name}")
    return name, amount


def apply_metric(payload: dict[str, Any], name: str, amount: int) -> None:
    current = payload["metrics"][name]
    if amount < 0 and current + amount < 0:
        raise ValueError("metric value cannot become negative")
    payload["metrics"][name] = current + amount


def refresh_context(args: argparse.Namespace) -> int:
    path = Path(args.context).resolve()
    payload = load(path)
    validate_context(payload)
    before_payload = deepcopy(payload)
    before_semantic = semantic_snapshot(payload)

    if args.base_ref is not None:
        payload["base_ref"] = args.base_ref
    if args.branch is not None:
        payload["branch"] = args.branch
    if args.pull_request is not None:
        payload["pull_request"] = args.pull_request

    previous_binding = payload.get("artifact_reuse") if isinstance(payload.get("artifact_reuse"), dict) else {}
    previous_subject = previous_binding.get("expected_subject") if isinstance(previous_binding, dict) else {}
    if not isinstance(previous_subject, dict):
        previous_subject = {}
    payload["artifact_reuse"] = classify_delivery_target(
        audit_dir=Path(payload["repository_path"]).resolve() / ".audit" / "entregar-issue",
        repository=payload["repository"],
        issue_number=int(payload["issue"]),
        work_item_kind=str(previous_subject.get("work_item_kind") or "issue"),
        work_item_number=int(previous_subject.get("work_item_number") or payload["issue"]),
        pull_request=payload.get("pull_request"),
        base_ref=payload.get("base_ref"),
        head_ref=payload.get("branch"),
        repository_path=Path(payload["repository_path"]).resolve(),
        base_sha=payload.get("identity", {}).get("base_sha"),
    )

    if args.identity_file:
        identity_patch = load(Path(args.identity_file).resolve())
        unknown = set(identity_patch) - IDENTITY_PATCH_FIELDS
        if unknown:
            raise ValueError(f"unsupported identity fields: {', '.join(sorted(unknown))}")
        old_material = {field: payload["identity"].get(field) for field in MATERIAL_IDENTITY_FIELDS}
        for field in MATERIAL_IDENTITY_FIELDS:
            if field in identity_patch:
                payload["identity"][field] = identity_patch[field]
        material_changed = any(
            old_material[field] != payload["identity"].get(field)
            for field in MATERIAL_IDENTITY_FIELDS
        )
        observed_at = identity_patch.get("observed_at") or now()
        payload["identity"]["observed_at"] = observed_at
        if material_changed:
            payload["identity"]["captured_at"] = identity_patch.get("captured_at") or observed_at

    if args.workflow_inventory_file:
        payload["workflow_inventory"] = load_array_or_key(
            Path(args.workflow_inventory_file).resolve(), "workflow_inventory"
        )
    if args.baseline_file:
        payload["baseline"] = load(Path(args.baseline_file).resolve())
    if args.source_manifest_file:
        payload["source_manifest"] = load(Path(args.source_manifest_file).resolve())
    for spec in args.metric:
        name, amount = parse_metric_spec(spec)
        apply_metric(payload, name, amount)

    semantic_changed = semantic_snapshot(payload) != before_semantic
    payload_changed = payload != before_payload
    binding_status = payload["artifact_reuse"]["status"]
    if semantic_changed:
        payload["controller_revision"] += 1
        payload["updated_at"] = now()
        validate_context(payload)
        save(path, payload)
        print(f"context-updated {path} artifact-reuse={binding_status}")
    elif payload_changed:
        payload["updated_at"] = now()
        validate_context(payload)
        save(path, payload)
        print(f"context-observed {path} artifact-reuse={binding_status}")
    else:
        print(f"context-unchanged {path} artifact-reuse={binding_status}")
    return 0


def advance_cycle(args: argparse.Namespace) -> int:
    path = Path(args.context).resolve()
    payload = load(path)
    validate_context(payload)
    current = int(payload["controller_cycle"])
    limit = int(payload["controller_cycle_limit"])
    if current >= limit:
        raise ValueError("controller cycle limit reached")
    payload["controller_cycle"] = current + 1
    payload["controller_revision"] += 1
    payload["updated_at"] = now()
    validate_context(payload)
    save(path, payload)
    print(path)
    return 0


def validate_contracts(args: argparse.Namespace) -> int:
    skills_root = Path(args.skills_root).resolve()
    canonical = ROOT / "contracts"
    manifest = load(canonical / "manifest.json")
    failures: list[str] = []
    for skill_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
        version_path = skill_dir / "contracts" / "version.json"
        if not version_path.is_file():
            continue
        version = load(version_path)
        if version.get("contract_version") != CONTRACT_VERSION:
            failures.append(f"{skill_dir.name}: contract version mismatch")
        schema_path = skill_dir / "schemas" / "subskill-result.schema.json"
        if schema_path.is_file():
            digest = hashlib.sha256(schema_path.read_bytes()).hexdigest()
            if digest != manifest["files"]["subskill-result.schema.json"]:
                failures.append(f"{skill_dir.name}: subskill schema drift")
        contract_schema_path = skill_dir / "contracts" / "subskill-result.schema.json"
        if contract_schema_path.is_file():
            digest = hashlib.sha256(contract_schema_path.read_bytes()).hexdigest()
            if digest != manifest["files"]["subskill-result.schema.json"]:
                failures.append(f"{skill_dir.name}: packaged subskill schema drift")
    canonical_contract_files = [
        "stage-dependencies.json", "gate-registry.json", "ci-ownership.json", "github-actions-policy.md",
    ]
    for name in canonical_contract_files:
        contract_path = skills_root / "entregar-issue" / "contracts" / name
        if contract_path.is_file():
            digest = hashlib.sha256(contract_path.read_bytes()).hexdigest()
            if digest != manifest["files"][name]:
                failures.append(f"entregar-issue: {name} drift")
    ci_copy = skills_root / "corrigir-ci" / "contracts" / "ci-ownership.json"
    if ci_copy.is_file():
        digest = hashlib.sha256(ci_copy.read_bytes()).hexdigest()
        if digest != manifest["files"]["ci-ownership.json"]:
            failures.append("corrigir-ci: ci ownership contract drift")
    if failures:
        for failure in failures:
            print(f"error: {failure}")
        return 1
    print("contracts-valid")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init-context")
    init.add_argument("--repository", required=True)
    init.add_argument("--repository-path", required=True)
    init.add_argument("--issue", type=int, required=True)
    init.add_argument("--work-item-kind", choices=("issue", "pr"), default="issue")
    init.add_argument("--work-item-number", type=int)
    init.add_argument("--base-ref", required=True)
    init.add_argument("--branch", required=True)
    init.add_argument("--pull-request", type=int)
    init.add_argument("--head-sha")
    init.add_argument("--work-item-start-sha", help="Immutable head observed before the current issue starts; defaults to --head-sha")
    init.add_argument("--base-sha")
    init.add_argument("--merge-preview-sha")
    init.add_argument("--controller-context-id")
    init.add_argument("--controller-cycle", type=int, default=1, choices=range(1, 11))
    init.add_argument("--controller-cycle-limit", type=int, default=10, choices=range(1, 11))
    init.add_argument("--allow-workflow-changes", action="store_true")
    init.add_argument("--out", required=True)
    init.set_defaults(func=init_context)

    metric = sub.add_parser("record-metric")
    metric.add_argument("--context", required=True)
    metric.add_argument("--metric", required=True)
    metric.add_argument("--amount", type=int, default=1)
    metric.set_defaults(func=record_metric)

    refresh = sub.add_parser("refresh-context")
    refresh.add_argument("--context", required=True)
    refresh.add_argument("--base-ref")
    refresh.add_argument("--branch")
    refresh.add_argument("--pull-request", type=int)
    refresh.add_argument("--identity-file")
    refresh.add_argument("--workflow-inventory-file")
    refresh.add_argument("--baseline-file")
    refresh.add_argument("--source-manifest-file")
    refresh.add_argument("--metric", action="append", default=[], help="metric or metric=amount")
    refresh.set_defaults(func=refresh_context)

    cycle = sub.add_parser("advance-cycle")
    cycle.add_argument("--context", required=True)
    cycle.set_defaults(func=advance_cycle)

    contracts = sub.add_parser("validate-contracts")
    contracts.add_argument("--skills-root", required=True)
    contracts.set_defaults(func=validate_contracts)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
