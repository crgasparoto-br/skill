"""Adversarial proof that no known risk surface or historical finding disappears."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "auditar-issue/scripts/validate_audit_completeness.py"
HEAD = "a" * 40
BASE = "b" * 40


def proof(root: Path, name: str) -> dict:
    path = root / "proofs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("independent replay of " + name, encoding="utf-8")
    return {"evidence_path": f"proofs/{name}",
            "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fixture(root: Path) -> tuple[dict, dict]:
    identity = {"repository": "org/test", "base_sha": BASE, "head_sha": HEAD}
    inventory = {
        "schema_version": 1, "identity": identity,
        "discovery": {"mode": "independent-rederivation",
                      "procedure": "Inspect issue, changed code, entrypoints and consumers separately",
                      "changed_paths": ["src/detector.py"]},
        "sources": [
            {"id": "issue", "kind": "specification", **proof(root, "issue.txt")},
            {"id": "diff", "kind": "diff", **proof(root, "diff.txt")},
        ],
        "requirements": [{"id": "REQ-1", "source_id": "issue"}],
        "surfaces": [
            {"id": "S1", "requirement_id": "REQ-1", "risk_family": "parser",
             "boundary": "production", "cost": "cheap"},
            {"id": "S2", "requirement_id": "REQ-1", "risk_family": "parser",
             "boundary": "external integration", "cost": "expensive"},
        ],
        "previous_findings": [{"id": "OLD-1", "source_url": "https://example.org/review/1"}],
    }
    diff_path = root / "proofs" / "diff.txt"
    diff_path.write_text(
        json.dumps({"base_sha": BASE, "head_sha": HEAD,
                    "changed_paths": ["src/detector.py"]}), encoding="utf-8"
    )
    inventory["sources"][1]["evidence_sha256"] = hashlib.sha256(diff_path.read_bytes()).hexdigest()
    report = {
        "schema_version": 1, "identity": identity, "verdict": "REPROVADA",
        "coverage": "comprehensive", "discovery_closed": True,
        "changed_path_reviews": [
            {"id": "src/detector.py", "status": "covered", "surface_ids": ["S1"],
             **proof(root, "changed-path.txt")},
        ],
        "requirements": [{"id": "REQ-1", "status": "covered", **proof(root, "req.txt")}],
        "surfaces": [
            {"id": "S1", "status": "covered", **proof(root, "s1.txt")},
            {"id": "S2", "status": "covered", **proof(root, "s2.txt")},
        ],
        "previous_findings": [
            {"id": "OLD-1", "disposition": "resolved",
             "reason": "The historical defect is covered by independent evidence",
             **proof(root, "old.txt")},
        ],
        "findings": [
            {"id": "NEW-1", "requirement_id": "REQ-1", "surface_id": "S1",
             "disposition": "blocking", "root_cause": "Violated invariant in parser",
             **proof(root, "finding.txt")},
        ],
        "blocking_ids": ["NEW-1"],
    }
    return inventory, report


def run(root: Path, inventory: dict, report: dict, head: str = HEAD) -> subprocess.CompletedProcess:
    (root / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--inventory", str(root / "inventory.json"),
         "--report-json", str(root / "report.json"), "--root", str(root), "--head-sha", head],
        capture_output=True, text=True, check=False,
    )


def test_complete_audit_can_publish(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    assert run(tmp_path, inv, report).returncode == 0


def test_missing_requirement_or_surface_is_blocked(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    report["requirements"] = []
    assert "omitted REQ-1" in run(tmp_path, inv, report).stdout
    _, report = fixture(tmp_path)
    report["surfaces"].pop()
    assert "omitted S2" in run(tmp_path, inv, report).stdout



def test_changed_path_is_not_silently_skipped(tmp_path: Path) -> None:
    inventory, report = fixture(tmp_path)
    report["changed_path_reviews"] = []
    assert "changed path not reviewed" in run(tmp_path, inventory, report).stdout


def test_diff_source_is_not_self_reported(tmp_path: Path) -> None:
    inventory, report = fixture(tmp_path)
    inventory["discovery"]["changed_paths"] = ["other/path.py"]
    assert "diverges from immutable Git diff" in run(tmp_path, inventory, report).stdout


def test_previously_reported_finding_cannot_disappear(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    report["previous_findings"] = []
    assert "silently dropped" in run(tmp_path, inv, report).stdout


def test_cheap_surface_must_be_checked_after_first_blocker(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    report["surfaces"][0] = {
        "id": "S1", "status": "not-executed",
        "reason": "An earlier blocking issue was already detected",
    }
    report["coverage"] = "limited"
    assert "cheap or mandatory" in run(tmp_path, inv, report).stdout


def test_expensive_unrelated_work_may_be_skipped_with_limited_label(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    report["surfaces"][1] = {
        "id": "S2", "status": "not-executed",
        "reason": "Expensive external integration check deferred after independent blocker",
    }
    report["coverage"] = "limited"
    assert run(tmp_path, inv, report).returncode == 0


def test_false_approval_and_false_completeness_are_blocked(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    report["verdict"] = "APROVADA"
    assert "require REPROVADA" in run(tmp_path, inv, report).stdout
    _, report = fixture(tmp_path)
    report["surfaces"][1] = {
        "id": "S2", "status": "not-executed",
        "reason": "Expensive validation intentionally deferred after known blocker",
    }
    assert "coverage declaration" in run(tmp_path, inv, report).stdout


def test_hash_stale_head_and_traversal_are_blocked(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    assert "stale HEAD" in run(tmp_path, inv, report, head="c" * 40).stdout
    inv, report = fixture(tmp_path)
    report["surfaces"][0]["evidence_sha256"] = "0" * 64
    assert "hash mismatch" in run(tmp_path, inv, report).stdout
    inv, report = fixture(tmp_path)
    report["surfaces"][0]["evidence_path"] = "../escape"
    assert "escapes workspace" in run(tmp_path, inv, report).stdout


def test_incomplete_discovery_and_fake_exemption_are_blocked(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    inv["discovery"]["mode"] = "implementer-claims"
    assert "independently rederived" in run(tmp_path, inv, report).stdout
    inv, report = fixture(tmp_path)
    report["surfaces"][0] = {
        "id": "S1", "status": "not-applicable",
        "reason": "Only a verified independent exemption is acceptable",
    }
    assert "evidence path" in run(tmp_path, inv, report).stdout


def test_no_unreported_blocker_and_no_premature_closure(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    report["blocking_ids"] = []
    assert "blocker ledger" in run(tmp_path, inv, report).stdout
    inv, report = fixture(tmp_path)
    report["discovery_closed"] = False
    assert "harvested" in run(tmp_path, inv, report).stdout


def test_no_finding_without_canonical_requirement(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    report["findings"][0]["requirement_id"] = "fabricated"
    assert "unknown requirement" in run(tmp_path, inv, report).stdout


def test_entrypoint_requires_completeness_gate() -> None:
    entry = (ROOT / "auditar-issue/SKILL.md").read_text(encoding="utf-8")
    assert "validate_audit_completeness.py" in entry
    reference = (ROOT / "auditar-issue/references/blocker-harvest.md").read_text(encoding="utf-8")
    assert "validate_audit_completeness.py" in reference
    delivery = (ROOT / "entregar-issue/SKILL.md").read_text(encoding="utf-8")
    assert "references/audit-readiness-exhaustive.md" in delivery
