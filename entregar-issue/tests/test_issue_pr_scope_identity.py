from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER = ROOT / "scripts" / "delivery_target_binding.py"
CONTROLLER = ROOT / "scripts" / "controller_cli.py"


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def seed_pr_issue_package(repo: Path) -> None:
    audit = repo / ".audit" / "entregar-issue"
    write_json(audit / "handoff-ready.json", {
        "schema_version": 2,
        "status": "ready",
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
    })
    write_json(audit / "specification-snapshot.json", {
        "schema_version": 1,
        "repository": "owner/repo",
        "issue": 598,
        "sources": [],
    })


def test_pr_number_never_substitutes_for_issue_number_in_target_binding() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        seed_pr_issue_package(repo)
        proc = subprocess.run([
            sys.executable, str(CLASSIFIER),
            "--audit-dir", str(repo / ".audit" / "entregar-issue"),
            "--repository", "owner/repo",
            "--issue-number", "598",
            "--work-item-kind", "pr",
            "--work-item-number", "632",
            "--pull-request", "632",
            "--base-ref", "main",
            "--head-ref", "feat/598-financial-invariants",
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(proc.stdout)
        assert payload["status"] == "current-target"
        assert payload["expected_subject"]["issue_number"] == 598
        assert payload["expected_subject"]["pull_request_number"] == 632


def test_controller_preserves_issue_number_and_immutable_work_item_start_sha_for_pr_input() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        seed_pr_issue_package(repo)
        context = repo / ".audit" / "entregar-issue" / "controller-context.json"
        start_sha = "1" * 40
        proc = subprocess.run([
            sys.executable, str(CONTROLLER), "init-context",
            "--repository", "owner/repo",
            "--repository-path", str(repo),
            "--issue", "598",
            "--work-item-kind", "pr",
            "--work-item-number", "632",
            "--pull-request", "632",
            "--base-ref", "main",
            "--branch", "feat/598-financial-invariants",
            "--head-sha", start_sha,
            "--out", str(context),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(context.read_text(encoding="utf-8"))
        assert payload["issue"] == 598
        assert payload["pull_request"] == 632
        assert payload["work_item_start_sha"] == start_sha
        assert payload["artifact_reuse"]["status"] == "current-target"
