from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "reconcile_issue_acceptance_criteria.py"
)
sys.path.insert(0, str(SCRIPT.parent))
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


def remote(report_value):
    provenance = MODULE.provenance
    repo = "owner/repo"
    root = f"/repos/{repo}"
    actor = {"id": 41, "login": "owner", "type": "User"}
    original = report_value["identity"]
    source = "6" * 40
    policy = MODULE.canonical({"schema_version": 1, "mode": "enabled",
        "assurance": provenance.ASSURANCE, "acknowledgement": provenance.ACKNOWLEDGEMENT,
        "operators": [{"id": 41, "login": "owner"}]})
    identity = {key: original[key] for key in ("repository", "pull_request", "issue",
        "base_sha", "head_sha", "merge_preview_sha")}
    identity.update(base_ref="develop", issue_sha256=original["issue_snapshot_sha256"],
                    policy_sha256=MODULE.digest(policy))
    report_sha = MODULE.digest(MODULE.canonical(report_value))
    review_payload = {"schema_version": 1, "identity": identity, "conclusion": "approved",
        "assurance": provenance.ASSURANCE, "acknowledgement": provenance.ACKNOWLEDGEMENT,
        "requirements": [{"candidate_key": "one-existing-row",
                          "analysis": "Detailed operator rationale for this requirement.\nAUDIT_REPORT_SHA256=" + report_sha}]}
    review = {"id": 9, "user": actor, "created_at": "2026-11-24T22:10:00Z",
              "updated_at": "2026-11-24T22:10:00Z",
              "issue_url": f"{provenance.API_ROOT}/repos/{repo}/issues/99",
              "body": provenance.PREFIX + json.dumps(review_payload)}
    receipt = {"schema_version": 1, "identity": identity, "assurance": provenance.ASSURANCE,
               "session_separation": "operator-declared", "third_party_identity_proven": False,
               "review_comment_id": 9, "review_body_sha256": MODULE.digest(review["body"].encode())}
    receipt["fingerprint"] = MODULE.digest(MODULE.canonical(receipt))
    check = {"id": 7, "name": provenance.CHECK, "head_sha": original["head_sha"],
        "status": "completed", "conclusion": "success", "app": {"id": 15368}, "check_suite": {"id": 55},
        "external_id": receipt["fingerprint"], "details_url": f"https://github.com/{repo}/actions/runs/8",
        "output": {"text": json.dumps(receipt)}}
    run = {"id": 8, "workflow_id": 101, "check_suite_id": 56, "head_sha": source,
           "head_branch": "main", "repository": {"full_name": repo}, "head_repository": {"full_name": repo},
           "path": provenance.WORKFLOW, "status": "completed", "conclusion": "success", "event": "workflow_run"}
    tree = {"sha": "7"*40, "truncated": False, "tree": [
        {"path": p, "sha": "8"*40, "mode": "100644", "type": "blob"} for p in provenance.TRUSTED]}
    blob = hashlib.sha1(b"blob " + str(len(policy)).encode() + b"\0" + policy).hexdigest()
    inventory = {"total_count": 1, "check_runs": [check]}
    posted = []
    responses = {
        "/user": actor,
        f"{root}/pulls/99": {"number": 99, "state": "open", "draft": False, "body": "Refs #196",
            "head": {"sha": original["head_sha"], "repo": {"full_name": repo}},
            "base": {"sha": original["base_sha"], "ref": "develop", "repo": {"full_name": repo}},
            "merge_commit_sha": original["merge_preview_sha"]},
        f"{root}/branches/develop": {"protected": True, "commit": {"sha": original["base_sha"]}},
        f"{root}/branches/main": {"protected": True, "commit": {"sha": source}},
        f"{root}/issues/196": issue(),
        f"{root}/issues/196/comments?per_page=100": posted,
        f"{root}/issues/99/comments?per_page=100": [review],
        f"{root}/issues/comments/9": review,
        f"{root}/commits/{original['head_sha']}/check-runs?per_page=100&filter=all": inventory,
        f"{root}/check-runs/7": check,
        f"{root}/actions/runs/8": run,
        f"{root}/actions/workflows/session-review.yml": {"id": 101, "path": provenance.WORKFLOW},
        f"{root}/check-suites/55": {"id": 55, "head_sha": original["head_sha"], "app": {"id": 15368}},
        f"{root}/check-suites/56": {"id": 56, "head_sha": source, "app": {"id": 15368}},
        f"{root}/git/commits/{source}": {"sha": source, "tree": {"sha": "7"*40}},
        f"{root}/git/commits/{original['base_sha']}": {"sha": original["base_sha"], "tree": {"sha": "7"*40}},
        f"{root}/git/trees/{'7'*40}?recursive=1": tree,
        f"{root}/contents/{provenance.POLICY}?ref={original['base_sha']}": {
            "type": "file", "encoding": "base64", "sha": blob, "content": base64.b64encode(policy).decode()},
    }
    calls = []

    def api(path, *, method="GET", payload=None, **_):
        calls.append((method, path))
        if method == "POST":
            assert path == f"{root}/issues/196/comments"
            published = {"body": payload["body"], "id": 12, "user": actor,
                "created_at": "2026-11-24T22:30:00Z", "updated_at": "2026-11-24T22:30:00Z",
                "html_url": f"https://github.com/{repo}/issues/196#issuecomment-12",
                "issue_url": f"{provenance.API_ROOT}/repos/{repo}/issues/196"}
            posted.append(published)
            responses[f"{root}/issues/comments/12"] = published
            return published
        assert method == "GET"
        return deepcopy(responses[path])

    return api, check, review, run, calls


