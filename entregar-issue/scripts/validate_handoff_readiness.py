#!/usr/bin/env python3
"""Fail closed before handing a delivery to an independent audit, proportionally to evidence profile."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from audit_artifact_io import load_json_artifact
from handoff_semantic_guards import validate_terminal_requirement_closure

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict:
    try:
        value = load_json_artifact(path)
    except Exception as exc:
        raise SystemExit(f"invalid JSON {path}: {exc}")
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def run_validator(args: list[str], errors: list[str]) -> None:
    proc = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if proc.returncode == 0:
        return
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    errors.extend(lines or [f"validator failed: {' '.join(args)}"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement-closure", required=True)
    parser.add_argument("--evidence-profile", choices=("light", "standard", "critical"), default="critical")
    parser.add_argument("--standard-evidence")
    parser.add_argument("--attack-matrix")
    parser.add_argument("--risk-saturation")
    parser.add_argument("--inherited-controls")
    parser.add_argument("--evidence-provenance")
    parser.add_argument("--audit-escape-closure")
    parser.add_argument("--learning-closure")
    parser.add_argument("--previous-inherited-controls")
    parser.add_argument("--historical-inherited-controls", action="append", default=[])
    parser.add_argument("--previous-audit-escape-closure")
    parser.add_argument("--previous-independent-rejection", action="store_true")
    parser.add_argument("--remediation-mode", choices=("targeted-remediation", "systemic-remediation", "mixed-remediation"), default="targeted-remediation")
    parser.add_argument("--head-sha")
    parser.add_argument("--contract-version", default="2026-08-20.3")
    args = parser.parse_args()

    errors: list[str] = []
    closure_path = Path(args.requirement_closure)
    closure = load(closure_path)
    validate_terminal_requirement_closure(closure, errors)

    structural = closure.get("structural_invariant_closures") or {}
    structural_flags = {"structural", "forbidden-implementation", "canonical-path", "dependency-independence", "precedence"}
    structural_obligations = [
        item for item in closure.get("obligations") or []
        if isinstance(item, dict)
        and structural_flags.intersection(item.get("flags") or [])
        and item.get("disposition") == "covered"
    ]
    if structural_obligations and structural.get("status") != "passed":
        errors.append("structural invariant gate is not passed")
    if structural_obligations:
        required_ids = {str(item.get("id")) for item in structural_obligations}
        linked_ids: set[str] = set()
        for entry in structural.get("entries") or []:
            if isinstance(entry, dict):
                linked_ids.update(str(value) for value in entry.get("obligation_ids") or [])
                if not entry.get("negative_control_evidence"):
                    errors.append(f"structural invariant {entry.get('id') or '?'} lacks negative control evidence")
                if len(str(entry.get("plausible_wrong_implementation") or "").strip()) < 20:
                    errors.append(f"structural invariant {entry.get('id') or '?'} lacks plausible wrong implementation")
        missing = required_ids - linked_ids
        if missing:
            errors.append(f"structural invariant gate does not cover obligations: {sorted(missing)}")
    if structural.get("unresolved_invariants"):
        errors.append("structural invariant gate has unresolved invariants")

    head_sha = str(args.head_sha or "")
    if args.evidence_profile == "light":
        pass
    elif args.evidence_profile == "standard":
        if not args.standard_evidence:
            errors.append("standard evidence profile requires standard-evidence.json")
        else:
            standard_path = Path(args.standard_evidence)
            if not standard_path.is_file():
                errors.append("standard-evidence.json is missing")
            else:
                standard = load(standard_path)
                observed_head = str(standard.get("head_sha") or "")
                if head_sha and observed_head != head_sha:
                    errors.append("standard evidence head_sha differs from candidate")
                head_sha = head_sha or observed_head
                run_validator([
                    sys.executable, str(ROOT / "scripts" / "validate_standard_evidence.py"),
                    "--requirement-closure", str(closure_path),
                    "--standard-evidence", str(standard_path),
                    "--head-sha", head_sha,
                    "--contract-version", args.contract_version,
                ], errors)
    else:
        attack_path = Path(args.attack_matrix) if args.attack_matrix else closure_path.parent / "requirement-attack-matrix.json"
        risk_path = Path(args.risk_saturation) if args.risk_saturation else closure_path.parent / "risk-saturation.json"
        inherited_path = Path(args.inherited_controls) if args.inherited_controls else closure_path.parent / "inherited-controls.json"
        default_provenance = closure_path.parent / "evidence-provenance.json"
        provenance_path = Path(args.evidence_provenance) if args.evidence_provenance else (default_provenance if default_provenance.is_file() else None)

        if not attack_path.is_file():
            errors.append("requirement-attack-matrix.json is missing")
        else:
            matrix = load(attack_path)
            observed_head = str(matrix.get("head_sha") or "")
            if head_sha and observed_head != head_sha:
                errors.append("attack matrix head_sha differs from candidate")
            head_sha = head_sha or observed_head
            documentation = closure.get("documentation_consistency") or {}
            if documentation.get("status") == "passed":
                has_documentation_family = any(
                    isinstance(item, dict) and (
                        "documentation" in {str(v) for v in item.get("risk_families") or []}
                        or any(
                            isinstance(surface, dict)
                            and str(surface.get("risk_family") or surface.get("family") or "") == "documentation"
                            for surface in item.get("risk_surfaces") or []
                        )
                    )
                    for item in matrix.get("requirements") or []
                )
                if not has_documentation_family:
                    errors.append("documentation consistency is material but requirement-attack-matrix lacks documentation risk family/canonical-claims surface")
            attack_args = [
                sys.executable, str(ROOT / "scripts" / "validate_requirement_attack_matrix.py"),
                "--requirement-closure", str(closure_path),
                "--attack-matrix", str(attack_path),
            ]
            if provenance_path is not None:
                if not provenance_path.is_file():
                    errors.append("evidence-provenance.json is missing")
                else:
                    attack_args.extend(["--evidence-provenance", str(provenance_path)])
                    run_validator([
                        sys.executable, str(ROOT / "scripts" / "validate_evidence_freshness.py"),
                        "--evidence-provenance", str(provenance_path),
                        "--material-head-sha", head_sha,
                    ], errors)
            run_validator(attack_args, errors)

        if not risk_path.is_file():
            errors.append("risk-saturation.json is missing")
        elif attack_path.is_file():
            risk_args = [
                sys.executable, str(ROOT / "scripts" / "validate_risk_saturation.py"),
                "--attack-matrix", str(attack_path),
                "--risk-saturation", str(risk_path),
                "--requirement-closure", str(closure_path),
            ]
            if inherited_path.is_file():
                risk_args.extend(["--inherited-controls", str(inherited_path)])
            run_validator(risk_args, errors)

        if not inherited_path.is_file():
            errors.append("inherited-controls.json is missing")
        elif head_sha:
            inherited_args = [
                sys.executable, str(ROOT / "scripts" / "validate_inherited_controls.py"),
                "--inherited-controls", str(inherited_path),
                "--head-sha", head_sha,
                "--attack-matrix", str(attack_path),
                "--requirement-closure", str(closure_path),
            ]
            if args.previous_independent_rejection and args.remediation_mode in {"systemic-remediation", "mixed-remediation"}:
                inherited_args.append("--previous-independent-rejection")
                if args.previous_inherited_controls:
                    inherited_args.extend(["--previous-inherited-controls", args.previous_inherited_controls])
                for historical in args.historical_inherited_controls:
                    inherited_args.extend(["--historical-inherited-controls", historical])
            run_validator(inherited_args, errors)

    systemic_reaudit = args.previous_independent_rejection and args.remediation_mode in {"systemic-remediation", "mixed-remediation"}
    escape_path = Path(args.audit_escape_closure) if args.audit_escape_closure else None
    learning_path = Path(args.learning_closure) if args.learning_closure else None
    if systemic_reaudit and args.evidence_profile != "critical":
        errors.append("systemic audit remediation requires critical evidence profile")
    if args.previous_independent_rejection and not escape_path:
        default_escape = closure_path.parent / "audit-escape-closure.json"
        escape_path = default_escape if default_escape.is_file() else None
    if args.previous_independent_rejection and not learning_path:
        default_learning = closure_path.parent / "learning-closure.json"
        learning_path = default_learning if default_learning.is_file() else None
    if args.previous_independent_rejection and not escape_path:
        errors.append("previous independent rejection requires audit-escape-closure.json")
    if args.previous_independent_rejection and not learning_path:
        errors.append("previous independent rejection requires learning-closure.json")
    if args.previous_independent_rejection and not args.previous_audit_escape_closure:
        errors.append("previous independent rejection requires previous audit-escape-closure snapshot")

    if learning_path:
        if not learning_path.is_file():
            errors.append("learning closure file is missing")
        else:
            run_validator([sys.executable, str(ROOT / "scripts" / "validate_learning_closure.py"), "--learning-closure", str(learning_path)], errors)
    if escape_path:
        if not escape_path.is_file():
            errors.append("audit escape closure file is missing")
        else:
            escape_args = [sys.executable, str(ROOT / "scripts" / "validate_audit_escape_lineage.py"), "--closure", str(escape_path)]
            if head_sha:
                escape_args.extend(["--head-sha", head_sha])
            if args.previous_independent_rejection and args.previous_audit_escape_closure:
                escape_args.extend([
                    "--require-previous",
                    "--previous-closure", args.previous_audit_escape_closure,
                ])
            run_validator(escape_args, errors)
    if args.previous_independent_rejection and learning_path and escape_path and learning_path.is_file() and escape_path.is_file():
        run_validator([
            sys.executable, str(ROOT / "scripts" / "validate_independent_rejection_closure.py"),
            "--learning-closure", str(learning_path), "--closure", str(escape_path),
        ], errors)

    if errors:
        for error in errors:
            print(error if error.startswith("BLOCK:") else f"BLOCK: {error}")
        return 2
    print(f"READY: {args.evidence_profile} handoff readiness is closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
