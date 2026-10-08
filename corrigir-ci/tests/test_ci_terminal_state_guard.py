from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_ci_terminal_state.py"
CERT_PATH = ".audit/entregar-issue/handoff-ready.json"


def write_certificate(path: Path, material: str, allowed_paths: list[str] | None = None) -> None:
    payload = {
        "schema_version": 2,
        "status": "ready",
        "identity": {
            "head_sha": material,
            "material_head_sha": material,
            "base_sha": "b" * 40,
        },
        "certificate_commit_policy": {
            "mode": "result-only-child",
            "allowed_paths": allowed_paths or [CERT_PATH, ".audit/entregar-issue/evidence/delivery.txt"],
        },
        "contract_version": "2026-08-20.3",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_guard(
    certificate: Path,
    material: str,
    current: str,
    parent: str,
    changed_paths: list[str],
) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--certificate",
        str(certificate),
        "--expected-material-head-sha",
        material,
        "--current-head-sha",
        current,
        "--current-parent-sha",
        parent,
        "--contract-version",
        "2026-08-20.3",
    ]
    for path in changed_paths:
        cmd.extend(["--current-changed-path", path])
    return subprocess.run(cmd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def test_accepts_direct_result_only_child_for_ci_fixed_material_head() -> None:
    with tempfile.TemporaryDirectory() as td:
        cert = Path(td) / "handoff-ready.json"
        material = "a" * 40
        child = "c" * 40
        write_certificate(cert, material)
        proc = run_guard(cert, material, child, material, [CERT_PATH])
        assert proc.returncode == 0, proc.stdout
        assert "READY: CI remediation terminal state" in proc.stdout


def test_rejects_stale_certificate_after_later_material_ci_fix() -> None:
    with tempfile.TemporaryDirectory() as td:
        cert = Path(td) / "handoff-ready.json"
        certified_material = "a" * 40
        ci_fixed_material = "d" * 40
        current = "e" * 40
        write_certificate(cert, certified_material)
        proc = run_guard(cert, ci_fixed_material, current, ci_fixed_material, [CERT_PATH])
        assert proc.returncode == 2
        assert "material_head_sha differs from CI-fixed material head" in proc.stdout
        assert "RECOVERY: post-write-refreeze" in proc.stdout


def test_rejects_material_commit_after_terminal_handoff_child() -> None:
    with tempfile.TemporaryDirectory() as td:
        cert = Path(td) / "handoff-ready.json"
        material = "a" * 40
        later_parent = "c" * 40
        later_material_head = "d" * 40
        write_certificate(cert, material)
        proc = run_guard(
            cert,
            material,
            later_material_head,
            later_parent,
            ["server/example.test.ts"],
        )
        assert proc.returncode == 2
        assert "not a direct child of the CI-fixed material head" in proc.stdout
        assert "non-handoff paths" in proc.stdout


def test_rejects_missing_terminal_child() -> None:
    with tempfile.TemporaryDirectory() as td:
        cert = Path(td) / "handoff-ready.json"
        material = "a" * 40
        write_certificate(cert, material)
        proc = run_guard(cert, material, material, "b" * 40, [CERT_PATH])
        assert proc.returncode == 2
        assert "terminal handoff child is missing" in proc.stdout
        assert "RECOVERY: handoff-only" in proc.stdout


def test_rejects_non_allowlisted_path_in_result_only_child() -> None:
    with tempfile.TemporaryDirectory() as td:
        cert = Path(td) / "handoff-ready.json"
        material = "a" * 40
        child = "c" * 40
        write_certificate(cert, material)
        proc = run_guard(cert, material, child, material, [CERT_PATH, "server/app.ts"])
        assert proc.returncode == 2
        assert "current terminal commit contains non-handoff paths" in proc.stdout
