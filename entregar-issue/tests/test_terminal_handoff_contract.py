from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_terminal_handoff.py"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _fixture(base: Path, material: str = "a" * 40):
    artifacts = base / "artifacts"
    artifacts.mkdir()
    names = {
        "specification_snapshot": "specification-snapshot.json",
        "requirement_closure": "requirement-closure.json",
        "requirement_attack_matrix": "requirement-attack-matrix.json",
        "risk_saturation": "risk-saturation.json",
        "inherited_controls": "inherited-controls.json",
    }
    artifact_entries = {}
    for key, name in names.items():
        path = artifacts / name
        if key == "specification_snapshot":
            _write_json(path, {
                "schema_version": 1,
                "repository": "owner/repo",
                "issue": 42,
                "primary_source_id": "SRC-ISSUE",
                "sources": [],
            })
        else:
            path.write_text("{}\n", encoding="utf-8")
        artifact_entries[key] = {"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    cert = base / "handoff-ready.json"
    allowed = [".audit/entregar-issue/handoff-ready.json"] + [
        f".audit/entregar-issue/{name}" for name in names.values()
    ]
    _write_json(cert, {
        "schema_version": 2,
        "status": "ready",
        "subject": {
            "repository": "owner/repo",
            "issue_number": 42,
            "pull_request_number": 99,
            "work_item_kind": "issue",
            "work_item_number": 42,
            "pull_request": 99,
            "base_ref": "develop",
            "head_ref": "feature/test",
        },
        "identity": {"head_sha": material, "material_head_sha": material, "base_sha": "b" * 40},
        "certificate_commit_policy": {"mode": "result-only-child", "allowed_paths": allowed},
        "contract_version": "2026-08-20.3",
        "producer": {"skill": "entregar-issue", "skill_sha256": "c" * 64},
        "artifacts": artifact_entries,
        "previous_independent_rejection": False,
    })
    return cert, artifacts, allowed


def _run(
    cert: Path, artifacts: Path, material: str, published: str, parent: str, paths: list[str],
    *, repository: str = "owner/repo", work_item_kind: str = "issue", work_item_number: int = 42,
    issue_number: int | None = None, pull_request: int | None = 99, material_parent_inherited: Path | None = None,
    material_parent_escape: Path | None = None, previous_inherited: Path | None = None,
    previous_escape: Path | None = None, current: str | None = None,
    current_parent: str | None = None, current_paths: list[str] | None = None,
    post_handoff_paths: list[str] | None = None,
):
    cmd = [
        sys.executable, str(SCRIPT),
        "--certificate", str(cert),
        "--repository", repository,
        "--work-item-kind", work_item_kind,
        "--work-item-number", str(work_item_number),
        "--artifacts-dir", str(artifacts),
        "--material-head-sha", material,
        "--published-head-sha", published,
        "--published-parent-sha", parent,
        "--current-head-sha", current or published,
        "--current-parent-sha", current_parent or parent,
        "--base-sha", "b" * 40,
        "--base-ref", "develop",
        "--head-ref", "feature/test",
        "--contract-version", "2026-08-20.3",
    ]
    canonical_issue = issue_number if issue_number is not None else (work_item_number if work_item_kind == "issue" else None)
    if canonical_issue is not None:
        cmd += ["--issue-number", str(canonical_issue)]
    if pull_request is not None:
        cmd += ["--pull-request-number", str(pull_request)]
    if material_parent_inherited is not None:
        cmd += ["--material-parent-inherited-controls", str(material_parent_inherited)]
    if material_parent_escape is not None:
        cmd += ["--material-parent-audit-escape-closure", str(material_parent_escape)]
    if previous_inherited is not None:
        cmd += ["--previous-inherited-controls", str(previous_inherited)]
    if previous_escape is not None:
        cmd += ["--previous-audit-escape-closure", str(previous_escape)]
    for path in paths:
        cmd += ["--published-changed-path", path]
    for path in (current_paths if current_paths is not None else paths):
        cmd += ["--current-changed-path", path]
    for path in (post_handoff_paths or []):
        cmd += ["--post-handoff-changed-path", path]
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def test_terminal_guard_requires_actual_published_child() -> None:
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        cert, artifacts, allowed = _fixture(Path(td), material)
        proc = _run(cert, artifacts, material, material, material, [".audit/entregar-issue/handoff-ready.json"])
        assert proc.returncode == 2
        assert "remote head is still the material head" in proc.stdout


def test_terminal_guard_rejects_material_path_in_handoff_child() -> None:
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        published = "d" * 40
        cert, artifacts, allowed = _fixture(Path(td), material)
        proc = _run(cert, artifacts, material, published, material, [".audit/entregar-issue/handoff-ready.json", "server/app.ts"])
        assert proc.returncode == 2
        assert "non-handoff paths" in proc.stdout


def test_terminal_guard_accepts_direct_result_only_child() -> None:
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        published = "d" * 40
        cert, artifacts, allowed = _fixture(Path(td), material)
        proc = _run(cert, artifacts, material, published, material, [".audit/entregar-issue/handoff-ready.json"])
        assert proc.returncode == 0, proc.stdout
        assert "owner/repo issue #42" in proc.stdout
        assert "READY: terminal handoff published" in proc.stdout


def test_terminal_guard_rejects_material_commit_after_valid_handoff() -> None:
    """Regression: material M -> handoff H -> later material commit P must refreeze."""
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        published_handoff = "d" * 40
        current_material = "e" * 40
        cert, artifacts, _allowed = _fixture(Path(td), material)
        proc = _run(
            cert, artifacts, material, published_handoff, material,
            [".audit/entregar-issue/handoff-ready.json"],
            current=current_material,
            current_parent=published_handoff,
            current_paths=["server/modules/example/new-regression.test.ts"],
            post_handoff_paths=["server/modules/example/new-regression.test.ts"],
        )
        assert proc.returncode == 2
        assert "current remote head moved after handoff publication" in proc.stdout
        assert "post-handoff material write detected" in proc.stdout
        assert "RECOVERY: post-write-refreeze" in proc.stdout


def test_terminal_guard_requires_full_post_handoff_compare_when_head_moved() -> None:
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        published_handoff = "d" * 40
        current = "e" * 40
        cert, artifacts, _allowed = _fixture(Path(td), material)
        proc = _run(
            cert, artifacts, material, published_handoff, material,
            [".audit/entregar-issue/handoff-ready.json"],
            current=current,
            current_parent=published_handoff,
            current_paths=[".audit/entregar-issue/handoff-ready.json"],
        )
        assert proc.returncode == 2
        assert "post-handoff comparison paths are required" in proc.stdout


def test_terminal_guard_rejects_stale_publication_observation_even_without_material_path() -> None:
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        published_handoff = "d" * 40
        current = "e" * 40
        cert, artifacts, _allowed = _fixture(Path(td), material)
        proc = _run(
            cert, artifacts, material, published_handoff, material,
            [".audit/entregar-issue/handoff-ready.json"],
            current=current,
            current_parent=published_handoff,
            current_paths=[".audit/entregar-issue/handoff-ready.json"],
            post_handoff_paths=[".audit/entregar-issue/handoff-ready.json"],
        )
        assert proc.returncode == 2
        assert "current remote head moved after handoff publication" in proc.stdout
        assert "RECOVERY: terminal-head-reconciliation-required" in proc.stdout


def test_terminal_guard_rejects_handoff_subject_from_another_work_item() -> None:
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        published = "d" * 40
        cert, artifacts, allowed = _fixture(Path(td), material)
        proc = _run(cert, artifacts, material, published, material, [".audit/entregar-issue/handoff-ready.json"], work_item_number=43)
        assert proc.returncode == 2
        assert "certificate subject work_item_number differs" in proc.stdout
        assert "specification snapshot issue differs" in proc.stdout


def test_terminal_guard_rejects_forged_current_subject_with_stale_snapshot() -> None:
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        published = "d" * 40
        cert, artifacts, allowed = _fixture(Path(td), material)
        payload = json.loads(cert.read_text(encoding="utf-8"))
        payload["subject"]["work_item_number"] = 43
        _write_json(cert, payload)
        proc = _run(cert, artifacts, material, published, material, [".audit/entregar-issue/handoff-ready.json"], work_item_number=43)
        assert proc.returncode == 2
        assert "specification snapshot issue differs" in proc.stdout


def test_pending_ci_delegates_before_terminal_handoff() -> None:
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    remote = (ROOT / "references" / "remote-gate.md").read_text(encoding="utf-8")
    efficiency = (ROOT / "references" / "controller-execution-efficiency.md").read_text(encoding="utf-8")
    assert "handoff_required_before_return" not in terminal  # machine rule lives in ci-ownership.json
    assert "transferir ownership para `corrigir-ci`" in terminal
    assert "nao responder com pendencia remota" in remote
    assert "CI terminal verde" in efficiency


def test_terminal_systemic_reaudit_guard_requires_historical_snapshots() -> None:
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        published = "d" * 40
        cert, artifacts, allowed = _fixture(Path(td), material)
        payload = json.loads(cert.read_text(encoding="utf-8"))
        payload["previous_independent_rejection"] = True
        payload["evidence_profile"] = "critical"
        payload["remediation_mode"] = "systemic-remediation"
        _write_json(cert, payload)
        proc = _run(cert, artifacts, material, published, material, [".audit/entregar-issue/handoff-ready.json"])
        assert proc.returncode == 2
        assert "systemic terminal re-audit handoff requires previous inherited-controls snapshot" in proc.stdout
        assert "requires previous audit-escape-closure snapshot" in proc.stdout


def test_terminal_targeted_reaudit_does_not_require_previous_inherited_controls() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        material = "a" * 40
        published = "d" * 40
        cert, artifacts, allowed = _fixture(base, material)
        previous_escape = base / "previous-audit-escape-closure.json"
        _write_json(previous_escape, {"schema_version": 1, "escapes": []})
        payload = json.loads(cert.read_text(encoding="utf-8"))
        payload["previous_independent_rejection"] = True
        payload["evidence_profile"] = "standard"
        payload["remediation_mode"] = "targeted-remediation"
        _write_json(cert, payload)
        proc = _run(
            cert, artifacts, material, published, material,
            [".audit/entregar-issue/handoff-ready.json"],
            previous_escape=previous_escape,
        )
        assert proc.returncode == 2
        assert "previous inherited-controls snapshot" not in proc.stdout


def _escape(escape_id: str) -> dict:
    return {
        "escape_id": escape_id,
        "escape_class": "generic-lineage-regression",
        "plausible_wrong_implementation": "Replace the cumulative ledger with only the newest remediation entry.",
        "literal_case": {"status": "passed", "procedure": "Exercise the historical escape."},
        "sibling_cases": [
            {"id": "s1", "status": "passed"},
            {"id": "s2", "status": "passed"},
        ],
        "prevention_change": {"evidence": "prevention.log"},
        "detection_change": {"evidence": "detection.log"},
        "status": "passed",
    }


def test_terminal_guard_requires_material_parent_snapshots_for_lineage_artifacts() -> None:
    with tempfile.TemporaryDirectory() as td:
        material = "a" * 40
        published = "d" * 40
        cert, artifacts, _allowed = _fixture(Path(td), material)
        payload = json.loads(cert.read_text(encoding="utf-8"))
        payload["certificate_commit_policy"]["allowed_paths"].extend([
            ".audit/entregar-issue/audit-escape-closure.json",
            ".audit/entregar-issue/inherited-controls.json",
        ])
        _write_json(cert, payload)
        proc = _run(cert, artifacts, material, published, material, [
            ".audit/entregar-issue/handoff-ready.json",
            ".audit/entregar-issue/audit-escape-closure.json",
            ".audit/entregar-issue/inherited-controls.json",
        ])
        assert proc.returncode == 2
        assert "changed inherited-controls.json without material-parent snapshot" in proc.stdout
        assert "changed audit-escape-closure.json without material-parent snapshot" in proc.stdout


def test_terminal_guard_rejects_escape_removed_between_material_parent_and_result_child() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        material = "a" * 40
        published = "d" * 40
        cert, artifacts, _allowed = _fixture(base, material)
        current_escape = artifacts / "audit-escape-closure.json"
        _write_json(current_escape, {"schema_version": 1, "escapes": [_escape("LATEST")]})
        payload = json.loads(cert.read_text(encoding="utf-8"))
        payload["artifacts"]["audit_escape_closure"] = {
            "name": current_escape.name,
            "sha256": hashlib.sha256(current_escape.read_bytes()).hexdigest(),
        }
        payload["certificate_commit_policy"]["allowed_paths"].append(
            ".audit/entregar-issue/audit-escape-closure.json"
        )
        _write_json(cert, payload)
        parent_escape = base / "material-parent-audit-escape-closure.json"
        _write_json(parent_escape, {"schema_version": 1, "escapes": [_escape("A-003")]})

        proc = _run(
            cert, artifacts, material, published, material,
            [
                ".audit/entregar-issue/handoff-ready.json",
                ".audit/entregar-issue/audit-escape-closure.json",
            ],
            material_parent_escape=parent_escape,
        )
        assert proc.returncode == 2
        assert "previous escape ids disappeared: A-003" in proc.stdout
