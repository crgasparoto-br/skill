from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_result_only_pr_recovery.py"
CERT_PATH = ".audit/entregar-issue/handoff-ready.json"
AUDIT_PATH = ".audit/entregar-issue/audit-escape-closure.json"
MATERIAL = "a" * 40
OLD_HEAD = "b" * 40
NEW_HEAD = "c" * 40


def _write_cert(path: Path, *, material: str = MATERIAL, pr: int = 17, allowed: list[str] | None = None) -> None:
    path.write_text(json.dumps({
        "schema_version": 2,
        "status": "ready",
        "subject": {
            "repository": "owner/repo",
            "issue_number": 11,
            "pull_request_number": pr,
            "work_item_kind": "pr",
            "work_item_number": pr,
            "pull_request": pr,
            "base_ref": "develop",
            "head_ref": "feature/example",
        },
        "identity": {"head_sha": material, "material_head_sha": material, "base_sha": "d" * 40},
        "certificate_commit_policy": {
            "mode": "result-only-child",
            "allowed_paths": allowed or [CERT_PATH, AUDIT_PATH],
        },
    }) + "\n", encoding="utf-8")


def _run(current: Path, candidate: Path, *, current_head: str = OLD_HEAD, current_parent: str = MATERIAL,
         current_paths: list[str] | None = None, candidate_parent: str = MATERIAL,
         candidate_paths: list[str] | None = None, pr_state: str = "open") -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable, str(SCRIPT),
        "--current-certificate", str(current),
        "--candidate-certificate", str(candidate),
        "--current-head-sha", current_head,
        "--current-parent-sha", current_parent,
        "--candidate-parent-sha", candidate_parent,
        "--pr-state", pr_state,
    ]
    for path in current_paths if current_paths is not None else [CERT_PATH, AUDIT_PATH]:
        cmd += ["--current-changed-path", path]
    for path in candidate_paths if candidate_paths is not None else [CERT_PATH, AUDIT_PATH]:
        cmd += ["--candidate-changed-path", path]
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def test_safe_sibling_result_only_recovery_preserves_original_pr() -> None:
    with tempfile.TemporaryDirectory() as td:
        current = Path(td) / "current.json"
        candidate = Path(td) / "candidate.json"
        _write_cert(current)
        _write_cert(candidate)
        proc = _run(current, candidate)
        payload = json.loads(proc.stdout)
        assert proc.returncode == 0
        assert payload["strategy"] == "replace-result-only-child-in-original-pr"
        assert payload["requires_force_ref_update"] is True
        assert payload["force_scope"] == "branch-ref-only"
        assert payload["replacement_pr_budget"] == 0


def test_original_pr_at_material_head_uses_normal_single_publication() -> None:
    with tempfile.TemporaryDirectory() as td:
        current = Path(td) / "current.json"
        candidate = Path(td) / "candidate.json"
        _write_cert(current)
        _write_cert(candidate)
        proc = _run(current, candidate, current_head=MATERIAL, current_parent="e" * 40, current_paths=[])
        payload = json.loads(proc.stdout)
        assert proc.returncode == 0
        assert payload["strategy"] == "publish-in-original-pr"
        assert payload["requires_force_ref_update"] is False


def test_force_recovery_rejects_material_path_in_current_child() -> None:
    with tempfile.TemporaryDirectory() as td:
        current = Path(td) / "current.json"
        candidate = Path(td) / "candidate.json"
        _write_cert(current)
        _write_cert(candidate)
        proc = _run(current, candidate, current_paths=[CERT_PATH, "server/runtime.ts"])
        payload = json.loads(proc.stdout)
        assert proc.returncode == 2
        assert payload["strategy"] == "same-pr-normal-recovery"
        assert payload["reason"] == "current-child-contains-material-paths"


def test_force_recovery_rejects_candidate_material_path() -> None:
    with tempfile.TemporaryDirectory() as td:
        current = Path(td) / "current.json"
        candidate = Path(td) / "candidate.json"
        _write_cert(current)
        _write_cert(candidate)
        proc = _run(current, candidate, candidate_paths=[CERT_PATH, "server/runtime.ts"])
        payload = json.loads(proc.stdout)
        assert proc.returncode == 2
        assert payload["reason"] == "candidate-contains-material-paths"


def test_force_recovery_rejects_subject_drift() -> None:
    with tempfile.TemporaryDirectory() as td:
        current = Path(td) / "current.json"
        candidate = Path(td) / "candidate.json"
        _write_cert(current, pr=17)
        _write_cert(candidate, pr=18)
        proc = _run(current, candidate)
        payload = json.loads(proc.stdout)
        assert proc.returncode == 2
        assert payload["reason"].startswith("subject-drift:")


def test_closed_original_pr_is_only_case_that_requests_replacement() -> None:
    with tempfile.TemporaryDirectory() as td:
        current = Path(td) / "current.json"
        candidate = Path(td) / "candidate.json"
        _write_cert(current)
        _write_cert(candidate)
        proc = _run(current, candidate, pr_state="closed")
        payload = json.loads(proc.stdout)
        assert proc.returncode == 3
        assert payload["strategy"] == "replacement-pr-last-resort"
        assert payload["replacement_pr_budget"] == 1
