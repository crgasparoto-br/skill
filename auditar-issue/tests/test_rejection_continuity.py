from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "classify_rejection_continuity.py"


def finding(command: str = "npm run format:check") -> dict:
    return {
        "id": "F-GATE-001",
        "requirement_id": "R-001",
        "escape_category": "execution-state-gap",
        "required_gate": "F01",
        "remediation_mode": "targeted-remediation",
        "failed_gate": {"command": command},
    }


def run(previous: dict, current: dict):
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        a = base / "previous.json"
        b = base / "current.json"
        a.write_text(json.dumps(previous), encoding="utf-8")
        b.write_text(json.dumps(current), encoding="utf-8")
        return subprocess.run([sys.executable, str(SCRIPT), "--previous-audit", str(a), "--current-audit", str(b)], capture_output=True, text=True)


def test_same_open_finding_reuses_rejection_id() -> None:
    rid = "audit-rejection:continuation-001"
    previous = {"rejection_id": rid, "findings": [finding()]}
    current = {"rejection_id": rid, "findings": [finding()]}
    proc = run(previous, current)
    assert proc.returncode == 0, proc.stdout
    assert "CONTINUATION" in proc.stdout


def test_same_open_finding_with_new_rejection_id_is_blocked() -> None:
    previous = {"rejection_id": "audit-rejection:continuation-001", "findings": [finding()]}
    current = {"rejection_id": "audit-rejection:unnecessary-new-002", "findings": [finding()]}
    proc = run(previous, current)
    assert proc.returncode == 2
    assert "must reuse rejection_id" in proc.stdout


def test_materially_new_finding_requires_new_rejection_id() -> None:
    rid = "audit-rejection:continuation-001"
    previous = {"rejection_id": rid, "findings": [finding()]}
    current = {"rejection_id": rid, "findings": [finding("npm run lint")]}
    proc = run(previous, current)
    assert proc.returncode == 2
    assert "requires a new rejection_id" in proc.stdout
