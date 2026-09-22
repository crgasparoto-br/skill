#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must be an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    try:
        manifest = load(Path(args.manifest))
    except Exception as exc:
        print(f"BLOCK: invalid audit transport manifest: {exc}")
        return 2

    errors: list[str] = []
    if manifest.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    repository = manifest.get("repository")
    if not isinstance(repository, str) or "/" not in repository:
        errors.append("repository must be owner/name")
    trusted_anchor_sha = str(manifest.get("trusted_anchor_sha") or "")
    if not HEX40.fullmatch(trusted_anchor_sha):
        errors.append("trusted_anchor_sha must be a 40-char lowercase hex SHA")

    contract = manifest.get("contract")
    if contract is not None and not isinstance(contract, dict):
        errors.append("contract must be an object when present")
        contract = None

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2

    qualifies = False
    reason = "no-trusted-native-contract"
    if contract:
        observed_at_sha = str(contract.get("observed_at_sha") or "")
        source_sha256 = str(contract.get("source_sha256") or "")
        source_git_blob_sha = str(contract.get("source_git_blob_sha") or "")
        legacy_policy = contract.get("legacy_handoff_policy")
        required_true = (
            contract.get("canonical") is True,
            contract.get("github_native_identity") is True,
            contract.get("exact_sha_evidence") is True,
            contract.get("independent_review") is True,
            contract.get("remote_ci_evidence") is True,
        )
        qualifies = (
            observed_at_sha == trusted_anchor_sha
            and (HEX64.fullmatch(source_sha256) is not None or HEX40.fullmatch(source_git_blob_sha) is not None)
            and contract.get("audit_mode") == "native-github"
            and legacy_policy in {"forbidden", "not-required"}
            and all(required_true)
            and isinstance(contract.get("path"), str)
            and bool(contract.get("path").strip())
        )
        if qualifies:
            reason = "trusted-canonical-native-audit-contract"
        elif observed_at_sha and observed_at_sha != trusted_anchor_sha:
            reason = "candidate-or-untrusted-contract-cannot-self-exempt"
        else:
            reason = "native-contract-incomplete"

    result = {
        "mode": "native-github-audit" if qualifies else "certified-handoff",
        "legacy_handoff_required": not qualifies,
        "trusted_anchor_sha": trusted_anchor_sha,
        "reason": reason,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
