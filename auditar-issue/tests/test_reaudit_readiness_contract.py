from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_SHA = hashlib.sha256(b"evidence").hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def control(control_id: str, head: str) -> dict:
    return {
        "id": control_id,
        "status": "passed",
        "head_sha": head,
        "subject_sha": head,
        "control_type": "scenario",
        "procedure": "Execute the discriminant scenario against the frozen candidate boundary.",
        "expected": "The plausible wrong implementation must be rejected by the control.",
        "observed": "The divergent scenario was rejected with the expected preserved state.",
        "evidence": f"artifacts/{control_id}.log",
        "evidence_sha256": EVIDENCE_SHA,
    }




def retired_control(control_id: str, head: str) -> dict:
    return {
        "id": control_id,
        "disposition": "not-applicable",
        "reason": "The historical control remains explicitly retired because its original risk surface is absent from the current target.",
        "subject_sha": head,
        "procedure": "Re-evaluate the historical control against the current target contract before preserving retirement.",
        "expected": "The historical control remains explicitly retired without disappearing from cumulative lineage.",
        "observed": "The current target still lacks the historical risk surface, so retirement remains valid.",
        "evidence": f"artifacts/{control_id}-retired.log",
        "evidence_sha256": EVIDENCE_SHA,
    }

def closure(escape_ids: list[str]) -> dict:
    return {
        "schema_version": 1,
        "escapes": [
            {
                "escape_id": escape_id,
                "escape_class": "canonical-path-divergence",
                "source_audit": {"rejection_id": f"audit-rejection:{escape_id}", "finding_id": escape_id},
                "plausible_wrong_implementation": "A specialized path intercepts before the canonical parser and drops semantics.",
                "status": "passed",
                "sibling_cases": [
                    {"id": "verb-preposition", "status": "passed"},
                    {"id": "alias-order", "status": "passed"},
                ],
                "prevention_change": {"evidence": "delivery structural gate"},
                "detection_change": {"evidence": "CANON-DIVERGENCE-001"},
            }
            for escape_id in escape_ids
        ],
    }


def learning(rejection_id: str, finding_id: str) -> dict:
    return {
        "schema_version": 1,
        "classification": "implementation-only",
        "source_event": {
            "kind": "independent-audit-rejection",
            "rejection_id": rejection_id,
            "finding_ids": [finding_id],
        },
        "generalized_learning": {
            "promotion_status": "not-required",
            "reason": "The reusable guard already exists; this round still requires explicit local closure.",
        },
    }


def run(current_closure: Path, learning_path: Path, inherited: Path, head: str, previous_closure: Path, previous_inherited: Path):
    return subprocess.run([
        sys.executable, str(ROOT / "scripts" / "check_reaudit_readiness.py"),
        "--closure", str(current_closure),
        "--learning-closure", str(learning_path),
        "--inherited-controls", str(inherited),
        "--head-sha", head,
        "--previous-closure", str(previous_closure),
        "--previous-inherited-controls", str(previous_inherited),
    ], check=False, text=True, stdout=subprocess.PIPE)


def test_reaudit_stops_before_full_audit_when_escape_is_incomplete() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        head = "c" * 40
        current_closure = base / "audit-escape-closure.json"
        previous_closure = base / "previous-audit-escape-closure.json"
        inherited = base / "inherited-controls.json"
        previous_inherited = base / "previous-inherited-controls.json"
        learning_path = base / "learning-closure.json"
        write_json(previous_closure, closure(["A-001"]))
        broken = closure(["A-001"])
        broken["escapes"][0]["sibling_cases"] = [{"id": "only-one", "status": "passed"}]
        write_json(current_closure, broken)
        write_json(previous_inherited, {"schema_version": 1, "head_sha": "b" * 40, "source_audits": ["audit-a"], "controls": [control("CANON-DIVERGENCE-001", "b" * 40)], "unresolved_controls": []})
        write_json(inherited, {"schema_version": 1, "head_sha": head, "source_audits": ["audit-a", "audit-b"], "controls": [control("CANON-DIVERGENCE-001", head)], "unresolved_controls": []})
        write_json(learning_path, learning("audit-rejection:A-001", "A-001"))
        proc = run(current_closure, learning_path, inherited, head, previous_closure, previous_inherited)
        assert proc.returncode == 2
        assert "sibling cases are incomplete" in proc.stdout


