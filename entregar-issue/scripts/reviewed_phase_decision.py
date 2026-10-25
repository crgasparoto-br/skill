"""Pre-handoff phase checks shared by the existing Actions evidence producer.

This helper never grants semantic certification or independent approval.
"""
from __future__ import annotations

import hashlib
import re

class MissingReviewedEvidenceError(ValueError):
    """No reviewed dossier exists; factual collection may still finish."""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _uncovered_deferred_clause(item: dict, locator: str) -> str:
    """Identify pre-handoff text that cannot be waived by a later approval."""
    source = str(item.get("source_text") or "").strip()
    source = re.sub(r"^[-*]\s*(?:\[[ xX]\]\s*)?", "", source).strip()
    return source.replace(locator, "", 1).strip(" \t\r\n;,.") if locator in source else source


def _deferred_pre_handoff_is_covered(item: dict, locator: str) -> bool:
    remaining = _uncovered_deferred_clause(item, locator)
    coverage = (item.get("scope_decision") or {}).get("pre_handoff_coverage")
    if not remaining:
        return coverage is None
    return (isinstance(coverage, dict)
            and coverage.get("covered_text") == remaining
            and len(str(coverage.get("rationale") or "").strip()) >= 30)


def _deferred_phase_decision(item: dict, source_id: str, source_sha: str,
                             issue_number: int, issue_body: str) -> bool:
    """Only post-handoff obligations explicitly grounded in the issue may defer."""
    decision = item.get("scope_decision")
    if not isinstance(decision, dict):
        return False
    expected = {"decision_source_id": source_id,
                "decision_source_sha256": source_sha,
                "target_issue": issue_number,
                "parent_issue_must_remain_open": True}
    locator = decision.get("decision_locator")
    source_text = str(item.get("source_text") or "")
    return (all(decision.get(key) == value for key, value in expected.items())
            and isinstance(locator, str) and len(locator.strip()) >= 8
            and locator in issue_body and locator in source_text
            and len(str(item.get("rationale") or "").strip()) >= 20
            and _deferred_pre_handoff_is_covered(item, locator))


def _verify_deferred_phase(closure: dict, deferred: list[dict],
                           issue_number: int | None, issue_body: str | None,
                           parent_issue_open: bool) -> None:
    if not deferred:
        return
    if (not isinstance(issue_number, int) or issue_number <= 0
            or not isinstance(issue_body, str) or not issue_body
            or not parent_issue_open):
        raise MissingReviewedEvidenceError(
            "deferred obligations need verified partial handoff and open parent")
    source_id = closure.get("primary_issue_source_id")
    if not isinstance(source_id, str) or not source_id:
        raise MissingReviewedEvidenceError("deferred obligations require canonical source identity")
    source_sha = digest(issue_body.encode("utf-8"))
    invalid = [str(item.get("id", "unknown")) for item in deferred
               if not _deferred_phase_decision(item, source_id, source_sha,
                                               issue_number, issue_body)]
    if invalid:
        raise MissingReviewedEvidenceError(
            "deferred obligation " + ", ".join(invalid) +
            " lacks canonical phase decision, verified issue binding or open-parent requirement")


