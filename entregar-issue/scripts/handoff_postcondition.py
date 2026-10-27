#!/usr/bin/env python3
"""Immutable preparation snapshots and the final certificate's replay proof chain."""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from audit_artifact_io import artifact_metadata, artifact_relative_paths, load_json_artifact
from certificate_replay_io import MAX_INVENTORY_BYTES, digest, json_bytes, read_object, relative_path, safe_read

if TYPE_CHECKING:
    from pathlib import Path

PREFIX = ".audit/entregar-issue/"
PROOF_KIND = "certificate-postcondition-finalization"
MUTABLE = {"audit_remediation", "audit_escape_closure"}
INVARIANT_FIELDS = (
    "identity", "subject", "scope", "contract_version", "evidence_profile", "remediation_mode",
    "previous_independent_rejection", "producer", "validators", "controls", "artifact_transport",
)


def require_final_phase(cert: dict) -> None:
    markers = {"prepared_artifacts", "prepared_files", "postcondition_plan", "preparation_sha256"}
    if cert.get("phase") not in (None, "final") or markers.intersection(cert) or cert.get("release_authority") is False:
        raise ValueError("certificate preparation does not authorize final handoff")


def file_metadata(path: Path, root: Path) -> dict:
    return {"name": relative_path(path.relative_to(root).as_posix()), "sha256": digest(safe_read(path))}


def authenticated_path(root: Path, descriptor: dict) -> Path:
    if not isinstance(descriptor, dict) or set(descriptor) != {"name", "sha256"}:
        raise ValueError("postcondition proof requires a closed file descriptor")
    path = root / relative_path(descriptor["name"])
    if digest(safe_read(path)) != descriptor["sha256"]:
        raise ValueError("postcondition proof file hash mismatch")
    return path


def report_path(root: Path, descriptor: dict) -> Path:
    if not isinstance(descriptor, dict):
        raise ValueError("postcondition artifact metadata is missing")
    path = root / relative_path(descriptor.get("name"))
    safe_read(path)
    observed = artifact_metadata(path)
    observed["name"] = descriptor["name"]
    if not {"name", "sha256"}.issubset(descriptor) or any(observed.get(key) != value for key, value in descriptor.items()):
        raise ValueError("postcondition artifact metadata or transport differs from its bytes")
    return path


