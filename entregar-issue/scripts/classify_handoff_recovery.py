#!/usr/bin/env python3
"""Classify governed handoff recovery from fresh remote identity.

An independent auditor may provide a recovery lower bound. In particular,
post-write-refreeze/requires_refreeze must never be downgraded to handoff-only
because the textual reason happens to be "handoff-stale".
"""
from __future__ import annotations

import argparse
import json
import posixpath
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact

SHA40 = re.compile(r"^[0-9a-f]{40}$", re.I)
CERT_PATH = ".audit/entregar-issue/handoff-ready.json"


def load(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value


def norm(value: str) -> str:
    raw = value.replace("\\", "/").strip()
    normalized = posixpath.normpath(raw)
    if not raw or raw.startswith("/") or normalized in {".", ".."} or normalized.startswith("../"):
        raise ValueError(f"invalid repository-relative path: {value!r}")
    return normalized


def emit(
    scope: str,
    reason: str,
    material: str | None = None,
    *,
    auditor_scope: str | None = None,
    auditor_requires_refreeze: bool = False,
) -> int:
    out = {"recovery_scope": scope, "reason": reason}
    if material:
        out["certified_material_head_sha"] = material
    if auditor_scope:
        out["auditor_recovery_scope"] = auditor_scope
    if auditor_requires_refreeze:
        out["auditor_requires_refreeze"] = True
    print(json.dumps(out, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--current-head-sha", required=True)
    parser.add_argument("--current-parent-sha", required=True)
    parser.add_argument("--current-changed-path", action="append", default=[])
    parser.add_argument(
        "--target-binding-status",
        choices=("current-target", "inherited-base-artifact", "foreign-target", "partial-current-target", "unbound-or-invalid"),
        default="current-target",
    )
    parser.add_argument("--certificate-repo-path", default=CERT_PATH)
    parser.add_argument(
        "--auditor-recovery-scope",
        choices=("handoff-only", "post-write-refreeze", "fresh-handoff-required"),
        help="Recovery scope returned by the immediately preceding independent audit.",
    )
    parser.add_argument(
        "--auditor-requires-refreeze",
        action="store_true",
        help="Preserve an auditor requires_refreeze=true lower bound.",
    )
    args = parser.parse_args()

    auditor_scope = args.auditor_recovery_scope
    auditor_requires_refreeze = bool(args.auditor_requires_refreeze)

    if args.target_binding_status != "current-target":
        return emit(
            "fresh-handoff-required",
            f"target-binding:{args.target_binding_status}",
            auditor_scope=auditor_scope,
            auditor_requires_refreeze=auditor_requires_refreeze,
        )

    try:
        cert = load(Path(args.certificate))
    except Exception as exc:
        print(f"BLOCK: invalid handoff certificate: {exc}")
        return 2

    identity = cert.get("identity") or {}
    material = str(identity.get("material_head_sha") or identity.get("head_sha") or "")
    current = str(args.current_head_sha)
    parent = str(args.current_parent_sha)
    if not all(SHA40.fullmatch(value) for value in (material, current, parent)):
        print("BLOCK: invalid material/current/parent SHA")
        return 2

    policy = cert.get("certificate_commit_policy") or {}
    if policy.get("mode") != "result-only-child":
        local_scope, local_reason = "post-write-refreeze", "non-result-only-certificate"
    else:
        try:
            allowed = {norm(str(path)) for path in policy.get("allowed_paths") or []}
            changed = {norm(str(path)) for path in args.current_changed_path if str(path).strip()}
            cert_path = norm(args.certificate_repo_path)
        except ValueError as exc:
            print(f"BLOCK: {exc}")
            return 2

        if current == material:
            local_scope, local_reason = "handoff-only", "material-head-stable-terminal-child-missing"
        elif parent != material:
            local_scope, local_reason = "post-write-refreeze", "current-parent-differs-from-certified-material"
        elif changed - allowed:
            local_scope, local_reason = "post-write-refreeze", "terminal-candidate-contains-material-paths"
        elif not changed or cert_path not in changed:
            local_scope, local_reason = "handoff-only", "terminal-child-incomplete-or-missing-certificate"
        else:
            local_scope, local_reason = "terminal-handoff-valid", "direct-result-only-child"

    # Independent-audit recovery metadata is a lower bound for material recovery.
    # It may make the action stricter, but a generic stale-handoff reason can never
    # downgrade an explicit refreeze requirement to handoff-only.
    if auditor_scope == "fresh-handoff-required":
        return emit(
            "fresh-handoff-required",
            "auditor-recovery-floor:fresh-handoff-required",
            material,
            auditor_scope=auditor_scope,
            auditor_requires_refreeze=auditor_requires_refreeze,
        )
    if auditor_requires_refreeze or auditor_scope == "post-write-refreeze":
        if local_scope != "fresh-handoff-required":
            return emit(
                "post-write-refreeze",
                "auditor-recovery-floor:post-write-refreeze",
                material,
                auditor_scope=auditor_scope,
                auditor_requires_refreeze=auditor_requires_refreeze,
            )

    return emit(
        local_scope,
        local_reason,
        material,
        auditor_scope=auditor_scope,
        auditor_requires_refreeze=auditor_requires_refreeze,
    )


if __name__ == "__main__":
    raise SystemExit(main())
