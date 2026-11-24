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


def test_rejects_a_pull_request_base_drift(monkeypatch):
    value = canonical_report()
    monkeypatch.setattr(MODULE, "run_gh", lambda *_args, **_kwargs: {
        "state": "open",
        "head": {"sha": value["identity"]["head_sha"]},
        "base": {"sha": "f" * 40},
        "merge_commit_sha": value["identity"]["merge_preview_sha"],
    })
    try:
        MODULE.verify_live_head(
            value, value["identity"]["head_sha"], value["identity"]["repository"]
        )
    except ValueError as exc:
        assert "HEAD changed" in str(exc)
    else:
        raise AssertionError("a pull request base drift must block publication")


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


def canonical_report() -> dict:
    value = report()
    identity = value["identity"]
    identity.update({
        "base_sha": "2" * 40,
        "merge_preview_sha": "3" * 40,
        "diff_sha256": HASH,
        "skills_sha256": HASH,
        "captured_at": "2026-11-24T22:00:00Z",
    })
    value.update({
        "schema_version": 3,
        "approval_scope": "independent-release-gate",
        "release_gate_satisfied": True,
        "started_at": "2026-11-24T22:00:01Z",
        "finished_at": "2026-11-24T22:00:02Z",
        "requirements_rederived": True,
        "modifications_detected": False,
        "source_manifest_sha256": HASH,
        "requirements_rederivation_sha256": HASH,
        "coverage_matrix_sha256": HASH,
        "neutral_packet_sha256": HASH,
        "neutral_packet": {
            "implementation_conclusions_included": False,
            "implementation_narrative_included": False,
            "allowed_contents": ["canonical-sources", "identity", "raw-evidence"],
        },
        "prior_internal_approval": None,
        "audit_escapes": [],
    })
    for index, requirement in enumerate(value["requirements"], start=1):
        requirement.update({
            "origin": "SRC-ISSUE",
            "statement": f"Criterion {index} is implemented.",
            "evidence": ["implementation:1"],
            "negative_controls": [],
            "negative_control_evidence": [],
            "regression_evidence": ["test"],
        })
    value["gates"] = [{
        "name": "audit-gate",
        "status": "passed",
        "attestation_sha256": HASH,
    }]
    return value


def test_accepts_report_satisfying_the_canonical_audit_schema(tmp_path: Path):
    path = tmp_path / "controller-report.json"
    path.write_text(json.dumps(canonical_report()), encoding="utf-8")
    assert load_report(path)["mode"] == "independent"


def test_required_audit_check_must_be_green_at_the_exact_head(monkeypatch):
    response = {
        "total_count": 1,
        "check_runs": [{
            "id": 7,
            "name": "Verify session review (exact SHA)",
            "head_sha": "1" * 40,
            "status": "completed",
            "conclusion": "failure",
        }],
    }
    monkeypatch.setattr(MODULE, "run_gh", lambda *_args, **_kwargs: response)
    try:
        MODULE.verify_required_audit_checks(
            "owner/repo",
            "1" * 40,
            196,
            HASH,
            {
                "repository": "owner/repo",
                "issue": 196,
                "pull_request": 99,
                "base_sha": "2" * 40,
                "head_sha": "1" * 40,
                "merge_preview_sha": "3" * 40,
                "issue_snapshot_sha256": "d" * 64,
            },
            [(
                "Verify session review (exact SHA)",
                ".github/workflows/session-review.yml",
            )],
        )
    except ValueError as exc:
        assert "not green" in str(exc)
    else:
        raise AssertionError("a failed exact-head audit check must block publication")


def test_required_audit_check_must_bind_the_exact_report(monkeypatch):
    audit_run = {
        "id": 7,
        "name": "Verify session review (exact SHA)",
        "head_sha": "1" * 40,
        "status": "completed",
        "conclusion": "success",
    }
    identity = {
        "repository": "owner/repo",
        "issue": 196,
        "pull_request": 99,
        "base_sha": "2" * 40,
        "head_sha": "1" * 40,
        "merge_preview_sha": "3" * 40,
        "issue_snapshot_sha256": "d" * 64,
    }
    receipt_identity = {
        "repository": "owner/repo",
        "issue": 196,
        "pull_request": 99,
        "base_sha": "2" * 40,
        "head_sha": "1" * 40,
        "merge_preview_sha": "3" * 40,
        "issue_sha256": "d" * 64,
    }

    def fake_api(endpoint, **_kwargs):
        if "/commits/" in endpoint:
            return {"total_count": 1, "check_runs": [audit_run]}
        if "/actions/runs/" in endpoint:
            return {
                "repository": {"full_name": "owner/repo"},
                "path": ".github/workflows/session-review.yml",
                "status": "completed",
                "conclusion": "success",
                "event": "workflow_run",
            }
        return {
            "app": {"id": 15368},
            "details_url": (
                "https://github.com/owner/repo/actions/runs/8"
            ),
            "output": {
                "text": json.dumps({
                    "identity": receipt_identity,
                    "publication_attestation": {
                        "schema": "issue-audit-publication-attestation-v1",
                        "repository": "owner/repo",
                        "issue": 196,
                        "head_sha": "1" * 40,
                        "audit_report_sha256": HASH,
                        "accepted": True,
                    }
                })
            }
        }

    monkeypatch.setattr(MODULE, "run_gh", fake_api)
    selected = MODULE.verify_required_audit_checks(
        "owner/repo",
        "1" * 40,
        196,
        HASH,
        identity,
        [("Verify session review (exact SHA)",
          ".github/workflows/session-review.yml")],
    )
    assert selected[0]["id"] == 7
    try:
        MODULE.verify_required_audit_checks(
            "owner/repo",
            "1" * 40,
            196,
            "b" * 64,
            identity,
            [("Verify session review (exact SHA)",
              ".github/workflows/session-review.yml")],
        )
    except ValueError as exc:
        assert "exact report" in str(exc)
    else:
        raise AssertionError("the attestation must bind the exact report digest")


def test_rejects_duplicate_logical_comments(monkeypatch):
    comments = [
        {"id": 1, "body": f"<!-- audit-acceptance-criteria-fingerprint:{'a' * 64} -->"},
        {"id": 2, "body": f"<!-- audit-acceptance-criteria-fingerprint:{'a' * 64} -->"},
    ]
    monkeypatch.setattr(MODULE, "run_gh", lambda *_args, **_kwargs: {})
    try:
        MODULE.exact_existing_comment(comments, "a" * 64, "expected", "owner/repo")
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("logical duplicate comments must block publication")
