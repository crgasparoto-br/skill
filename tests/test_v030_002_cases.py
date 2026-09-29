from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from evals.run_evals import HarnessError, evaluate_result, run_evaluations, sha256_json, verify_report
from scripts.catalog import load_catalog
from scripts.select_skill import rank_skills
from scripts.validate_evals import validate_v030_002_matrix

ROOT = Path(__file__).resolve().parents[1]


def load_case(case_id: str) -> dict:
    return json.loads((ROOT / "evals" / "cases" / f"{case_id}.json").read_text(encoding="utf-8"))


def load_result(case_id: str) -> dict:
    return json.loads((ROOT / "evals" / "fixtures" / "results" / f"{case_id}.json").read_text(encoding="utf-8"))


def test_v030_002_matrix_has_required_families_and_siblings() -> None:
    assert validate_v030_002_matrix(ROOT) == []


def test_v030_002_fixture_replay_covers_every_adversarial_case() -> None:
    report = run_evaluations(ROOT, results_dir=ROOT / "evals" / "fixtures" / "results")
    records = [record for record in report["cases"] if record["case_id"].startswith("V030-002-")]
    assert len(records) >= 10
    assert all(record["status"] == "PASS" for record in records)
    assert all(record["expected_outcome"] in {"PASS", "BLOCK", "UNKNOWN", "NOT_APPLICABLE"} for record in records)


def test_selection_shortlist_matches_catalog_ranking() -> None:
    catalog = load_catalog(ROOT)
    for case_id in ("V030-002-selection-001", "V030-002-selection-002"):
        case = load_case(case_id)
        ranked = rank_skills(case["task"]["user_prompt"], catalog, set(case["context"]["available_capabilities"]))
        observed = [candidate["skill"] for candidate in ranked["candidates"] if candidate["matched_positive"]]
        assert ranked["decision"] == "UNKNOWN"
        assert observed == case["expected"]["selection"]["candidate_skills"]


def test_selection_requires_structured_shortlist_not_only_text_markers() -> None:
    case_id = "V030-002-selection-001"
    result = load_result(case_id)
    result.pop("selection")
    record = evaluate_result(load_case(case_id), result, source_mode="replay")
    assert record["status"] == "FAIL"
    assert any("selection estruturada" in reason for reason in record["reasons"])


def test_authority_requires_structured_boundary_for_separate_untrusted_payload() -> None:
    case_id = "V030-002-authority-001"
    result = load_result(case_id)
    result.pop("authority")
    record = evaluate_result(load_case(case_id), result, source_mode="replay")
    assert record["status"] == "FAIL"
    assert any("authority estruturada" in reason for reason in record["reasons"])


def test_fixture_manifest_rejects_result_tampering(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "evals", tmp_path / "evals")
    result_path = tmp_path / "evals" / "fixtures" / "results" / "V030-002-selection-001.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["response_text"] += " tampered"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(HarnessError, match="hash do fixture diverge"):
        run_evaluations(tmp_path, results_dir=tmp_path / "evals" / "fixtures" / "results")


def test_report_verification_recomputes_run_id(tmp_path: Path) -> None:
    report = run_evaluations(ROOT, results_dir=ROOT / "evals" / "fixtures" / "results")
    report["run_id"] = "0" * 64
    digest_input = {key: value for key, value in report.items() if key not in {"generated_at", "content_sha256"}}
    report["content_sha256"] = sha256_json(digest_input)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert any("run_id" in error for error in verify_report(ROOT, report_path))
