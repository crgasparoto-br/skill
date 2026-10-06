#!/usr/bin/env python3
"""Final fail-closed delivery completion guard.

This script is intentionally small and self-contained so it can run in local or
connector-only delivery workspaces. It verifies the final transport-specific
proof after CI is green and refuses stale/foreign handoff identities.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

GREEN_CI_STATES = {"green", "success", "completed-success", "completed/success"}


def _load_object(path: str, label: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} cannot be read: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return {}
    return value


def _first(value: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        current: Any = value
        for part in path:
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return None


def _check_equal(label: str, observed: Any, expected: Any, errors: list[str]) -> None:
    if expected is not None and observed != expected:
        errors.append(f"{label} differs: observed={observed!r} expected={expected!r}")


def _write_result(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-transport", choices=("certified-handoff", "native-github-audit"), required=True)
    parser.add_argument("--ci-state", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int)
    parser.add_argument("--pull-request-number", type=int)
    parser.add_argument("--material-head-sha", required=True)
    parser.add_argument("--current-head-sha", required=True)
    parser.add_argument("--target-binding")
    parser.add_argument("--terminal-handoff-proof")
    parser.add_argument("--terminal-native-audit-ready")
    parser.add_argument("--out")
    args = parser.parse_args()

    errors: list[str] = []
    normalized_ci = args.ci_state.strip().lower()
    if normalized_ci not in GREEN_CI_STATES:
        errors.append(f"CI material is not green: {args.ci_state}")

    published_handoff_head_sha: str | None = None

    if args.audit_transport == "certified-handoff":
        if not args.target_binding:
            errors.append("certified-handoff requires --target-binding")
            binding: dict[str, Any] = {}
        else:
            binding = _load_object(args.target_binding, "target binding", errors)
        status = _first(binding, ("status",), ("artifact_reuse", "status"))
        if status != "current-target":
            errors.append(f"target binding must be current-target, observed={status!r}")
        requires_fresh = _first(binding, ("requires_fresh_handoff",), ("artifact_reuse", "requires_fresh_handoff"))
        if requires_fresh is True:
            errors.append("target binding still requires a fresh handoff")

        expected_subject = _first(binding, ("expected_subject",), ("artifact_reuse", "expected_subject")) or {}
        observed_subject = _first(binding, ("observed_subject",), ("artifact_reuse", "observed_subject")) or {}
        if isinstance(expected_subject, dict):
            _check_equal("binding expected repository", expected_subject.get("repository"), args.repository, errors)
            _check_equal("binding expected issue_number", expected_subject.get("issue_number"), args.issue_number, errors)
            _check_equal("binding expected pull_request_number", expected_subject.get("pull_request_number"), args.pull_request_number, errors)
        if isinstance(observed_subject, dict):
            _check_equal("binding observed repository", observed_subject.get("repository"), args.repository, errors)
            if args.issue_number is not None and "issue_number" in observed_subject:
                _check_equal("binding observed issue_number", observed_subject.get("issue_number"), args.issue_number, errors)
            if args.pull_request_number is not None and "pull_request_number" in observed_subject:
                _check_equal("binding observed pull_request_number", observed_subject.get("pull_request_number"), args.pull_request_number, errors)

        if not args.terminal_handoff_proof:
            errors.append("certified-handoff requires --terminal-handoff-proof")
            proof: dict[str, Any] = {}
        else:
            proof = _load_object(args.terminal_handoff_proof, "terminal handoff proof", errors)
        proof_status = str(proof.get("status") or proof.get("decision") or "").upper()
        if proof_status != "READY":
            errors.append(f"terminal handoff proof must be READY, observed={proof_status!r}")
        if proof.get("audit_transport") not in (None, "certified-handoff"):
            errors.append("terminal handoff proof has the wrong audit transport")
        _check_equal("proof repository", proof.get("repository"), args.repository, errors)
        _check_equal("proof issue_number", proof.get("issue_number"), args.issue_number, errors)
        _check_equal("proof pull_request_number", proof.get("pull_request_number"), args.pull_request_number, errors)
        _check_equal("proof material_head_sha", proof.get("material_head_sha"), args.material_head_sha, errors)
        _check_equal("proof current_head_sha", proof.get("current_head_sha"), args.current_head_sha, errors)
        published_handoff_head_sha = proof.get("published_handoff_head_sha") or proof.get("published_head_sha")
        if not published_handoff_head_sha:
            errors.append("terminal handoff proof lacks published_handoff_head_sha")
        elif published_handoff_head_sha != args.current_head_sha:
            errors.append("published handoff head differs from freshly observed current head")
        if args.current_head_sha == args.material_head_sha:
            errors.append("certified-handoff current head is still the material head; result-only child is missing")

    else:
        if str(args.terminal_native_audit_ready or "").upper() != "READY":
            errors.append("native-github-audit requires terminal_native_audit_ready=READY")
        if args.current_head_sha != args.material_head_sha:
            errors.append("native-github-audit requires current_head_sha == material_head_sha")

    result = {
        "schema_version": 1,
        "status": "BLOCK" if errors else "READY",
        "audit_transport": args.audit_transport,
        "repository": args.repository,
        "issue_number": args.issue_number,
        "pull_request_number": args.pull_request_number,
        "ci_state": args.ci_state,
        "material_head_sha": args.material_head_sha,
        "current_head_sha": args.current_head_sha,
        "published_handoff_head_sha": published_handoff_head_sha,
        "errors": errors,
    }
    _write_result(args.out, result)

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print(
        "READY: delivery completion guard passed "
        f"for {args.repository} material={args.material_head_sha} current={args.current_head_sha} "
        f"transport={args.audit_transport}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
