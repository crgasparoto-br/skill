#!/usr/bin/env python3
"""Build a tamper-evident handoff certificate after delivery readiness gates pass.

The certificate is bound to the *material* candidate SHA. When persisted in the
repository, it is expected to live in a direct result-only child commit whose
changed paths are explicitly allow-listed by the certificate. This avoids the
impossible self-reference of embedding a commit SHA inside a file that itself
changes that commit SHA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from audit_artifact_io import artifact_metadata, artifact_relative_paths, load_json_artifact

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_DIR = ".audit/entregar-issue"
DEFAULT_CERT_PATH = f"{DEFAULT_REPO_DIR}/handoff-ready.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def skill_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run(args: list[str]) -> list[str]:
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        raise RuntimeError(proc.stdout.strip() or "validator failed")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def issue_scope_digest(work_item_start_sha: str, material_head_sha: str, paths: list[str]) -> str:
    payload = {
        "work_item_start_sha": work_item_start_sha,
        "material_head_sha": material_head_sha,
        "issue_changed_paths": sorted(set(paths)),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def normalize_repo_path(value: str) -> str:
    raw = value.replace("\\", "/").strip()
    normalized = posixpath.normpath(raw)
    if not raw or raw.startswith("/") or normalized in {".", ".."} or normalized.startswith("../"):
        raise ValueError(f"invalid repository-relative path: {value!r}")
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specification-snapshot", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int, help="Canonical issue represented by the delivery; mandatory for PR-scoped subjects")
    parser.add_argument("--work-item-kind", choices=("issue", "pr"), required=True)
    parser.add_argument("--work-item-number", required=True, type=int)
    parser.add_argument("--pull-request", type=int, help="Legacy alias for --pull-request-number")
    parser.add_argument("--pull-request-number", type=int)
    parser.add_argument("--work-item-start-sha", help="Immutable SHA observed before the issue implementation began")
    parser.add_argument("--issue-changed-path", action="append", default=[], help="Path from work_item_start_sha..material_head_sha; repeat for every path")
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--requirement-closure", required=True)
    parser.add_argument("--evidence-profile", choices=("auto", "light", "standard", "critical"), default="auto")
    parser.add_argument("--standard-evidence")
    parser.add_argument("--attack-matrix")
    parser.add_argument("--risk-saturation")
    parser.add_argument("--inherited-controls")
    parser.add_argument("--evidence-provenance")
    parser.add_argument("--audit-escape-closure")
    parser.add_argument("--learning-closure")
    parser.add_argument("--audit-remediation")
    parser.add_argument("--audit-source-result")
    parser.add_argument("--previous-independent-rejection", action="store_true")
    parser.add_argument("--remediation-mode", choices=("targeted-remediation", "systemic-remediation", "mixed-remediation"), default="targeted-remediation")
    parser.add_argument("--previous-inherited-controls")
    parser.add_argument("--previous-audit-escape-closure")
    parser.add_argument("--head-sha", required=True, help="Material candidate SHA, before the result-only handoff commit")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--merge-preview-sha", help="Merge preview for the material candidate SHA")
    parser.add_argument("--contract-version", default="2026-08-20.3")
    parser.add_argument("--artifact-repo-dir", default=DEFAULT_REPO_DIR)
    parser.add_argument("--certificate-repo-path", default=DEFAULT_CERT_PATH)
    parser.add_argument("--allow-result-path", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    profile = args.evidence_profile
    if profile == "auto":
        if args.standard_evidence:
            profile = "standard"
        elif any((args.attack_matrix, args.risk_saturation, args.inherited_controls)):
            profile = "critical"
        else:
            profile = "light"

    files = {
        "specification_snapshot": Path(args.specification_snapshot).resolve(),
        "requirement_closure": Path(args.requirement_closure).resolve(),
    }
    if profile == "standard":
        if not args.standard_evidence:
            print("BLOCK: standard evidence profile requires --standard-evidence")
            return 2
        files["standard_evidence"] = Path(args.standard_evidence).resolve()
    elif profile == "critical":
        missing = [name for name, value in (("attack-matrix", args.attack_matrix), ("risk-saturation", args.risk_saturation), ("inherited-controls", args.inherited_controls)) if not value]
        if missing:
            print("BLOCK: critical evidence profile requires " + ", ".join(missing))
            return 2
        files["requirement_attack_matrix"] = Path(args.attack_matrix).resolve()
        files["risk_saturation"] = Path(args.risk_saturation).resolve()
        files["inherited_controls"] = Path(args.inherited_controls).resolve()

    provenance_candidate = None
    if args.evidence_provenance:
        provenance_candidate = Path(args.evidence_provenance).resolve()
    elif args.attack_matrix:
        provenance_candidate = Path(args.attack_matrix).resolve().parent / "evidence-provenance.json"
    if provenance_candidate is not None and provenance_candidate.is_file():
        files["evidence_provenance"] = provenance_candidate
    if args.audit_escape_closure:
        files["audit_escape_closure"] = Path(args.audit_escape_closure).resolve()
    if args.learning_closure:
        files["learning_closure"] = Path(args.learning_closure).resolve()
    if args.audit_remediation:
        files["audit_remediation"] = Path(args.audit_remediation).resolve()
    if args.audit_source_result:
        files["audit_source_result"] = Path(args.audit_source_result).resolve()

    if args.previous_independent_rejection and "audit_remediation" not in files:
        print("BLOCK: previous independent rejection requires audit-remediation.json")
        return 2
    if args.previous_independent_rejection and "audit_source_result" not in files:
        print("BLOCK: previous independent rejection requires audit-source-result.json")
        return 2
    systemic_reaudit = args.previous_independent_rejection and args.remediation_mode in {"systemic-remediation", "mixed-remediation"}
    if args.previous_independent_rejection and "learning_closure" not in files:
        print("BLOCK: previous independent rejection requires learning-closure.json")
        return 2
    if args.previous_independent_rejection and "audit_escape_closure" not in files:
        print("BLOCK: previous independent rejection requires audit-escape-closure.json")
        return 2
    if args.previous_independent_rejection and not args.previous_audit_escape_closure:
        print("BLOCK: previous independent rejection requires previous audit-escape-closure snapshot")
        return 2
    if systemic_reaudit and profile != "critical":
        print("BLOCK: systemic audit remediation requires critical evidence profile")
        return 2
    if systemic_reaudit and not args.previous_inherited_controls:
        print("BLOCK: systemic independent rejection requires previous inherited-controls snapshot")
        return 2

    try:
        snapshot = load_json_artifact(files["specification_snapshot"], require_object=True)
    except Exception as exc:
        print(f"BLOCK: invalid specification snapshot for handoff subject: {exc}")
        return 2
    if not isinstance(snapshot, dict):
        print("BLOCK: specification snapshot must be an object")
        return 2
    issue_number = args.issue_number if args.issue_number is not None else (args.work_item_number if args.work_item_kind == "issue" else None)
    pull_request_number = args.pull_request_number if args.pull_request_number is not None else args.pull_request
    if args.work_item_kind == "pr":
        if pull_request_number is None:
            pull_request_number = args.work_item_number
        elif pull_request_number != args.work_item_number:
            print("BLOCK: PR subject requires pull-request-number equal to work-item-number")
            return 2
        if issue_number is None:
            print("BLOCK: PR subject requires canonical --issue-number; PR number must not substitute for issue number")
            return 2
    elif issue_number != args.work_item_number:
        print("BLOCK: issue subject requires issue-number equal to work-item-number")
        return 2
    if snapshot.get("repository") != args.repository:
        print("BLOCK: specification snapshot repository differs from handoff subject")
        return 2
    if snapshot.get("issue") != issue_number:
        print("BLOCK: specification snapshot issue differs from handoff subject")
        return 2

    issue_scope = None
    if args.work_item_start_sha:
        try:
            issue_paths = sorted({normalize_repo_path(value) for value in args.issue_changed_path})
        except ValueError as exc:
            print(f"BLOCK: {exc}")
            return 2
        issue_scope = {
            "schema_version": 1,
            "work_item_start_sha": args.work_item_start_sha,
            "material_head_sha": args.head_sha,
            "issue_changed_paths": issue_paths,
            "issue_delta_sha256": issue_scope_digest(args.work_item_start_sha, args.head_sha, issue_paths),
        }

    try:
        run([
            sys.executable, str(ROOT / "scripts" / "validate_specification_coverage.py"),
            "--specification-snapshot", str(files["specification_snapshot"]),
            "--requirement-closure", str(files["requirement_closure"]),
        ])
        handoff_args = [
            sys.executable, str(ROOT / "scripts" / "validate_handoff_readiness.py"),
            "--requirement-closure", str(files["requirement_closure"]),
            "--evidence-profile", profile,
            "--head-sha", args.head_sha,
            "--contract-version", args.contract_version,
        ]
        if profile == "standard":
            handoff_args.extend(["--standard-evidence", str(files["standard_evidence"])])
        elif profile == "critical":
            handoff_args.extend([
                "--attack-matrix", str(files["requirement_attack_matrix"]),
                "--risk-saturation", str(files["risk_saturation"]),
                "--inherited-controls", str(files["inherited_controls"]),
            ])
        if "evidence_provenance" in files:
            handoff_args.extend(["--evidence-provenance", str(files["evidence_provenance"])])
        if args.previous_independent_rejection:
            run([
                sys.executable, str(ROOT / "scripts" / "validate_audit_remediation.py"),
                "--ledger", str(files["audit_remediation"]),
                "--audit-result", str(files["audit_source_result"]),
                "--head-sha", args.head_sha,
            ])
            handoff_args.extend([
                "--previous-independent-rejection",
                "--remediation-mode",
                args.remediation_mode,
                "--previous-audit-escape-closure",
                str(Path(args.previous_audit_escape_closure).resolve()),
            ])
        if systemic_reaudit:
            handoff_args.extend([
                "--previous-inherited-controls",
                str(Path(args.previous_inherited_controls).resolve()),
            ])
        if "audit_escape_closure" in files:
            handoff_args.extend(["--audit-escape-closure", str(files["audit_escape_closure"])])
        if "learning_closure" in files:
            handoff_args.extend(["--learning-closure", str(files["learning_closure"])])
        run(handoff_args)
    except Exception as exc:
        print(f"BLOCK: handoff certificate not created: {exc}")
        return 2

    for name, path in files.items():
        if not path.is_file():
            print(f"BLOCK: missing artifact {name}: {path}")
            return 2

    if profile == "standard":
        standard = load_json_artifact(files["standard_evidence"], require_object=True)
        if standard.get("head_sha") != args.head_sha:
            print("BLOCK: standard evidence is not bound to material candidate head_sha")
            return 2
    elif profile == "critical":
        matrix = load_json_artifact(files["requirement_attack_matrix"], require_object=True)
        inherited = load_json_artifact(files["inherited_controls"], require_object=True)
        if matrix.get("head_sha") != args.head_sha or inherited.get("head_sha") != args.head_sha:
            print("BLOCK: critical readiness artifacts are not bound to material candidate head_sha")
            return 2

    try:
        artifact_repo_dir = normalize_repo_path(args.artifact_repo_dir)
        certificate_repo_path = normalize_repo_path(args.certificate_repo_path)
        allowed_paths = {certificate_repo_path}
        for path in files.values():
            for relative in artifact_relative_paths(path):
                allowed_paths.add(normalize_repo_path(posixpath.join(artifact_repo_dir, relative)))
        for value in args.allow_result_path:
            allowed_paths.add(normalize_repo_path(value))
    except ValueError as exc:
        print(f"BLOCK: {exc}")
        return 2

    validators = [
        ROOT / "scripts" / "validate_specification_coverage.py",
        ROOT / "scripts" / "validate_handoff_readiness.py",
        ROOT / "scripts" / "validate_standard_evidence.py",
        ROOT / "scripts" / "validate_requirement_attack_matrix.py",
        ROOT / "scripts" / "validate_evidence_freshness.py",
        ROOT / "scripts" / "validate_risk_saturation.py",
        ROOT / "scripts" / "validate_inherited_controls.py",
        ROOT / "scripts" / "validate_learning_closure.py",
        ROOT / "scripts" / "validate_independent_rejection_closure.py",
        ROOT / "scripts" / "validate_audit_remediation.py",
    ]
    payload = {
        "schema_version": 2,
        "status": "ready",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "identity": {
            # head_sha is retained as a compatibility alias for material_head_sha.
            "head_sha": args.head_sha,
            "material_head_sha": args.head_sha,
            "base_sha": args.base_sha,
            "merge_preview_sha": args.merge_preview_sha,
            "material_merge_preview_sha": args.merge_preview_sha,
        },
        "subject": {
            "repository": args.repository,
            "issue_number": issue_number,
            "pull_request_number": pull_request_number,
            "work_item_kind": args.work_item_kind,
            "work_item_number": args.work_item_number,
            "pull_request": pull_request_number,
            "base_ref": args.base_ref,
            "head_ref": args.head_ref,
        },
        "scope": issue_scope,
        "certificate_commit_policy": {
            "mode": "result-only-child",
            "allowed_paths": sorted(allowed_paths),
        },
        "contract_version": args.contract_version,
        "evidence_profile": profile,
        "remediation_mode": args.remediation_mode if args.previous_independent_rejection else None,
        "producer": {
            "skill": "entregar-issue",
            "skill_sha256": skill_hash(ROOT),
        },
        "validators": {path.name: sha256(path) for path in validators},
        "artifact_transport": {
            "version": 1,
            "supported_formats": ["plain-json", "base64-shards-v1"],
        },
        "artifacts": {
            name: artifact_metadata(path) for name, path in files.items()
        },
        "previous_independent_rejection": bool(args.previous_independent_rejection),
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"READY: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
