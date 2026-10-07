from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_audit_remediation.py"


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def audit(head: str) -> dict:
    return {
        "rejection_id": "audit-rejection:synthetic-gate-001",
        "head_sha": head,
        "findings": [{
            "id": "F-GATE-001",
            "remediation_mode": "targeted-remediation",
            "failed_gate": {
                "name": "format-check",
                "command": "npm run format:check",
                "deterministic": True,
                "subject_sha": head,
                "observed_exit_code": 1,
                "evidence_sha256": "a" * 64,
            },
        }],
        "recommendations": [],
    }


def ledger(report_path: Path, old_head: str, new_head: str, replay_command: str) -> dict:
    return {
        "schema_version": 1,
        "contract_version": "2026-08-20.3",
        "resolution_policy": "all-actionable-items",
        "source": {
            "rejection_id": "audit-rejection:synthetic-gate-001",
            "audit_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "audited_head_sha": old_head,
        },
        "candidate_head_sha": new_head,
        "remediation_mode": "targeted-remediation",
        "items": [{
            "source_kind": "finding",
            "source_id": "F-GATE-001",
            "remediation_mode": "targeted-remediation",
            "status": "fixed",
            "closure_kind": "deterministic-gate-replay",
            "changed_files": ["src/example.ts"],
            "evidence": ["evidence/remediation.log"],
            "validations": [replay_command],
            "original_failed_gate": {
                "name": "format-check",
                "command": "npm run format:check",
                "subject_sha": old_head,
                "exit_code": 1,
                "evidence_sha256": "a" * 64,
            },
            "revalidation": {
                "command": replay_command,
                "subject_sha": new_head,
                "exit_code": 0,
                "evidence_sha256": "b" * 64,
                "equivalence": "exact-command-replay",
            },
        }],
        "status": "closed",
    }


def run_case(replay_command: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        old_head = "1" * 40
        new_head = "2" * 40
        report = base / "audit.json"
        write(report, audit(old_head))
        remediation = base / "remediation.json"
        write(remediation, ledger(report, old_head, new_head, replay_command))
        return subprocess.run([sys.executable, str(SCRIPT), "--ledger", str(remediation), "--audit-result", str(report), "--head-sha", new_head], check=False, capture_output=True, text=True)


def test_exact_failed_gate_replay_closes_remediation() -> None:
    proc = run_case("npm run format:check")
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_substitute_check_cannot_close_failed_gate() -> None:
    proc = run_case("node --check src/example.ts")
    assert proc.returncode == 2
    assert "must replay the exact failed gate command" in proc.stdout
