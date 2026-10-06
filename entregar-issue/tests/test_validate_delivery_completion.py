from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_delivery_completion.py"


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _certified(tmp_path: Path, binding_status: str = "current-target", current: str | None = None):
    material = "a" * 40
    handoff = "b" * 40
    observed_current = current or handoff
    binding = tmp_path / "binding.json"
    proof = tmp_path / "proof.json"
    _write(binding, {
        "status": binding_status,
        "requires_fresh_handoff": binding_status != "current-target",
        "expected_subject": {"repository": "owner/repo", "issue_number": 42, "pull_request_number": 99},
        "observed_subject": {"repository": "owner/repo", "issue_number": 42, "pull_request_number": 99},
    })
    _write(proof, {
        "status": "READY",
        "audit_transport": "certified-handoff",
        "repository": "owner/repo",
        "issue_number": 42,
        "pull_request_number": 99,
        "material_head_sha": material,
        "published_handoff_head_sha": handoff,
        "current_head_sha": handoff,
    })
    proc = subprocess.run([
        sys.executable, str(SCRIPT),
        "--audit-transport", "certified-handoff",
        "--ci-state", "success",
        "--repository", "owner/repo",
        "--issue-number", "42",
        "--pull-request-number", "99",
        "--material-head-sha", material,
        "--current-head-sha", observed_current,
        "--target-binding", str(binding),
        "--terminal-handoff-proof", str(proof),
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc


def test_certified_completion_accepts_current_target_and_terminal_proof(tmp_path: Path) -> None:
    proc = _certified(tmp_path)
    assert proc.returncode == 0, proc.stdout
    assert "READY: delivery completion guard passed" in proc.stdout


def test_certified_completion_rejects_inherited_base_artifact(tmp_path: Path) -> None:
    proc = _certified(tmp_path, binding_status="inherited-base-artifact")
    assert proc.returncode == 2
    assert "current-target" in proc.stdout
    assert "requires a fresh handoff" in proc.stdout


def test_certified_completion_rejects_stale_terminal_head(tmp_path: Path) -> None:
    proc = _certified(tmp_path, current="c" * 40)
    assert proc.returncode == 2
    assert "proof current_head_sha differs" in proc.stdout or "freshly observed current head" in proc.stdout


def test_native_completion_requires_exact_material_head() -> None:
    material = "a" * 40
    proc = subprocess.run([
        sys.executable, str(SCRIPT),
        "--audit-transport", "native-github-audit",
        "--ci-state", "green",
        "--repository", "owner/repo",
        "--issue-number", "42",
        "--pull-request-number", "99",
        "--material-head-sha", material,
        "--current-head-sha", material,
        "--terminal-native-audit-ready", "READY",
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout


def test_native_completion_rejects_head_drift() -> None:
    proc = subprocess.run([
        sys.executable, str(SCRIPT),
        "--audit-transport", "native-github-audit",
        "--ci-state", "green",
        "--repository", "owner/repo",
        "--material-head-sha", "a" * 40,
        "--current-head-sha", "b" * 40,
        "--terminal-native-audit-ready", "READY",
    ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 2
    assert "current_head_sha == material_head_sha" in proc.stdout
