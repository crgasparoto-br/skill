from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEAD = "a" * 40
EVIDENCE_SHA = hashlib.sha256(b"coverage-evidence").hexdigest()


def run(script: str, *args: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        check=False, text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def closure_same_requirement() -> dict:
    return {
        "obligations": [
            {
                "id": "O-DAY",
                "disposition": "covered",
                "requirement_ids": ["COV"],
                "source_text": "Retention: daily aggregates remain available for 24 months.",
            },
            {
                "id": "O-MONTH",
                "disposition": "covered",
                "requirement_ids": ["COV"],
                "source_text": "Retention: monthly aggregates remain available for 5 years.",
            },
            {
                "id": "O-COVERAGE",
                "disposition": "covered",
                "requirement_ids": ["COV"],
                "source_text": "Queries expose coverage, availableFrom and complete or partial availability.",
            },
        ]
    }


def closure_cross_requirement() -> dict:
    return {
        "obligations": [
            {
                "id": "O-DAY",
                "disposition": "covered",
                "requirement_ids": ["RET"],
                "source_text": "Retention: daily aggregates remain available for 24 months.",
            },
            {
                "id": "O-MONTH",
                "disposition": "covered",
                "requirement_ids": ["RET"],
                "source_text": "Retention: monthly aggregates remain available for 5 years.",
            },
            {
                "id": "O-COVERAGE",
                "disposition": "covered",
                "requirement_ids": ["REPORT"],
                "source_text": "Reports expose data coverage, availableFrom and complete or partial availability.",
            },
        ]
    }


def control(control_id: str, tier: str, granularity: str, cutoff: str, boundary: str) -> dict:
    return {
        "id": control_id,
        "status": "passed",
        "head_sha": HEAD,
        "evidence": "coverage.log",
        "evidence_sha256": EVIDENCE_SHA,
        "risk_family": "temporal-consistency",
        "surface": "reporting-availability-window",
        "dimension": f"{tier}-retention-boundary-alignment",
        "failure_mode": "Coverage metadata can use a timestamp boundary while storage and queries use a bucket boundary.",
        "plausible_wrong_implementation": "Compute availableFrom from the raw cutoff even though purge and query normalize to the retained bucket.",
        "control_type": "scenario",
        "procedure": f"Use an off-boundary {tier} cutoff and observe purge, query and coverage boundaries on the frozen candidate.",
        "expected": "All effective boundaries use the same retained bucket and the boundary request is complete.",
        "observed": "Purge, query and reported availability resolved to the same retained bucket boundary.",
        "coverage_tier": tier,
        "boundary_granularity": granularity,
        "boundary_probe": {
            "timezone": "UTC",
            "cutoff_input": cutoff,
            "requested_from": boundary,
            "purge_boundary": boundary,
            "query_boundary": boundary,
            "reported_available_from": boundary,
            "reported_state": "complete",
        },
        "sibling_cases": [
            {
                "id": f"{control_id}-BEFORE",
                "surface": "reporting-availability-window",
                "dimension": f"{tier}-requested-before-boundary",
                "status": "passed",
            },
            {
                "id": f"{control_id}-EXPIRED",
                "surface": "reporting-availability-window",
                "dimension": f"{tier}-fully-expired-window",
                "status": "passed",
            },
        ],
    }


def matrix() -> dict:
    daily = control(
        "TEMP-COVERAGE-DAILY",
        "daily",
        "day",
        "2024-08-18T17:59:00Z",
        "2024-08-18T00:00:00Z",
    )
    monthly = control(
        "TEMP-COVERAGE-MONTHLY",
        "monthly",
        "month",
        "2021-08-18T17:59:00Z",
        "2021-08-01T00:00:00Z",
    )
    coverage_label = control(
        "TEMP-COVERAGE-LABEL",
        "reporting",
        "instant",
        "2024-08-18T17:59:00Z",
        "2024-08-18T17:59:00Z",
    )
    coverage_label.update({
        "dimension": "reported-complete-partial-label",
        "procedure": "Request a window that crosses the retained-data boundary and inspect the report coverage label and availableFrom payload.",
        "expected": "The report marks the window complete or partial consistently with the retained data exposed by the query.",
        "observed": "The report label and availableFrom matched the retained/query boundary for the requested window.",
    })
    return {
        "schema_version": 1,
        "head_sha": HEAD,
        "requirements": [
            {
                "requirement_id": "COV",
                "obligation_ids": ["O-DAY", "O-MONTH", "O-COVERAGE"],
                "risk_families": ["temporal-consistency"],
                "risk_surfaces": [
                    {
                        "risk_family": "temporal-consistency",
                        "surface": "reporting-availability-window",
                        "reason": "Retention-backed reports can disagree with the actual retained/query boundary.",
                    }
                ],
                "source_texts": [o["source_text"] for o in closure_same_requirement()["obligations"]],
                "plausible_wrong_implementation": "A report can label a retained bucket partial by using a raw timestamp cutoff while storage preserves the whole bucket.",
                "positive_control": {
                    "id": "POS",
                    "status": "passed",
                    "head_sha": HEAD,
                    "evidence": "positive.log",
                },
                "negative_controls": [daily, monthly, coverage_label],
                "obligation_control_map": [
                    {"obligation_id": "O-DAY", "primary_negative_control_id": "TEMP-COVERAGE-DAILY"},
                    {"obligation_id": "O-MONTH", "primary_negative_control_id": "TEMP-COVERAGE-MONTHLY"},
                    {"obligation_id": "O-COVERAGE", "primary_negative_control_id": "TEMP-COVERAGE-LABEL"},
                ],
                "regression_controls": [
                    {"id": "REG", "status": "passed", "head_sha": HEAD, "evidence": "regression.log"}
                ],
                "coverage_contract": {
                    "reporting_entrypoint": "usageAnalytics.reportCoverage",
                    "retained_tiers": [
                        {
                            "tier": "daily",
                            "granularity": "day",
                            "applicability": "used",
                            "reason": "The report reads retained daily aggregates for the medium-term window.",
                            "control_id": "TEMP-COVERAGE-DAILY",
                        },
                        {
                            "tier": "monthly",
                            "granularity": "month",
                            "applicability": "used",
                            "reason": "The report reads retained monthly aggregates for the long-term window.",
                            "control_id": "TEMP-COVERAGE-MONTHLY",
                        },
                    ],
                },
            }
        ],
        "uncovered_requirements": [],
    }


def write_inputs(base: Path, matrix_payload: dict):
    closure_path = base / "closure.json"
    matrix_path = base / "matrix.json"
    closure_path.write_text(json.dumps(closure_same_requirement()), encoding="utf-8")
    matrix_path.write_text(json.dumps(matrix_payload), encoding="utf-8")
    return closure_path, matrix_path


def test_initializer_propagates_retention_tiers_across_requirements():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        closure_path = base / "closure.json"
        out = base / "matrix.json"
        closure_path.write_text(json.dumps(closure_cross_requirement()), encoding="utf-8")
        proc = run(
            "init_requirement_attack_matrix.py",
            "--requirement-closure",
            str(closure_path),
            "--head-sha",
            HEAD,
            "--out",
            str(out),
        )
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(out.read_text())
        report = next(item for item in payload["requirements"] if item["requirement_id"] == "REPORT")
        tiers = {(item["tier"], item["granularity"]) for item in report["coverage_contract"]["retained_tiers"]}
        assert tiers == {("daily", "day"), ("monthly", "month")}


def test_validator_accepts_dedicated_boundary_probe_per_retained_tier():
    with tempfile.TemporaryDirectory() as tmp:
        closure_path, matrix_path = write_inputs(Path(tmp), matrix())
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure",
            str(closure_path),
            "--attack-matrix",
            str(matrix_path),
        )
        assert proc.returncode == 0, proc.stdout


