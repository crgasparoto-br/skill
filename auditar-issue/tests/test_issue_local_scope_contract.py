from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_handoff_certificate.py"
HEAD = "d" * 40
BASE = "e" * 40
START = "c" * 40
ISSUE_PATH = "apps/api/src/financial-invariants-e2e.integration.test.ts"
INHERITED_PATH = "scripts/statement-visual/issue-568-financial-assistant-cancel-inflight.mjs"


def digest(paths: list[str]) -> str:
    payload = {
        "work_item_start_sha": START,
        "material_head_sha": HEAD,
        "issue_changed_paths": sorted(set(paths)),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(base: Path, *, grounding_sha: str | None = HEAD, declare_control: bool = True, growth_status: str = "passed") -> Path:
    grounding = base / "codebase-grounding.json"
    grounding.write_text(json.dumps({"schema_version": 1, "subject_sha": grounding_sha}), encoding="utf-8")
    growth = base / "code-growth.json"
    growth.write_text(json.dumps({
        "control_id": "CODE-GROWTH-001", "status": growth_status, "subject_sha": HEAD,
        "policy": {}, "blocking_files": [],
    }), encoding="utf-8")
    spec = base / "specification-snapshot.json"
    spec.write_text(json.dumps({"repository": "owner/repo", "issue": 598}), encoding="utf-8")
    closure = base / "requirement-closure.json"
    closure.write_text("{}\n", encoding="utf-8")
    cert = base / "handoff-ready.json"
    cert.write_text(json.dumps({
        "schema_version": 2,
        "status": "ready",
        "identity": {"head_sha": HEAD, "material_head_sha": HEAD, "base_sha": BASE},
        "subject": {
            "repository": "owner/repo",
            "issue_number": 598,
            "pull_request_number": 632,
            "work_item_kind": "pr",
            "work_item_number": 632,
            "pull_request": 632,
            "base_ref": "main",
            "head_ref": "feat/598-financial-invariants",
        },
        "scope": {
            "schema_version": 1,
            "work_item_start_sha": START,
            "material_head_sha": HEAD,
            "issue_changed_paths": [ISSUE_PATH],
            "issue_delta_sha256": digest([ISSUE_PATH]),
        },
        "certificate_commit_policy": {
            "mode": "result-only-child",
            "allowed_paths": [".audit/entregar-issue/handoff-ready.json"],
        },
        "contract_version": "2026-08-20.3",
        "evidence_profile": "light",
        "producer": {"skill": "entregar-issue", "skill_sha256": "a" * 64},
        "artifacts": {
            "specification_snapshot": {"name": spec.name, "sha256": sha(spec)},
            "requirement_closure": {"name": closure.name, "sha256": sha(closure)},
            "codebase_grounding": {"name": grounding.name, "sha256": sha(grounding)},
            "code_growth": {"name": growth.name, "sha256": sha(growth)},
        },
        "controls": {key: {"applicable": True} for key in ("codebase_grounding", "code_growth")} if declare_control else {},
        "previous_independent_rejection": False,
    }), encoding="utf-8")
    return cert


def run(cert: Path, base: Path, issue_paths: list[str]):
    cmd = [
        sys.executable, str(VALIDATOR),
        "--certificate", str(cert),
        "--artifacts-dir", str(base),
        "--head-sha", HEAD,
        "--base-sha", BASE,
        "--contract-version", "2026-08-20.3",
        "--repository", "owner/repo",
        "--work-item-kind", "pr",
        "--work-item-number", "632",
        "--issue-number", "598",
        "--pull-request-number", "632",
        "--base-ref", "main",
        "--head-ref", "feat/598-financial-invariants",
        "--work-item-start-sha", START,
    ]
    for path in issue_paths:
        cmd.extend(["--issue-changed-path", path])
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def test_pr_and_issue_identity_are_independent_and_issue_local_scope_is_accepted() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        cert = fixture(base)
        proc = run(cert, base, [ISSUE_PATH])
        assert proc.returncode == 0, proc.stdout


def test_code_scope_without_codebase_grounding_control_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        proc = run(fixture(base, declare_control=False), base, [ISSUE_PATH])
        assert proc.returncode == 2
        assert "omits codebase_grounding control" in proc.stdout
        assert "omits code_growth control" in proc.stdout


def test_stale_codebase_grounding_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        proc = run(fixture(base, grounding_sha=BASE), base, [ISSUE_PATH])
        assert proc.returncode == 2
        assert "codebase grounding is stale for material head" in proc.stdout


def test_blocked_code_growth_report_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        proc = run(fixture(base, growth_status="blocked"), base, [ISSUE_PATH])
        assert proc.returncode == 2
        assert "certified CODE-GROWTH-001 did not pass" in proc.stdout


def test_pr_wide_inherited_path_cannot_be_attributed_to_issue_local_delta() -> None:
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        cert = fixture(base)
        proc = run(cert, base, [ISSUE_PATH, INHERITED_PATH])
        assert proc.returncode == 2
        assert "issue_changed_paths differ from observed work-item delta" in proc.stdout


def test_skill_contract_forbids_out_of_scope_finding_from_pr_wide_diff_alone() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    evidence = (ROOT / "references" / "evidence-rules.md").read_text(encoding="utf-8")
    assert "inherited-pr-delta" in skill
    assert "nao pode gerar finding `fora do escopo`" in skill
    assert "Nao usar `base_ref..PR head` como prova de autoria" in evidence
