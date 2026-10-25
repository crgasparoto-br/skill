"""Adversarial proof that no known risk surface or historical finding disappears."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "auditar-issue/scripts/validate_audit_completeness.py"
def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def create_git_fixture(root: Path) -> tuple[str, str]:
    checkout = root / "gitrepo"
    if checkout.exists():
        return git(checkout, "rev-parse", "HEAD~1"), git(checkout, "rev-parse", "HEAD")
    checkout.mkdir()
    git(checkout, "init", "-q")
    git(checkout, "config", "user.name", "Audit Fixture")
    git(checkout, "config", "user.email", "audit@example.invalid")
    candidate = checkout / "src/detector.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("value = 1\n", encoding="utf-8")
    git(checkout, "add", ".")
    git(checkout, "commit", "-qm", "base")
    base = git(checkout, "rev-parse", "HEAD")
    candidate.write_text("value = 2\n", encoding="utf-8")
    git(checkout, "add", ".")
    git(checkout, "commit", "-qm", "candidate")
    head = git(checkout, "rev-parse", "HEAD")
    return base, head




def proof(root: Path, name: str) -> dict:
    path = root / "proofs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("independent replay of " + name, encoding="utf-8")
    return {"evidence_path": f"proofs/{name}",
            "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fixture(root: Path) -> tuple[dict, dict]:
    base, head = create_git_fixture(root)
    identity = {"repository": "org/test", "base_sha": base, "head_sha": head}
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
        json.dumps({"base_sha": base, "head_sha": head,
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


def run(root: Path, inventory: dict, report: dict, head: str | None = None) -> subprocess.CompletedProcess:
    (root / "inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
    (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--inventory", str(root / "inventory.json"),
         "--report-json", str(root / "report.json"), "--root", str(root),
         "--git-repo", str(root / "gitrepo"),
         "--trusted-base-sha", git(root / "gitrepo", "rev-parse", "HEAD~1"),
         "--trusted-head-sha", git(root / "gitrepo", "rev-parse", "HEAD"),
         "--head-sha", head or inventory["identity"]["head_sha"]],
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


def test_unresolved_historical_blocker_requires_a_current_finding(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    report["previous_findings"][0]["disposition"] = "still-open"
    assert "historical blocker" in run(tmp_path, inv, report).stdout


def test_unchanged_evidence_cannot_fake_historical_resolution(tmp_path: Path) -> None:
    inv, report = fixture(tmp_path)
    report["previous_findings"][0]["disposition"] = "regressed"
    report["findings"][0]["id"] = "OLD-1"
    report["blocking_ids"] = ["OLD-1"]
    assert run(tmp_path, inv, report).returncode == 0


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


def test_self_consistent_forged_snapshot_cannot_hide_real_git_file(tmp_path: Path) -> None:
    inventory, report = fixture(tmp_path)
    inventory["discovery"]["changed_paths"] = ["src/decoy.py"]
    diff_path = tmp_path / "proofs/diff.txt"
    diff_path.write_text(json.dumps({
        "base_sha": inventory["identity"]["base_sha"],
        "head_sha": inventory["identity"]["head_sha"],
        "changed_paths": ["src/decoy.py"],
    }), encoding="utf-8")
    inventory["sources"][1]["evidence_sha256"] = hashlib.sha256(diff_path.read_bytes()).hexdigest()
    report["changed_path_reviews"][0]["id"] = "src/decoy.py"
    result = run(tmp_path, inventory, report)
    assert result.returncode == 2
    assert "independently read Git objects" in result.stdout


def test_missing_trusted_git_objects_fails_closed(tmp_path: Path) -> None:
    inventory, report = fixture(tmp_path)
    for key in ("base_sha", "head_sha"):
        inventory["identity"][key] = "f" * 40
        report["identity"][key] = "f" * 40
    assert "trusted Git changed-path verification failed" in run(tmp_path, inventory, report).stdout


def test_existing_but_forged_git_base_rejected_by_remote_anchor(tmp_path: Path) -> None:
    inventory, report = fixture(tmp_path)
    inventory["identity"]["base_sha"] = inventory["identity"]["head_sha"]
    report["identity"]["base_sha"] = report["identity"]["head_sha"]
    result = run(tmp_path, inventory, report)
    assert result.returncode == 2
    assert "independent GitHub anchor" in result.stdout


def test_test_only_removal_requires_independent_lifecycle_review(tmp_path: Path) -> None:
    """A deleted test cannot be waived or linked only to unrelated code controls."""
    inventory, report = fixture(tmp_path)
    checkout = tmp_path / "gitrepo"
    git(checkout, "reset", "--hard", "HEAD~1")
    removed = checkout / "tests/test_removed_contract.py"
    removed.parent.mkdir(parents=True)
    removed.write_text("def test_legacy_contract():\\n    assert True\\n".replace("\\n", "\n"), encoding="utf-8")
    git(checkout, "add", "-A")
    git(checkout, "commit", "-qm", "existing test baseline")
    removed.unlink()
    git(checkout, "add", "-A")
    git(checkout, "commit", "-qm", "remove test")
    base = git(checkout, "rev-parse", "HEAD~1")
    head = git(checkout, "rev-parse", "HEAD")
    identity = {"repository": "org/test", "base_sha": base, "head_sha": head}
    inventory["identity"] = identity
    report["identity"] = identity
    path = "tests/test_removed_contract.py"
    inventory["discovery"]["changed_paths"] = [path]
    diff_path = tmp_path / "proofs/diff.txt"
    diff_path.write_text(json.dumps({
        "base_sha": base, "head_sha": head, "changed_paths": [path],
    }), encoding="utf-8")
    inventory["sources"][1]["evidence_sha256"] = hashlib.sha256(
        diff_path.read_bytes()).hexdigest()
    review = report["changed_path_reviews"][0]
    review["id"] = path
    review["status"] = "not-applicable"
    review["reason"] = "This file is allegedly not relevant to the implementation"
    review.pop("surface_ids", None)
    first = run(tmp_path, inventory, report)
    assert first.returncode == 2, first.stdout
    assert "changed test/runner path cannot be not-applicable" in first.stdout

    review["status"] = "covered"
    review["surface_ids"] = ["S1"]
    second = run(tmp_path, inventory, report)
    assert second.returncode == 2, second.stdout
    assert "lacks test-lifecycle surface" in second.stdout

    inventory["surfaces"][0]["risk_family"] = "test-lifecycle"
    assert run(tmp_path, inventory, report).returncode == 0

    review["reason"] = ""
    last = run(tmp_path, inventory, report)
    assert last.returncode == 2, last.stdout
    assert "substantive reason required" in last.stdout
