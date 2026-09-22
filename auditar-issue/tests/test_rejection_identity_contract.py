from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_new_rejection_id_has_stable_contract_shape() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "new_rejection_id.py")],
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    value = proc.stdout.strip()
    assert value.startswith("audit-rejection:")
    assert len(value) >= 24


def test_external_audit_draft_carries_rejection_id_from_report_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "external-audit.json"
        subprocess.run([
            sys.executable, str(ROOT / "scripts" / "init_external_audit_report.py"),
            "--repository", "owner/repo",
            "--issue", "7",
            "--base-ref", "main",
            "--head-sha", "a" * 40,
            "--base-sha", "b" * 40,
            "--merge-preview-sha", "c" * 40,
            "--orchestration-cycle", "1",
            "--implementation-context-id", "implementation-context-1",
            "--audit-context-id", "audit-context-2",
            "--context-proof-kind", "agent-run-id",
            "--context-proof-value", "audit-context-2",
            "--context-proof-issuer", "independent-runner",
            "--origin", "Independent runner outside implementation context",
            "--out", str(out),
        ], check=True, stdout=subprocess.PIPE, text=True)
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["rejection_id"] == f"audit-rejection:{report['report_id']}"