def test_reaudit_accepts_closed_cumulative_escape_class() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        head = "d" * 40
        current_closure = base / "audit-escape-closure.json"
        previous_closure = base / "previous-audit-escape-closure.json"
        inherited = base / "inherited-controls.json"
        previous_inherited = base / "previous-inherited-controls.json"
        learning_path = base / "learning-closure.json"
        write_json(previous_closure, closure(["A-001"]))
        current = closure(["A-001", "A-002"])
        for item in current["escapes"]:
            item["revalidated_head_sha"] = head
        write_json(current_closure, current)
        write_json(previous_inherited, {"schema_version": 1, "head_sha": "c" * 40, "source_audits": ["audit-a"], "controls": [control("CANON-DIVERGENCE-001", "c" * 40)], "unresolved_controls": []})
        write_json(inherited, {"schema_version": 1, "head_sha": head, "source_audits": ["audit-a", "audit-b"], "controls": [control("CANON-DIVERGENCE-001", head)], "unresolved_controls": []})
        write_json(learning_path, learning("audit-rejection:A-002", "A-002"))
        proc = run(current_closure, learning_path, inherited, head, previous_closure, previous_inherited)
        assert proc.returncode == 0, proc.stdout


def test_reaudit_rejects_silent_inherited_control_removal() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        head = "e" * 40
        current_closure = base / "audit-escape-closure.json"
        previous_closure = base / "previous-audit-escape-closure.json"
        inherited = base / "inherited-controls.json"
        previous_inherited = base / "previous-inherited-controls.json"
        learning_path = base / "learning-closure.json"
        write_json(previous_closure, closure(["A-001"]))
        write_json(current_closure, closure(["A-001", "A-002"]))
        write_json(previous_inherited, {"schema_version": 1, "head_sha": "d" * 40, "source_audits": ["audit-a"], "controls": [control("OLD-CONTROL-001", "d" * 40), control("KEEP-CONTROL-001", "d" * 40)], "unresolved_controls": []})
        write_json(inherited, {"schema_version": 1, "head_sha": head, "source_audits": ["audit-a", "audit-b"], "controls": [control("KEEP-CONTROL-001", head)], "unresolved_controls": []})
        write_json(learning_path, learning("audit-rejection:A-002", "A-002"))
        proc = run(current_closure, learning_path, inherited, head, previous_closure, previous_inherited)
        assert proc.returncode == 2
        assert "OLD-CONTROL-001 disappeared" in proc.stdout


def test_reaudit_accepts_explicit_supersession_with_exact_head_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        head = "f" * 40
        current_closure = base / "audit-escape-closure.json"
        previous_closure = base / "previous-audit-escape-closure.json"
        inherited = base / "inherited-controls.json"
        previous_inherited = base / "previous-inherited-controls.json"
        learning_path = base / "learning-closure.json"
        write_json(previous_closure, closure(["A-001"]))
        current = closure(["A-001", "A-002"])
        for item in current["escapes"]:
            item["revalidated_head_sha"] = head
        write_json(current_closure, current)
        write_json(previous_inherited, {"schema_version": 1, "head_sha": "e" * 40, "source_audits": ["audit-a"], "controls": [control("OLD-CONTROL-001", "e" * 40)], "unresolved_controls": []})
        write_json(inherited, {
            "schema_version": 1,
            "head_sha": head,
            "source_audits": ["audit-a", "audit-b"],
            "controls": [control("NEW-CONTROL-001", head)],
            "retired_controls": [{
                "id": "OLD-CONTROL-001",
                "disposition": "superseded",
                "replacement_control_id": "NEW-CONTROL-001",
                "reason": "The replacement strictly covers the historical failure mode and a broader sibling surface.",
                "subject_sha": head,
                "procedure": "Compare the historical control contract with the replacement discriminant coverage.",
                "expected": "Every historical failure mode remains discriminated by the replacement control.",
                "observed": "The replacement covers the historical failure mode on the exact candidate head.",
                "evidence": "artifacts/supersession.log",
                "evidence_sha256": EVIDENCE_SHA,
            }],
            "unresolved_controls": [],
        })
        write_json(learning_path, learning("audit-rejection:A-002", "A-002"))
        proc = run(current_closure, learning_path, inherited, head, previous_closure, previous_inherited)
        assert proc.returncode == 0, proc.stdout


