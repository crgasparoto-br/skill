from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "reconcile_issue_acceptance_criteria.py"
)
SPEC = importlib.util.spec_from_file_location("issue_reconciliation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
FINGERPRINT_RE = MODULE.FINGERPRINT_RE
PAYLOAD_PREFIX = MODULE.PAYLOAD_PREFIX
load_report = MODULE.load_report
reconcile_payload = MODULE.reconcile_payload
render_comment = MODULE.render_comment
validate_report_against_sources = MODULE.validate_report_against_sources

HASH = "a" * 64
ROOT = Path(__file__).resolve().parents[1]
BODY = (
    "# Issue\n\n"
    "## Objetivo\n"
    "- Implementar o fluxo.\n\n"
    "## Critérios de aceite\n"
    "- [ ] O fluxo publica a decisão.\n"
    "- [x] O fluxo preserva o corpo.\n"
)


def report() -> dict:
    return {
        "schema_version": 3,
        "mode": "independent",
        "verdict": "Aprovado",
        "read_only": True,
        "identity": {
            "repository": "owner/repo",
            "issue": 196,
            "pull_request": 99,
            "branch": "fix/196",
            "head_sha": "1" * 40,
            "issue_snapshot_sha256": hashlib.sha256(BODY.encode()).hexdigest(),
        },
        "requirements": [
            {"id": "REQ-1", "status": "Implementado"},
            {"id": "REQ-2", "status": "Implementado"},
        ],
        "acceptance_criteria": [
            criterion(
                "AC-1", "REQ-1", 7, "O fluxo publica a decisão.", "unchecked"
            ),
            criterion(
                "AC-2", "REQ-2", 8, "O fluxo preserva o corpo.", "checked"
            ),
        ],
        "findings": [],
        "gates": [],
        "limitations": [],
    }


def criterion(identifier: str, requirement: str, line: int, text: str,
              initial: str) -> dict:
    return {
        "id": identifier,
        "requirement_id": requirement,
        "origin": "issue-body",
        "source_id": "SRC-ISSUE",
        "source_locator": "issue-body",
        "source_sha256": hashlib.sha256(BODY.encode()).hexdigest(),
        "source_line": line,
        "text": text,
        "initial_checkbox_state": initial,
        "decision": "verified",
        "evidence": [f"{ROOT}/evidence:{line}"],
        "rationale": "A execução exata comprova o critério no SHA auditado.",
        "proposed_checkbox_state": "checked",
    }


def issue() -> dict:
    return {"state": "open", "body": BODY}


def validate(value: dict) -> None:
    validate_report_against_sources(
        value,
        repository="owner/repo",
        issue_number=196,
        head_sha="1" * 40,
        issue=issue(),
        comments=[],
    )


def test_accepts_exact_issue_criteria_inventory():
    validate(report())


def test_rejects_changed_issue_body_after_audit():
    changed = report()
    changed_issue = issue()
    changed_issue["body"] += "\n- [ ] Novo critério concorrente.\n"
    try:
        validate_report_against_sources(
            changed,
            repository="owner/repo",
            issue_number=196,
            head_sha="1" * 40,
            issue=changed_issue,
            comments=[],
        )
    except ValueError as exc:
        assert "changed" in str(exc)
    else:
        raise AssertionError("body drift must block reconciliation")


def test_rejects_checked_proposal_without_proof():
    changed = report()
    changed["acceptance_criteria"][0]["decision"] = "inconclusive"
    changed["acceptance_criteria"][0]["evidence"] = []
    try:
        validate(changed)
    except ValueError as exc:
        assert "must remain open" in str(exc)
    else:
        raise AssertionError("an inconclusive criterion cannot be checked")


def test_reopens_a_marked_criterion_without_proof():
    changed = report()
    changed["acceptance_criteria"][1]["decision"] = "partial"
    changed["acceptance_criteria"][1]["proposed_checkbox_state"] = "unchecked"
    validate(changed)
    changed["acceptance_criteria"][1]["proposed_checkbox_state"] = "unchanged"
    try:
        validate(changed)
    except ValueError as exc:
        assert "must remain open" in str(exc)
    else:
        raise AssertionError("an unproven marked criterion must be reopened")


def test_accepts_a_criterion_without_an_explicit_checkbox():
    body = (
        "# Issue\n\n"
        "## Critérios de aceite\n"
        "- O comportamento deve permanecer observável.\n"
    )
    changed = report()
    changed["identity"]["issue_snapshot_sha256"] = hashlib.sha256(
        body.encode()
    ).hexdigest()
    changed["acceptance_criteria"] = [criterion(
        "AC-1",
        "REQ-1",
        4,
        "O comportamento deve permanecer observável.",
        "not-present",
    )]
    item = changed["acceptance_criteria"][0]
    item["source_sha256"] = changed["identity"]["issue_snapshot_sha256"]
    item["decision"] = "inconclusive"
    item["evidence"] = []
    item["proposed_checkbox_state"] = "unchanged"
    validate_report_against_sources(
        changed,
        repository="owner/repo",
        issue_number=196,
        head_sha="1" * 40,
        issue={"state": "open", "body": body},
        comments=[],
    )


def test_rejects_partial_inventory():
    changed = report()
    changed["acceptance_criteria"].pop()
    try:
        validate(changed)
    except ValueError as exc:
        assert "inventory differs" in str(exc)
    else:
        raise AssertionError("the inventory must contain every criterion")


def test_comment_fingerprint_is_logically_idempotent():
    first = report()
    second = deepcopy(first)
    first_payload = reconcile_payload(first, HASH, "https://example.invalid/audit/1")
    second_payload = reconcile_payload(second, HASH, "https://example.invalid/audit/1")
    assert first_payload["fingerprint"] == second_payload["fingerprint"]
    first_comment = render_comment(first_payload)
    assert FINGERPRINT_RE.search(first_comment).group(1) == first_payload["fingerprint"]
    assert PAYLOAD_PREFIX in first_comment
    assert "not-attempted-no-proven-cas" in first_comment


def test_reconciliation_schema_rejects_non_independent_report(tmp_path: Path):
    changed = report()
    changed["mode"] = "controller-adversarial"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    try:
        load_report(path)
    except Exception:
        return
    raise AssertionError("only an independent report may be published")
