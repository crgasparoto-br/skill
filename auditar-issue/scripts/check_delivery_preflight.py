#!/usr/bin/env python3
"""Single fail-closed, profile-aware preflight before spending an independent audit."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from audit_artifact_io import load_json_artifact
from handoff_origin import inherited_foreign_certificate_by_bytes
from preflight_semantic_guards import validate_terminal_requirement_closure

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], errors: list[str]) -> None:
    proc = subprocess.run(args, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        errors.extend(lines or [f"BLOCK: validator failed: {' '.join(args)}"])


def certified_artifact(cert: dict, artifacts_dir: Path, key: str) -> Path | None:
    item = (cert.get("artifacts") or {}).get(key)
    if not isinstance(item, dict):
        return None
    name = str(item.get("name") or "").strip()
    return artifacts_dir / name if name else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--base-certificate", help="handoff-ready.json read from the immutable base SHA, when present")
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--standard-evidence")
    parser.add_argument("--attack-matrix")
    parser.add_argument("--risk-saturation")
    parser.add_argument("--inherited-controls")
    parser.add_argument("--head-sha", required=True, help="Current published candidate head SHA")
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--work-item-kind", choices=("issue", "pr"), required=True)
    parser.add_argument("--work-item-number", type=int, required=True)
    parser.add_argument("--pull-request", type=int, help="Legacy alias for --pull-request-number")
    parser.add_argument("--pull-request-number", type=int)
    parser.add_argument("--work-item-start-sha")
    parser.add_argument("--issue-changed-path", action="append", default=[])
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--merge-preview-sha")
    parser.add_argument("--candidate-parent-sha")
    parser.add_argument("--candidate-changed-path", action="append", default=[])
    parser.add_argument("--previous-closure")
    parser.add_argument("--previous-inherited-controls")
    parser.add_argument("--contract-version", required=True)
    args = parser.parse_args()

    errors: list[str] = []

    # A foreign handoff that is byte-identical to the file already present on the immutable
    # base did not originate in this delivery. Treat it as inherited repository state and
    # report that the current target handoff was not produced, instead of classifying it as
    # a stale/foreign handoff authored by the candidate.
    try:
        candidate_cert = load_json_artifact(Path(args.certificate), require_object=True)
    except Exception as exc:
        print(f"BLOCK: invalid handoff certificate: {exc}")
        return 2
    base_certificate = Path(args.base_certificate) if args.base_certificate else None
    observed_pull_request = args.pull_request_number if args.pull_request_number is not None else args.pull_request
    if inherited_foreign_certificate_by_bytes(
        candidate_cert,
        candidate_certificate=Path(args.certificate),
        base_certificate=base_certificate,
        repository=args.repository,
        work_item_kind=args.work_item_kind,
        work_item_number=args.work_item_number,
        issue_number=args.issue_number,
        pull_request_number=observed_pull_request,
        base_ref=args.base_ref,
        head_ref=args.head_ref,
    ):
        print(
            "BLOCK: inherited-base-artifact: handoff-ready.json is unchanged from the immutable base "
            "and belongs to another delivery; the current target handoff was not produced"
        )
        print("REASON: handoff-not-produced")
        print("RECOVERY: handoff-only")
        return 2
    cert_args = [
        sys.executable, str(ROOT / "scripts" / "validate_handoff_certificate.py"),
        "--certificate", args.certificate,
        "--artifacts-dir", args.artifacts_dir,
        "--head-sha", args.head_sha,
        "--base-sha", args.base_sha,
        "--contract-version", args.contract_version,
        "--repository", args.repository,
        "--work-item-kind", args.work_item_kind,
        "--work-item-number", str(args.work_item_number),
    ]
    if args.issue_number is not None:
        cert_args.extend(["--issue-number", str(args.issue_number)])
    pull_request_number = args.pull_request_number if args.pull_request_number is not None else args.pull_request
    if pull_request_number is not None:
        cert_args.extend(["--pull-request-number", str(pull_request_number)])
    if args.work_item_start_sha is not None:
        cert_args.extend(["--work-item-start-sha", args.work_item_start_sha])
    for path in args.issue_changed_path:
        cert_args.extend(["--issue-changed-path", path])
    if args.base_ref is not None:
        cert_args.extend(["--base-ref", args.base_ref])
    if args.head_ref is not None:
        cert_args.extend(["--head-ref", args.head_ref])
    if args.merge_preview_sha is not None:
        cert_args.extend(["--merge-preview-sha", args.merge_preview_sha])
    if args.candidate_parent_sha is not None:
        cert_args.extend(["--candidate-parent-sha", args.candidate_parent_sha])
    for path in args.candidate_changed_path:
        cert_args.extend(["--candidate-changed-path", path])
    run(cert_args, errors)
    if errors:
        for error in errors:
            print(error if error.startswith(("BLOCK:", "RECOVERY:")) else f"BLOCK: {error}")
        return 2

    try:
        cert = load_json_artifact(Path(args.certificate), require_object=True)
    except Exception as exc:
        print(f"BLOCK: invalid handoff certificate after validation: {exc}")
        return 2
    identity = cert.get("identity") or {}
    material_head_sha = identity.get("material_head_sha") or identity.get("head_sha")
    if not material_head_sha:
        print("BLOCK: handoff certificate lacks material head identity")
        return 2
    profile = str(cert.get("evidence_profile") or "critical")
    if profile not in {"light", "standard", "critical"}:
        print("BLOCK: invalid evidence_profile in handoff certificate")
        return 2

    artifacts_dir = Path(args.artifacts_dir)
    specification_snapshot = certified_artifact(cert, artifacts_dir, "specification_snapshot")
    requirement_closure = certified_artifact(cert, artifacts_dir, "requirement_closure")
    if specification_snapshot is None or not specification_snapshot.is_file():
        errors.append("BLOCK: certified delivery packet lacks specification_snapshot artifact")
    if requirement_closure is None or not requirement_closure.is_file():
        errors.append("BLOCK: certified delivery packet lacks requirement_closure artifact")
        closure = None
    else:
        try:
            closure = load_json_artifact(requirement_closure, require_object=True)
            if not isinstance(closure, dict):
                raise ValueError("expected object")
        except Exception as exc:
            closure = None
            errors.append(f"BLOCK: invalid certified requirement closure: {exc}")
        else:
            closure_errors: list[str] = []
            validate_terminal_requirement_closure(closure, closure_errors)
            errors.extend(f"BLOCK: {item}" for item in closure_errors)
            if specification_snapshot is not None and specification_snapshot.is_file():
                run([
                    sys.executable, str(ROOT / "scripts" / "check_normative_section_coverage.py"),
                    "--specification-snapshot", str(specification_snapshot),
                    "--requirement-closure", str(requirement_closure),
                ], errors)

    if profile == "standard" and requirement_closure is not None:
        standard = certified_artifact(cert, artifacts_dir, "standard_evidence")
        if standard is None or not standard.is_file():
            errors.append("BLOCK: standard evidence profile lacks certified standard_evidence artifact")
        else:
            run([
                sys.executable, str(ROOT / "scripts" / "check_standard_evidence.py"),
                "--requirement-closure", str(requirement_closure),
                "--standard-evidence", str(standard),
                "--head-sha", material_head_sha,
                "--contract-version", args.contract_version,
            ], errors)
    elif profile == "critical":
        attack = certified_artifact(cert, artifacts_dir, "requirement_attack_matrix")
        risk = certified_artifact(cert, artifacts_dir, "risk_saturation")
        inherited = certified_artifact(cert, artifacts_dir, "inherited_controls")
        # Explicit args remain accepted for connector/materialization flows, but certificate names are authoritative.
        attack = attack if attack is not None else (Path(args.attack_matrix) if args.attack_matrix else None)
        risk = risk if risk is not None else (Path(args.risk_saturation) if args.risk_saturation else None)
        inherited = inherited if inherited is not None else (Path(args.inherited_controls) if args.inherited_controls else None)
        if attack is None or risk is None or inherited is None:
            errors.append("BLOCK: critical evidence profile lacks attack matrix, risk saturation or inherited controls")
        else:
            saturation_args = [
                sys.executable, str(ROOT / "scripts" / "check_delivery_saturation.py"),
                "--attack-matrix", str(attack),
                "--risk-saturation", str(risk),
                "--inherited-controls", str(inherited),
                "--head-sha", material_head_sha,
            ]
            evidence_provenance = certified_artifact(cert, artifacts_dir, "evidence_provenance")
            if evidence_provenance is not None:
                saturation_args.extend(["--evidence-provenance", str(evidence_provenance)])
            run(saturation_args, errors)

    growth_control = (cert.get("controls") or {}).get("code_growth") or {}
    if growth_control.get("applicable") is True:
        code_growth = certified_artifact(cert, artifacts_dir, "code_growth")
        if code_growth is None or not code_growth.is_file():
            errors.append("BLOCK: CODE-GROWTH-001 applicable but certified code_growth artifact is missing")
        else:
            run([
                sys.executable, str(ROOT / "scripts" / "check_code_growth_evidence.py"),
                "--report", str(code_growth), "--head-sha", material_head_sha,
            ], errors)

    if cert.get("previous_independent_rejection"):
        remediation=certified_artifact(cert, artifacts_dir, "audit_remediation")
        source=certified_artifact(cert, artifacts_dir, "audit_source_result")
        if remediation is None or source is None:
            errors.append("BLOCK: certified re-audit packet lacks audit remediation/source artifacts")
        else:
            run([sys.executable,str(ROOT / "scripts" / "validate_audit_remediation.py"),"--ledger",str(remediation),"--audit-result",str(source),"--head-sha",material_head_sha],errors)
        remediation_mode=str(cert.get("remediation_mode") or "targeted-remediation")
        if remediation_mode in {"systemic-remediation","mixed-remediation"}:
            if profile != "critical": errors.append("BLOCK: systemic audit remediation requires critical evidence profile")
            escape = certified_artifact(cert, artifacts_dir, "audit_escape_closure")
            learning = certified_artifact(cert, artifacts_dir, "learning_closure")
            inherited = certified_artifact(cert, artifacts_dir, "inherited_controls")
            if escape is None or learning is None or inherited is None:
                errors.append("BLOCK: systemic re-audit packet lacks escape, learning or inherited-control artifacts")
            else:
                reaudit_args=[sys.executable,str(ROOT / "scripts" / "check_reaudit_readiness.py"),"--closure",str(escape),"--learning-closure",str(learning),"--inherited-controls",str(inherited),"--head-sha",material_head_sha]
                if args.previous_closure is not None: reaudit_args.extend(["--previous-closure",args.previous_closure])
                if args.previous_inherited_controls is not None: reaudit_args.extend(["--previous-inherited-controls",args.previous_inherited_controls])
                run(reaudit_args,errors)
                run([sys.executable,str(ROOT / "scripts" / "validate_learning_closure.py"),"--learning-closure",str(learning)],errors)

    if errors:
        for error in errors:
            print(error if error.startswith(("BLOCK:", "RECOVERY:")) else f"BLOCK: {error}")
        return 2
    if args.head_sha != material_head_sha:
        print(f"READY: {profile} delivery child {args.head_sha} preserves material head {material_head_sha}")
    else:
        print(f"READY: {profile} delivery is ready for independent audit expenditure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