def test_reaudit_rejects_previous_escape_id_disappearance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        head = "a" * 40
        current_closure = base / "audit-escape-closure.json"
        previous_closure = base / "previous-audit-escape-closure.json"
        inherited = base / "inherited-controls.json"
        previous_inherited = base / "previous-inherited-controls.json"
        learning_path = base / "learning-closure.json"
        write_json(previous_closure, closure(["A-001", "A-OLD"]))
        write_json(current_closure, closure(["A-001", "A-NEW"]))
        write_json(previous_inherited, {"schema_version": 1, "head_sha": "9" * 40, "source_audits": ["audit-a"], "controls": [control("KEEP-CONTROL-001", "9" * 40)], "unresolved_controls": []})
        write_json(inherited, {"schema_version": 1, "head_sha": head, "source_audits": ["audit-a", "audit-b"], "controls": [control("KEEP-CONTROL-001", head)], "unresolved_controls": []})
        write_json(learning_path, learning("audit-rejection:A-NEW", "A-NEW"))
        proc = run(current_closure, learning_path, inherited, head, previous_closure, previous_inherited)
        assert proc.returncode == 2
        assert "previous escape ids disappeared: A-OLD" in proc.stdout


def test_reaudit_rejects_latest_independent_rejection_missing_from_current_ledger() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        head = "b" * 40
        current_closure = base / "audit-escape-closure.json"
        previous_closure = base / "previous-audit-escape-closure.json"
        inherited = base / "inherited-controls.json"
        previous_inherited = base / "previous-inherited-controls.json"
        learning_path = base / "learning-closure.json"
        write_json(previous_closure, closure(["A-001"]))
        write_json(current_closure, closure(["A-001", "A-002"]))
        write_json(learning_path, learning("audit-rejection:A-003", "A-003"))
        write_json(previous_inherited, {"schema_version": 1, "head_sha": "a" * 40, "source_audits": ["audit-a"], "controls": [control("KEEP-CONTROL-001", "a" * 40)], "unresolved_controls": []})
        write_json(inherited, {"schema_version": 1, "head_sha": head, "source_audits": ["audit-a", "audit-b"], "controls": [control("KEEP-CONTROL-001", head)], "unresolved_controls": []})
        proc = run(current_closure, learning_path, inherited, head, previous_closure, previous_inherited)
        assert proc.returncode == 2
        assert "audit-rejection:A-003 has no audit escape closure" in proc.stdout


def test_reaudit_accepts_control_already_retired_in_previous_snapshot() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        previous_head = "1" * 40
        head = "2" * 40
        current_closure = base / "audit-escape-closure.json"
        previous_closure = base / "previous-audit-escape-closure.json"
        inherited = base / "inherited-controls.json"
        previous_inherited = base / "previous-inherited-controls.json"
        learning_path = base / "learning-closure.json"
        write_json(previous_closure, closure(["A-001"]))
        current = closure(["A-001", "A-002"])
        for item in current["escapes"]:
            item["revalidated_head_sha"] = head
        write_json(current_closure, current)
        write_json(previous_inherited, {
            "schema_version": 1,
            "head_sha": previous_head,
            "source_audits": ["audit-a"],
            "controls": [control("KEEP-CONTROL-001", previous_head)],
            "retired_controls": [retired_control("OLD-RETIRED-001", previous_head)],
            "unresolved_controls": [],
        })
        write_json(inherited, {
            "schema_version": 1,
            "head_sha": head,
            "source_audits": ["audit-a", "audit-b"],
            "controls": [control("KEEP-CONTROL-001", head)],
            "retired_controls": [retired_control("OLD-RETIRED-001", head)],
            "unresolved_controls": [],
        })
        write_json(learning_path, learning("audit-rejection:A-002", "A-002"))
        proc = run(current_closure, learning_path, inherited, head, previous_closure, previous_inherited)
        assert proc.returncode == 0, proc.stdout
