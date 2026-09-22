#!/usr/bin/env python3
"""Producer-side terminal guard for a published result-only handoff child.

This validator intentionally requires a *published* child commit. It complements
validate_handoff_certificate.py, which can also validate the material head before
publication. Delivery must run this guard with freshly re-read remote metadata
immediately before returning or inviting an independent audit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from audit_artifact_io import load_json_artifact

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CERT_REPO_PATH = ".audit/entregar-issue/handoff-ready.json"
INHERITED_CONTROLS_REPO_PATH = ".audit/entregar-issue/inherited-controls.json"
AUDIT_ESCAPE_CLOSURE_REPO_PATH = ".audit/entregar-issue/audit-escape-closure.json"


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--work-item-kind", choices=("issue", "pr"), required=True)
    parser.add_argument("--work-item-number", required=True, type=int)
    parser.add_argument("--pull-request", type=int, help="Legacy alias for --pull-request-number")
    parser.add_argument("--pull-request-number", type=int)
    parser.add_argument("--base-ref")
    parser.add_argument("--head-ref")
    parser.add_argument("--artifacts-dir", required=True)
    parser.add_argument("--material-head-sha", required=True)
    parser.add_argument("--published-head-sha", required=True, help="Result-only handoff child SHA produced by this delivery")
    parser.add_argument("--published-parent-sha", required=True)
    parser.add_argument("--published-changed-path", action="append", default=[])
    parser.add_argument(
        "--current-head-sha", required=True,
        help="Freshly re-read remote HEAD after the last repository write; must equal the published handoff child",
    )
    parser.add_argument("--current-parent-sha", required=True)
    parser.add_argument("--current-changed-path", action="append", default=[])
    parser.add_argument(
        "--post-handoff-changed-path", action="append", default=[],
        help="Paths changed across published handoff head..current remote head; required when the head moved",
    )
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--contract-version")
    parser.add_argument("--certificate-repo-path", default=DEFAULT_CERT_REPO_PATH)
    parser.add_argument("--previous-inherited-controls")
    parser.add_argument("--previous-audit-escape-closure")
    parser.add_argument("--material-parent-inherited-controls")
    parser.add_argument("--material-parent-audit-escape-closure")
    args = parser.parse_args()

    errors: list[str] = []
    cert_path = Path(args.certificate).resolve()
    try:
        cert = load(cert_path)
    except Exception as exc:
        print(f"BLOCK: invalid handoff certificate: {exc}")
        return 2

    identity = cert.get("identity") or {}
    material = identity.get("material_head_sha") or identity.get("head_sha")
    policy = cert.get("certificate_commit_policy") or {}
    evidence_profile = str(cert.get("evidence_profile") or "critical").strip() or "critical"
    remediation_mode = str(cert.get("remediation_mode") or "targeted-remediation").strip() or "targeted-remediation"
    previous_rejection = bool(cert.get("previous_independent_rejection"))
    systemic_reaudit = previous_rejection and remediation_mode in {"systemic-remediation", "mixed-remediation"}

    subject = cert.get("subject")
    expected_issue_number = args.issue_number if args.issue_number is not None else (args.work_item_number if args.work_item_kind == "issue" else None)
    expected_pull_request = args.pull_request_number if args.pull_request_number is not None else args.pull_request
    if args.work_item_kind == "pr":
        expected_pull_request = args.work_item_number if expected_pull_request is None else expected_pull_request
        if expected_issue_number is None:
            errors.append("terminal PR target requires canonical issue-number")
    if not isinstance(subject, dict):
        errors.append("handoff certificate lacks semantic subject binding")
        subject = {}
    if subject.get("repository") != args.repository:
        errors.append("certificate subject repository differs from terminal target")
    if subject.get("work_item_kind") != args.work_item_kind:
        errors.append("certificate subject work_item_kind differs from terminal target")
    if subject.get("work_item_number") != args.work_item_number:
        errors.append("certificate subject work_item_number differs from terminal target")
    if subject.get("pull_request") != expected_pull_request:
        errors.append("certificate subject pull_request differs from terminal target")
    if "issue_number" in subject and subject.get("issue_number") != expected_issue_number:
        errors.append("certificate subject issue_number differs from terminal target")
    if "pull_request_number" in subject and subject.get("pull_request_number") != expected_pull_request:
        errors.append("certificate subject pull_request_number differs from terminal target")
    if args.base_ref is not None and subject.get("base_ref") != args.base_ref:
        errors.append("certificate subject base_ref differs from terminal target")
    if args.head_ref is not None and subject.get("head_ref") != args.head_ref:
        errors.append("certificate subject head_ref differs from terminal target")

    artifacts_dir = Path(args.artifacts_dir).resolve()
    snapshot_item = (cert.get("artifacts") or {}).get("specification_snapshot")
    snapshot = {}
    if not isinstance(snapshot_item, dict) or not snapshot_item.get("name"):
        errors.append("handoff certificate lacks specification snapshot artifact")
    else:
        snapshot_path = artifacts_dir / str(snapshot_item.get("name"))
        try:
            snapshot = load(snapshot_path)
        except Exception as exc:
            errors.append(f"cannot read specification snapshot for terminal subject validation: {exc}")
    if snapshot:
        if snapshot.get("repository") != args.repository:
            errors.append("specification snapshot repository differs from terminal target")
        if expected_issue_number is not None and snapshot.get("issue") != expected_issue_number:
            errors.append("specification snapshot issue differs from terminal target")

    if material != args.material_head_sha:
        errors.append("certificate material_head_sha differs from terminal material head")
    if policy.get("mode") != "result-only-child":
        errors.append("terminal handoff requires result-only-child policy")

    # The published handoff identity and the *current* remote identity are intentionally
    # separate. A caller must perform a fresh remote read after the last repository
    # write instead of reusing the response that created the handoff commit. This
    # closes the sequence M -> H(result-only) -> P(material), where H was once valid
    # but P became the real branch head before the delivery returned.
    current_changed = {
        str(path).replace("\\", "/").strip()
        for path in args.current_changed_path
        if str(path).strip()
    }
    if args.current_head_sha != args.published_head_sha:
        errors.append("current remote head moved after handoff publication")
        try:
            allowed_now = {
                str(path).replace("\\", "/").strip()
                for path in policy.get("allowed_paths") or []
                if str(path).strip()
            }
        except Exception:
            allowed_now = set()
        post_handoff_changed = {
            str(path).replace("\\", "/").strip()
            for path in args.post_handoff_changed_path
            if str(path).strip()
        }
        if not post_handoff_changed:
            errors.append("post-handoff comparison paths are required after remote head movement")
        material_paths = sorted(post_handoff_changed - allowed_now)
        if material_paths:
            errors.append(
                "post-handoff material write detected: " + ", ".join(material_paths)
            )
            errors.append("RECOVERY: post-write-refreeze")
        else:
            errors.append("RECOVERY: terminal-head-reconciliation-required")
    elif args.current_parent_sha != args.published_parent_sha:
        errors.append("fresh current parent differs from published handoff parent")
    elif current_changed != {
        str(path).replace("\\", "/").strip()
        for path in args.published_changed_path
        if str(path).strip()
    }:
        errors.append("fresh current changed paths differ from published handoff changed paths")
    if args.published_head_sha == args.material_head_sha:
        errors.append("handoff child was not published; remote head is still the material head")
    if args.published_parent_sha != args.material_head_sha:
        errors.append("published handoff head is not a direct child of the material head")
    changed = {str(path).replace("\\", "/").strip() for path in args.published_changed_path if str(path).strip()}
    if args.certificate_repo_path not in changed:
        errors.append("published handoff commit does not contain handoff-ready.json")

    if INHERITED_CONTROLS_REPO_PATH in changed and not args.material_parent_inherited_controls:
        errors.append("result-only child changed inherited-controls.json without material-parent snapshot")
    if AUDIT_ESCAPE_CLOSURE_REPO_PATH in changed and not args.material_parent_audit_escape_closure:
        errors.append("result-only child changed audit-escape-closure.json without material-parent snapshot")

    if previous_rejection:
        if not args.previous_audit_escape_closure:
            errors.append("terminal re-audit handoff requires previous audit-escape-closure snapshot")
        if systemic_reaudit and not args.previous_inherited_controls:
            errors.append("systemic terminal re-audit handoff requires previous inherited-controls snapshot")

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2

    cmd = [
        sys.executable, str(ROOT / "scripts" / "validate_handoff_certificate.py"),
        "--certificate", str(cert_path),
        "--artifacts-dir", str(artifacts_dir),
        "--head-sha", args.published_head_sha,
        "--base-sha", args.base_sha,
        "--candidate-parent-sha", args.published_parent_sha,
    ]
    for path in sorted(changed):
        cmd.extend(["--candidate-changed-path", path])
    if args.contract_version:
        cmd.extend(["--contract-version", args.contract_version])
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode != 0:
        print(proc.stdout.strip() or "BLOCK: handoff certificate validation failed")
        return 2

    artifacts = cert.get("artifacts") or {}

    def artifact_path(key: str) -> Path:
        item = artifacts.get(key) or {}
        return artifacts_dir / str(item.get("name") or "")

    if args.material_parent_audit_escape_closure:
        current_escape = artifact_path("audit_escape_closure")
        if not current_escape.is_file():
            print("BLOCK: result-only child changed audit-escape-closure.json but certificate lacks the published artifact")
            return 2
        proc = subprocess.run([
            sys.executable, str(ROOT / "scripts" / "validate_audit_escape_lineage.py"),
            "--closure", str(current_escape),
            "--previous-closure", str(Path(args.material_parent_audit_escape_closure).resolve()),
            "--require-previous",
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            print(proc.stdout.strip() or "BLOCK: result-only child audit escape lineage regressed from material parent")
            return 2

    if args.material_parent_inherited_controls:
        current_inherited = artifact_path("inherited_controls")
        current_attack = artifact_path("requirement_attack_matrix")
        current_closure = artifact_path("requirement_closure")
        if not current_inherited.is_file():
            print("BLOCK: result-only child changed inherited-controls.json but certificate lacks the published artifact")
            return 2
        inherited_cmd = [
            sys.executable, str(ROOT / "scripts" / "validate_inherited_controls.py"),
            "--inherited-controls", str(current_inherited),
            "--head-sha", args.material_head_sha,
            "--previous-inherited-controls", str(Path(args.material_parent_inherited_controls).resolve()),
        ]
        if current_attack.is_file():
            inherited_cmd.extend(["--attack-matrix", str(current_attack)])
        if current_closure.is_file():
            inherited_cmd.extend(["--requirement-closure", str(current_closure)])
        proc = subprocess.run(inherited_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            print(proc.stdout.strip() or "BLOCK: result-only child inherited control lineage regressed from material parent")
            return 2

    if previous_rejection:
        readiness = [
            sys.executable, str(ROOT / "scripts" / "validate_handoff_readiness.py"),
            "--requirement-closure", str(artifact_path("requirement_closure")),
            "--evidence-profile", evidence_profile,
            "--head-sha", str(args.material_head_sha),
            "--contract-version", str(cert.get("contract_version") or args.contract_version or "2026-08-20.3"),
            "--audit-escape-closure", str(artifact_path("audit_escape_closure")),
            "--learning-closure", str(artifact_path("learning_closure")),
            "--previous-independent-rejection",
            "--remediation-mode", remediation_mode,
            "--previous-audit-escape-closure", str(Path(args.previous_audit_escape_closure).resolve()),
        ]
        if evidence_profile == "standard":
            readiness.extend(["--standard-evidence", str(artifact_path("standard_evidence"))])
        elif evidence_profile == "critical":
            readiness.extend([
                "--attack-matrix", str(artifact_path("requirement_attack_matrix")),
                "--risk-saturation", str(artifact_path("risk_saturation")),
                "--inherited-controls", str(artifact_path("inherited_controls")),
            ])
        if systemic_reaudit:
            readiness.extend([
                "--previous-inherited-controls", str(Path(args.previous_inherited_controls).resolve()),
            ])
        if args.material_parent_inherited_controls:
            readiness.extend([
                "--historical-inherited-controls",
                str(Path(args.material_parent_inherited_controls).resolve()),
            ])
        provenance = artifacts.get("evidence_provenance")
        if isinstance(provenance, dict) and provenance.get("name"):
            readiness.extend(["--evidence-provenance", str(artifact_path("evidence_provenance"))])
        proc = subprocess.run(readiness, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode != 0:
            print(proc.stdout.strip() or "BLOCK: published re-audit handoff semantic validation failed")
            return 2

    print(
        "READY: terminal handoff published "
        f"{args.published_head_sha} for {args.repository} {args.work_item_kind} #{args.work_item_number} "
        f"material head {args.material_head_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