def trusted_check(value, report_sha=None):
    return MODULE.verify_required_audit_checks("owner/repo", "1" * 40,
        report_sha or MODULE.digest(MODULE.canonical(value)), {**value["identity"], "base_ref": "develop"})


def test_suites_have_different_anchors_and_receipt_binds_legacy_review(monkeypatch):
    value = canonical_report()
    api, check, _, run, _ = remote(value)
    assert check["check_suite"]["id"] != run["check_suite_id"]
    monkeypatch.setattr(MODULE, "run_gh", api)
    assert trusted_check(value)[0] == 7
    with pytest.raises(ValueError, match="exact audit report"):
        trusted_check(value, "b" * 64)


@pytest.mark.parametrize(("field", "change", "failure"), [
    ("conclusion", "failure", "not green"),
    ("details_url", "https://github.com/owner/repo/runs/7", "invalid review workflow run URL"),
    ("external_id", "f" * 64, "receipt fingerprint mismatch"),
    ("check_suite", {"id": 56}, "wrong GitHub Actions check suite"),
])
def test_invalid_check_provenance_is_closed(monkeypatch, field, change, failure):
    value = canonical_report()
    api, check, _, _, _ = remote(value)
    check[field] = change
    monkeypatch.setattr(MODULE, "run_gh", api)
    with pytest.raises(ValueError, match=failure):
        trusted_check(value)


def test_edited_review_is_not_accepted(monkeypatch):
    value = canonical_report()
    api, _, review, _, _ = remote(value)
    review["updated_at"] = "2026-11-24T22:12:00Z"
    monkeypatch.setattr(MODULE, "run_gh", api)
    with pytest.raises(ValueError, match="edited or undated"):
        trusted_check(value)


def test_report_digest_marker_cannot_duplicate_or_replace_analysis():
    good = "AUDIT_REPORT_SHA256=" + HASH
    with pytest.raises(ValueError, match="one canonical"):
        MODULE.provenance.review_digest({"requirements": [{"analysis": good + "\n" + good}]})
    with pytest.raises(ValueError, match="one canonical"):
        MODULE.provenance.review_digest({"requirements": [{"analysis": "narrative " + good}]})


def test_criteria_include_multiline_nested_text_but_not_inert_code():
    markdown = ("## Critérios de aceite\n- [ ] Pai\n  Continuação normativa.\n"
                "  - [ ] Filho\n    Continuação do filho.\n\n" + chr(96)*3 +
                "\n- [ ] Não é critério\n" + chr(96)*3 + "\n- Sem checkbox\n")
    assert MODULE.acceptance_lines(markdown) == [2, 4, 10]
    assert MODULE.source_item(markdown, 2) == ("unchecked", "Pai Continuação normativa.")
    assert MODULE.source_item(markdown, 4) == ("unchecked", "Filho Continuação do filho.")
    with pytest.raises(ValueError, match="not a normative"):
        MODULE.source_item(markdown, 8)


def test_lazy_multiline_criterion_does_not_drop_authored_prose():
    markdown = "## Acceptance criteria\n- [ ] Main statement\ncontinues with a binding condition.\n\nUnrelated paragraph.\n"
    assert MODULE.source_item(markdown, 2) == ("unchecked", "Main statement continues with a binding condition.")


def full_report(tmp_path):
    value = canonical_report()
    proof = tmp_path / "control.txt"
    proof.write_text("synthetic verified evidence", encoding="utf-8")
    for requirement in value["requirements"]:
        requirement["negative_controls"] = ["N-1"]
        requirement["negative_control_evidence"] = [{"id": "N-1", "risk_family": "source",
            "dimension": "missing-evidence", "failure_mode": "fails to retain exact target",
            "plausible_wrong_implementation": "allows unrelated snapshot", "control_type": "test",
            "procedure": "test protected branch binding", "expected": "rejected", "observed": "rejected",
            "status": "passed", "evidence_path": proof.name, "evidence_sha256": MODULE.digest(proof.read_bytes()),
            "head_sha": value["identity"]["head_sha"], "sibling_cases": []}]
    return value


def apply_arguments(monkeypatch, path, extra=()):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--audit-report", str(path),
        "--repository", "owner/repo", "--issue", "196", "--head-sha", "1"*40, "--apply", *extra])


def test_cli_appends_and_reuses_authorized_immutable_readback(tmp_path, monkeypatch, capsys):
    value = full_report(tmp_path)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))
    api, _, _, _, calls = remote(value)
    monkeypatch.setattr(MODULE, "run_gh", api)
    apply_arguments(monkeypatch, path)
    assert MODULE.main() == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "published" and receipt["audit_review_comment_id"] == 9
    assert MODULE.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already-published"
    assert [m for m, _ in calls if m != "GET"] == ["POST"]


def test_cli_uses_semantic_validator_and_fails_before_write(tmp_path, monkeypatch, capsys):
    value = canonical_report()  # structurally valid; lacks any negative controls.
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))
    api, _, _, _, calls = remote(value)
    monkeypatch.setattr(MODULE, "run_gh", api)
    apply_arguments(monkeypatch, path)
    assert MODULE.main() == 2
    assert "canonical semantic report validation failed" in capsys.readouterr().err
    assert all(method == "GET" for method, _ in calls)


def test_cli_rejects_caller_selected_trust_authority(tmp_path, monkeypatch, capsys):
    apply_arguments(monkeypatch, tmp_path / "unused", ["--required-audit-check", "Other"])
    assert MODULE.main() == 2
    assert "only the canonical" in capsys.readouterr().err


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
