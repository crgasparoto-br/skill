from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

from evals.run_evals import HarnessError, evaluate_result, run_evaluations, sha256_json, verify_report
from scripts.catalog import load_catalog
from scripts.select_skill import rank_skills
from scripts.validate_evals import selection_case_errors, validate_v030_002_matrix

ROOT = Path(__file__).resolve().parents[1]
RESOLVED_SELECTION_CASES = (
    "V030-002-selection-003",
    "V030-002-selection-004",
    "V030-002-selection-005",
    "V030-002-selection-006",
)
ABSTAIN_SELECTION_CASES = ("V030-002-selection-007", "V030-002-selection-008")


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
    assert any(
        record["expected_outcome"] == "PASS" and record["case_id"].startswith("V030-002-selection")
        for record in records
    ), "a matriz precisa provar seleção resolvida, não apenas abstenção"


def rank_for(case: dict) -> dict:
    return rank_skills(
        case["task"]["user_prompt"],
        load_catalog(ROOT),
        set(case["context"]["available_capabilities"]),
    )


def test_resolved_selection_cases_match_the_real_router() -> None:
    for case_id in RESOLVED_SELECTION_CASES:
        case = load_case(case_id)
        ranked = rank_for(case)
        expected = case["expected"]
        assert expected["selection"]["disambiguation_required"] is False, case_id
        assert ranked["decision"] == expected["selected_skill"], case_id
        observed = [candidate["skill"] for candidate in ranked["candidates"] if candidate["matched_positive"]]
        assert observed == expected["selection"]["candidate_skills"], case_id


def test_abstain_selection_cases_stay_unknown_in_the_real_router() -> None:
    for case_id in ABSTAIN_SELECTION_CASES:
        case = load_case(case_id)
        assert "selection" not in case["expected"], case_id
        assert rank_for(case)["decision"] == "UNKNOWN", case_id


def test_selection_case_shapes_are_enforced() -> None:
    resolved = load_case("V030-002-selection-003")
    tie = load_case("V030-002-selection-001")
    assert selection_case_errors(resolved) == []
    assert selection_case_errors(tie) == []

    def mutate(case_id: str, mutate_case) -> list[str]:
        case = copy.deepcopy(load_case(case_id))
        mutate_case(case)
        return selection_case_errors(case)

    def drop_shortlist(case: dict) -> None:
        case["expected"]["selection"]["candidate_skills"] = []

    def widen_shortlist(case: dict) -> None:
        case["expected"]["selection"]["candidate_skills"] = ["entregar-issue", "revisar-issue"]

    def drop_winner(case: dict) -> None:
        case["expected"]["selected_skill"] = None

    def shorten_tie(case: dict) -> None:
        case["expected"]["selection"]["candidate_skills"] = ["entregar-issue"]

    def drop_reason_markers(case: dict) -> None:
        case["expected"]["selection"]["reason_markers"] = []

    def drop_selection_block(case: dict) -> None:
        case["expected"].pop("selection")

    assert any("exactly the resolved skill" in error for error in mutate("V030-002-selection-003", drop_shortlist))
    assert any("exactly the resolved skill" in error for error in mutate("V030-002-selection-003", widen_shortlist))
    assert any("must expect PASS with a selected skill" in error for error in mutate("V030-002-selection-003", drop_winner))
    assert any("structured material shortlist" in error for error in mutate("V030-002-selection-001", shorten_tie))
    assert any("structured reason markers" in error for error in mutate("V030-002-selection-003", drop_reason_markers))
    assert any("must declare a structured selection" in error for error in mutate("V030-002-selection-003", drop_selection_block))


def test_persisted_replay_report_round_trips_and_rejects_tampering(tmp_path: Path) -> None:
    report = run_evaluations(ROOT, results_dir=ROOT / "evals" / "fixtures" / "results")
    assert report["summary"]["failed"] == 0
    assert report["summary"]["invalid"] == 0
    assert report["summary"]["not_run"] == 0
    assert report["summary"]["passed"] == report["summary"]["total"]

    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert verify_report(ROOT, report_path) == []

    tampered = copy.deepcopy(report)
    tampered["cases"][0]["status"] = "FAIL"
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert any("content_sha256" in error for error in verify_report(ROOT, tampered_path))


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