def prepare_payload(payload: dict, files: dict[str, Path], out: Path, plan_path: Path) -> dict:
    """Preserve every declared input byte without granting publication authority."""
    if out.name == "handoff-ready.json" or out.exists() or out.is_symlink():
        raise ValueError("preparation must use a fresh nonterminal output path")
    root = out.parent
    root.mkdir(parents=True, exist_ok=True)
    prepared = root / "prepared"
    if prepared.exists() or prepared.is_symlink():
        raise ValueError("preparation snapshots already exist")
    audit = files["requirement_closure"].parent
    inputs: dict[str, bytes] = {}
    for path in files.values():
        for relative in artifact_relative_paths(path):
            raw = safe_read(path.parent / relative_path(relative))
            if relative in inputs and inputs[relative] != raw:
                raise ValueError("preparation contains conflicting artifact names")
            inputs[relative] = raw
    for relative in payload["certificate_commit_policy"]["allowed_paths"]:
        if relative == PREFIX + "handoff-ready.json":
            continue
        if not relative.startswith(PREFIX):
            raise ValueError("postcondition preparation requires the canonical artifact namespace")
        name = relative_path(relative.removeprefix(PREFIX))
        if name not in inputs:
            inputs[name] = safe_read(audit / name)
    if len(inputs) > 10000 or sum(map(len, inputs.values())) > MAX_INVENTORY_BYTES:
        raise ValueError("preparation artifact inventory exceeds its bound")
    if any(name.startswith("postcondition/") for name in inputs):
        raise ValueError("preparation cannot contain a previous finalization chain")
    plan_raw = safe_read(plan_path)
    plan_target = root / "plan.json"
    if plan_target.exists() and safe_read(plan_target) != plan_raw:
        raise ValueError("preparation plan destination contains different bytes")
    prepared.mkdir()
    for name, raw in sorted(inputs.items()):
        destination = prepared / relative_path(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    if not plan_target.exists():
        plan_target.write_bytes(plan_raw)
    result = copy.deepcopy(payload)
    result.update({"phase": "preparation", "status": "prepared", "release_authority": False})
    result["certificate_commit_policy"]["allowed_paths"] = []
    result["prepared_artifacts"] = result.pop("artifacts")
    for item in result["prepared_artifacts"].values():
        item["name"] = "prepared/" + item["name"]
    result["prepared_files"] = [{"name": "prepared/" + name, "sha256": digest(raw)}
                                for name, raw in sorted(inputs.items())]
    result["postcondition_plan"] = file_metadata(plan_target, root)
    return result


def _proof_inputs(cert: dict, audit: Path) -> tuple[dict, Path, dict, Path, dict, Path]:
    proof_path = authenticated_path(audit, cert.get("postcondition_proof"))
    proof, _ = read_object(proof_path)
    if (set(proof) != {"schema_version", "kind", "preparation", "plan", "event", "receipts"}
            or proof.get("schema_version") != 1 or proof.get("kind") != PROOF_KIND):
        raise ValueError("unrecognized certificate finalization proof")
    preparation = authenticated_path(audit, proof["preparation"])
    prepared, _ = read_object(preparation)
    if (prepared.get("phase") != "preparation" or prepared.get("status") != "prepared"
            or prepared.get("release_authority") is not False or "artifacts" in prepared
            or prepared.get("certificate_commit_policy", {}).get("allowed_paths") != []):
        raise ValueError("preparation envelope has final handoff authority")
    if any(prepared.get(field) != cert.get(field) for field in INVARIANT_FIELDS):
        raise ValueError("final certificate changed immutable preparation identity or controls")
    plan_path = authenticated_path(audit, proof["plan"])
    if plan_path != authenticated_path(preparation.parent, prepared.get("postcondition_plan")):
        raise ValueError("final proof replaced the preparation plan")
    plan, _ = read_object(plan_path)
    event = authenticated_path(audit, proof["event"])
    return proof, preparation, prepared, plan_path, plan, event


def _verify_plan_source(plan: dict, source: dict, source_path: Path, head: str, base: str, items: list[dict]) -> None:
    from handoff_postcondition_records import planned_items
    selected = planned_items(plan)
    expected = {(item["source_kind"], item["source_id"]): item for item in items}
    if set(selected) != set(expected):
        raise ValueError("proof plan changed the recognized source postconditions")
    if (plan.get("material_head_sha") != head or plan.get("base_sha") != base
            or plan.get("audit_report_sha256") != digest(safe_read(source_path))
            or plan.get("trusted_anchor_sha") != source.get("trusted_anchor_sha")
            or plan.get("trusted_anchor_sha") != (source.get("identity") or {}).get("base_sha")
            or plan.get("rejection_id") != source.get("rejection_id")
            or plan.get("repository") != (source.get("identity") or {}).get("repository")):
        raise ValueError("proof plan differs from the immutable audit source")
    for key, item in expected.items():
        if any(selected[key].get(field) != value for field, value in item.items()):
            raise ValueError("proof plan changed the literal source gate")


def _verify_reports(cert: dict, audit: Path, prepared: dict, preparation: Path,
                    plan: dict, verified: dict) -> None:
    from handoff_postcondition_records import expected_final_records
    old = prepared["prepared_artifacts"]
    current = cert["artifacts"]
    if set(old) != set(current):
        raise ValueError("final certificate changed the prepared artifact inventory")
    before = {key: report_path(preparation.parent, meta) for key, meta in old.items()}
    after = {key: report_path(audit, meta) for key, meta in current.items()}
    expected = expected_final_records(
        load_json_artifact(before["audit_remediation"], require_object=True),
        load_json_artifact(before["audit_escape_closure"], require_object=True), plan, verified)
    for key in old:
        if key in MUTABLE:
            if safe_read(after[key]) != json_bytes(expected[key]):
                raise ValueError("final records differ from the exact replay-derived transition")
        elif safe_read(before[key]) != safe_read(after[key]):
            raise ValueError("final certificate changed an immutable prepared artifact")
    mutable_names = {meta["name"] for key, meta in old.items() if key in MUTABLE}
    for descriptor in prepared["prepared_files"]:
        path = authenticated_path(preparation.parent, descriptor)
        name = descriptor["name"]
        if not name.startswith("prepared/"):
            raise ValueError("prepared file lies outside the snapshot namespace")
        if name not in mutable_names and safe_read(audit / name.removeprefix("prepared/")) != safe_read(path):
            raise ValueError("final auxiliary evidence changed after preparation")


def _verification_identity(cert: dict, source_repository: Path | None, expected_base: str | None,
                           require_repository: bool) -> tuple[str, str]:
    identity = cert.get("identity") or {}
    head, base = identity.get("material_head_sha"), identity.get("base_sha")
    if expected_base is not None and base != expected_base:
        raise ValueError("finalization base differs from the externally authenticated base")
    if source_repository is not None and expected_base is None:
        raise ValueError("Git replay verification requires an externally authenticated base")
    if require_repository and source_repository is None:
        raise ValueError("final postcondition verification requires the source repository")
    return head, base


def verify_finalization(cert: dict, artifacts_dir: Path, source_repository: Path | None = None,
                        *, expected_base: str | None = None, require_repository: bool = False) -> None:
    """Authenticate data first; Git-backed callers then independently execute the trusted gate."""
    from certificate_postcondition_replay import postcondition_items, verify_postcondition_plan, verify_replay, verify_replay_receipt
    require_final_phase(cert)
    audit = artifacts_dir.absolute()
    source_meta = (cert.get("artifacts") or {}).get("audit_source_result")
    if source_meta is None:
        if "postcondition_proof" in cert or cert.get("previous_independent_rejection"):
            raise ValueError("final certificate lacks its original audit source")
        return
    source_path = report_path(audit, source_meta)
    source = load_json_artifact(source_path, require_object=True)
    items = postcondition_items(source)
    if not items and "postcondition_proof" not in cert:
        return
    if not items or cert.get("phase") != "final":
        raise ValueError("final postcondition certificate lacks a recognized final phase")
    head, base = _verification_identity(cert, source_repository, expected_base, require_repository)
    proof, preparation, prepared, plan_path, plan, event = _proof_inputs(cert, audit)
    _verify_plan_source(plan, source, source_path, head, base, items)
    if plan.get("repository") != (cert.get("subject") or {}).get("repository"):
        raise ValueError("postcondition audit belongs to another repository")
    selected = {(item["source_kind"], item["source_id"]): item for item in plan["items"]}
    receipts = proof["receipts"]
    if not isinstance(receipts, list) or len(receipts) != len(selected):
        raise ValueError("final proof lacks the complete replay inventory")
    verified, paths = {}, {}
    for row in receipts:
        if not isinstance(row, dict) or set(row) != {"source_kind", "source_id", "name", "sha256"}:
            raise ValueError("invalid final replay descriptor")
        key = row["source_kind"], row["source_id"]
        if key not in selected or key in verified:
            raise ValueError("duplicate or unrelated final replay")
        receipt = authenticated_path(audit, {name: row[name] for name in ("name", "sha256")})
        paths[key] = receipt
        verified[key] = verify_replay_receipt(
            preparation, event, receipt, expected_command=selected[key]["command"],
            expected_anchor=plan["trusted_anchor_sha"], expected_material=head, expected_base=base,
            expected_source_kind=key[0], expected_source_id=key[1])
    _verify_reports(cert, audit, prepared, preparation, plan, verified)
    allowed = cert.get("certificate_commit_policy", {}).get("allowed_paths")
    evidence_paths = finalization_paths(audit, cert["postcondition_proof"], proof, prepared)
    if not isinstance(allowed, list) or set(allowed) != set(evidence_paths):
        raise ValueError("final certificate result allowlist differs from the verified proof chain")
    if source_repository is not None:
        verify_postcondition_plan(plan_path, source_path, head, source_repository, expected_base=expected_base)
        for key, receipt in paths.items():
            verify_replay(source_repository, preparation, event, receipt, expected_command=selected[key]["command"],
                          expected_anchor=plan["trusted_anchor_sha"], expected_material=head, expected_base=expected_base,
                          expected_source_kind=key[0], expected_source_id=key[1])


def finalization_paths(audit: Path, descriptor: dict, proof: dict | None = None,
                       prepared: dict | None = None) -> list[str]:
    """Derive a closed publication inventory from authenticated proof inputs."""
    proof_path = authenticated_path(audit, descriptor)
    proof = proof if proof is not None else read_object(proof_path)[0]
    preparation = authenticated_path(audit, proof["preparation"])
    prepared = prepared if prepared is not None else read_object(preparation)[0]
    paths = {"handoff-ready.json", descriptor["name"]}
    for key in ("preparation", "plan", "event"):
        paths.add(proof[key]["name"])
    for row in proof["receipts"]:
        path = authenticated_path(audit, {key: row[key] for key in ("name", "sha256")})
        receipt = read_object(path)[0]
        paths.add(row["name"])
        paths.add((path.parent / relative_path(receipt["execution"]["raw_log_path"])).relative_to(audit).as_posix())
    for row in prepared["prepared_files"]:
        relative = relative_path(row["name"])
        if not relative.startswith("prepared/"):
            raise ValueError("prepared input outside snapshot namespace")
        paths.add((preparation.parent / relative).relative_to(audit).as_posix())
        paths.add(relative.removeprefix("prepared/"))
    return sorted(PREFIX + relative_path(path) for path in paths)