def test_validator_rejects_one_control_reused_across_retention_tiers():
    payload = matrix()
    tiers = payload["requirements"][0]["coverage_contract"]["retained_tiers"]
    tiers[1]["control_id"] = tiers[0]["control_id"]
    with tempfile.TemporaryDirectory() as tmp:
        closure_path, matrix_path = write_inputs(Path(tmp), payload)
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure",
            str(closure_path),
            "--attack-matrix",
            str(matrix_path),
        )
        assert proc.returncode == 2
        assert "each tier requires a dedicated control" in proc.stdout


def test_validator_rejects_mid_bucket_available_from_for_daily_retention():
    payload = matrix()
    daily = payload["requirements"][0]["negative_controls"][0]
    daily["boundary_probe"]["reported_available_from"] = "2024-08-18T17:59:00Z"
    daily["boundary_probe"]["reported_state"] = "partial"
    with tempfile.TemporaryDirectory() as tmp:
        closure_path, matrix_path = write_inputs(Path(tmp), payload)
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure",
            str(closure_path),
            "--attack-matrix",
            str(matrix_path),
        )
        assert proc.returncode == 2
        assert "reported_available_from differs from effective retained/query boundary" in proc.stdout
        assert "reported_state must be complete" in proc.stdout


def test_validator_rejects_already_aligned_bucket_probe_as_non_discriminant():
    payload = matrix()
    daily = payload["requirements"][0]["negative_controls"][0]
    daily["boundary_probe"]["cutoff_input"] = "2024-08-18T00:00:00Z"
    with tempfile.TemporaryDirectory() as tmp:
        closure_path, matrix_path = write_inputs(Path(tmp), payload)
        proc = run(
            "validate_requirement_attack_matrix.py",
            "--requirement-closure",
            str(closure_path),
            "--attack-matrix",
            str(matrix_path),
        )
        assert proc.returncode == 2
        assert "must use an off-boundary cutoff_input" in proc.stdout
