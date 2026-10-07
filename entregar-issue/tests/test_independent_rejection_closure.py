from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_independent_rejection_closure.py"


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(learning: Path, closure: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--learning-closure", str(learning), "--closure", str(closure)],
        check=False, text=True,
        stdout=subprocess.PIPE,
    )


def learning(*, rejection_id: str = "audit-rejection:synthetic-001", classification: str = "implementation-only") -> dict:
    return {
        "schema_version": 1,
        "classification": classification,
        "source_event": {
            "kind": "independent-audit-rejection",
            "rejection_id": rejection_id,
            "finding_ids": ["F-001", "F-002"],
        },
        "generalized_learning": {
            "promotion_status": "not-required",
            "reason": "An existing generic terminal guard already represents the reusable rule.",
        },
    }


def escape(rejection_id: str, finding_id: str) -> dict:
    return {
        "escape_id": f"ESC-{finding_id}",
        "escape_class": "published-candidate-identity-drift",
        "source_audit": {"rejection_id": rejection_id, "finding_id": finding_id},
        "plausible_wrong_implementation": "Publish additional material changes after freeze without restoring the terminal handoff invariant.",
        "literal_case": {"status": "passed", "evidence": "literal.log"},
        "sibling_cases": [
            {"id": "post-ci-write", "status": "passed", "evidence": "post-ci.log"},
            {"id": "result-child-parent-drift", "status": "passed", "evidence": "parent.log"},
        ],
        "prevention_change": {"evidence": "terminal guard"},
        "detection_change": {"evidence": "rejection lineage gate"},
        "status": "passed",
    }


def test_rejects_new_independent_rejection_missing_from_escape_ledger() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        learning_path = base / "learning.json"
        closure_path = base / "closure.json"
        write(learning_path, learning())
        write(closure_path, {"schema_version": 1, "escapes": [escape("audit-rejection:older-001", "F-OLD")]})
        proc = run(learning_path, closure_path)
        assert proc.returncode == 2
        assert "has no audit escape closure" in proc.stdout


def test_accepts_when_all_findings_of_latest_rejection_are_explicitly_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        learning_path = base / "learning.json"
        closure_path = base / "closure.json"
        rid = "audit-rejection:synthetic-001"
        write(learning_path, learning(rejection_id=rid))
        write(closure_path, {"schema_version": 1, "escapes": [escape(rid, "F-001"), escape(rid, "F-002")]})
        proc = run(learning_path, closure_path)
        assert proc.returncode == 0, proc.stdout


def test_rejects_partial_finding_coverage() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        learning_path = base / "learning.json"
        closure_path = base / "closure.json"
        rid = "audit-rejection:synthetic-001"
        write(learning_path, learning(rejection_id=rid))
        write(closure_path, {"schema_version": 1, "escapes": [escape(rid, "F-001")]})
        proc = run(learning_path, closure_path)
        assert proc.returncode == 2
        assert "F-002" in proc.stdout


def test_implementation_only_rejection_still_requires_escape_closure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        learning_path = base / "learning.json"
        closure_path = base / "closure.json"
        write(learning_path, learning(classification="implementation-only"))
        write(closure_path, {"schema_version": 1, "escapes": []})
        proc = run(learning_path, closure_path)
        assert proc.returncode == 2
        assert "has no audit escape closure" in proc.stdout
