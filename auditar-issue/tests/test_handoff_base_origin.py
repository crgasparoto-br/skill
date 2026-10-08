from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_delivery_preflight.py"


def run(candidate: Path, base_cert: Path | None):
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--certificate", str(candidate),
        "--artifacts-dir", str(candidate.parent),
        "--head-sha", "a" * 40,
        "--base-sha", "b" * 40,
        "--repository", "example/repo",
        "--issue-number", "379",
        "--work-item-kind", "issue",
        "--work-item-number", "379",
        "--pull-request-number", "380",
        "--base-ref", "develop",
        "--head-ref", "fix/379-collaborator-create",
        "--contract-version", "2026-08-20.3",
    ]
    if base_cert is not None:
        cmd.extend(["--base-certificate", str(base_cert)])
    return subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def foreign_certificate() -> dict:
    return {
        "schema_version": 2,
        "status": "ready",
        "identity": {
            "head_sha": "c" * 40,
            "material_head_sha": "c" * 40,
            "base_sha": "d" * 40,
        },
        "subject": {
            "repository": "example/repo",
            "issue_number": 365,
            "pull_request_number": 366,
            "work_item_kind": "issue",
            "work_item_number": 365,
            "pull_request": 366,
            "base_ref": "develop",
            "head_ref": "feat/365-install-product-defaults",
        },
        "certificate_commit_policy": {
            "mode": "result-only-child",
            "allowed_paths": [".audit/entregar-issue/handoff-ready.json"],
        },
        "contract_version": "2026-08-20.3",
        "producer": {"skill": "entregar-issue", "skill_sha256": "e" * 64},
        "artifacts": {},
    }


def test_foreign_handoff_identical_to_base_is_not_attributed_to_candidate():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        candidate = root / "handoff-ready.json"
        base_cert = root / "base-handoff-ready.json"
        raw = json.dumps(foreign_certificate(), sort_keys=True)
        candidate.write_text(raw, encoding="utf-8")
        base_cert.write_text(raw, encoding="utf-8")

        proc = run(candidate, base_cert)

        assert proc.returncode == 2
        assert "inherited-base-artifact" in proc.stdout
        assert "REASON: handoff-not-produced" in proc.stdout
        assert "RECOVERY: handoff-only" in proc.stdout
        assert "fresh-handoff-required" not in proc.stdout


def test_foreign_handoff_changed_from_base_keeps_fresh_handoff_required():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        candidate = root / "handoff-ready.json"
        base_cert = root / "base-handoff-ready.json"
        candidate.write_text(json.dumps(foreign_certificate()), encoding="utf-8")
        base_data = foreign_certificate()
        base_data["created_at"] = "older"
        base_cert.write_text(json.dumps(base_data), encoding="utf-8")

        proc = run(candidate, base_cert)

        assert proc.returncode == 2
        assert "RECOVERY: fresh-handoff-required" in proc.stdout
        assert "inherited-base-artifact" not in proc.stdout
