from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

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
            requirement("REQ-1", 7, "O fluxo publica a decisão."),
            requirement("REQ-2", 8, "O fluxo preserva o corpo."),
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


def requirement(identifier: str, line: int, text: str) -> dict:
    return {"id": identifier, "status": "Implementado", "origin": "SRC-ISSUE",
            "statement": text, "source_locator": "issue-body", "source_line": line,
            "source_sha256": hashlib.sha256(BODY.encode()).hexdigest(),
            "evidence": [f"{ROOT}/evidence:{line}"]}


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
    changed["verdict"] = "Reprovado"
    changed["requirements"][1]["status"] = "Parcial"
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
    changed["verdict"] = "Reprovado"
    changed["requirements"] = [requirement("REQ-1", 4, item["text"])]
    changed["requirements"][0].update(status="Nao verificavel", source_sha256=item["source_sha256"])
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
    for requirement in value["requirements"]:
        requirement.update({
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


def remote(report_value, *, regenerated_preview=None, edit_origin=None, source_comments=()):
    provenance = MODULE.provenance
    repo = "owner/repo"
    root = f"/repos/{repo}"
    actor = {"id": 41, "login": "owner", "type": "User"}
    original = report_value["identity"]
    current_preview = regenerated_preview or original["merge_preview_sha"]
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
    receipt["publication_origin"] = {"schema_version": 2, "run_id": 8, "run_attempt": 1}
    receipt["fingerprint"] = MODULE.digest(MODULE.canonical(receipt))
    check = {"id": 7, "name": provenance.CHECK, "head_sha": original["head_sha"],
        "status": "completed", "conclusion": "success", "app": {"id": 15368}, "check_suite": {"id": 55},
        "external_id": receipt["fingerprint"], "details_url": f"https://github.com/{repo}/runs/7",
        "output": {"text": json.dumps(receipt)}}
    run = {"id": 8, "run_attempt": 1, "workflow_id": 101, "check_suite_id": 56, "head_sha": source,
           "head_branch": "main", "repository": {"full_name": repo, "id": 73},
           "head_repository": {"full_name": repo, "id": 73},
           "path": provenance.WORKFLOW, "status": "completed", "conclusion": "success", "event": "workflow_run"}
    tree = {"sha": "7"*40, "truncated": False, "tree": [
        {"path": p, "sha": "8"*40, "mode": "100644", "type": "blob"} for p in provenance.TRUSTED]}
    blob = hashlib.sha1(b"blob " + str(len(policy)).encode() + b"\0" + policy).hexdigest()
    inventory = {"total_count": 1, "check_runs": [check]}
    record = {**receipt["publication_origin"], "check_id": 7, "check_suite_id": 55,
              "receipt_sha256": MODULE.digest(MODULE.canonical(receipt))}
    attempt = deepcopy(run)
    art_name = "session-review-origin-v2-attempt-1"
    artifact = {"id": 15, "name": art_name, "expired": False,
                "expires_at": "2099-01-01T00:00:00Z",
                "workflow_run": {"id": 8, "repository_id": 73, "head_repository_id": 73,
                                 "head_branch": "main", "head_sha": source}}
    artifacts = {"total_count": 1, "artifacts": [artifact]}
    inv = {"run": run, "attempt": attempt, "record": record, "check": check,
           "artifact": artifact, "artifacts": artifacts}
    if edit_origin:
        edit_origin(inv)
    output = BytesIO()
    with ZipFile(output, "w") as zipped:
        zipped.writestr(inv.get("member", "7.json"), MODULE.canonical(record))
        if inv.get("extra"):
            zipped.writestr("extra.json", "{}")
    archive = output.getvalue()
    artifact.setdefault("digest", "sha256:" + MODULE.digest(archive))
    artifact.setdefault("size_in_bytes", len(archive))
    posted = list(source_comments)
    responses = {
        "/user": actor,
        f"{root}/pulls/99": {"number": 99, "state": "open", "draft": False, "body": "Refs #196",
            "head": {"sha": original["head_sha"], "repo": {"full_name": repo}},
            "base": {"sha": original["base_sha"], "ref": "develop", "repo": {"full_name": repo}},
            "merge_commit_sha": current_preview},
        f"{root}/branches/develop": {"protected": True, "commit": {"sha": original["base_sha"]}},
        f"{root}/branches/main": {"protected": True, "commit": {"sha": source}},
        f"{root}/issues/196": issue(),
        f"{root}/issues/196/comments?per_page=100": posted,
        f"{root}/issues/99/comments?per_page=100": [review],
        f"{root}/issues/comments/9": review,
        f"{root}/commits/{original['head_sha']}/check-runs?per_page=100&filter=all": inventory,
        f"{root}/check-runs/7": check,
        f"{root}/actions/runs/8": run,
        f"{root}/actions/runs/8/attempts/1": attempt,
        f"{root}/actions/runs/8/artifacts?name={art_name}&per_page=100": artifacts,
        f"{root}/actions/artifacts/15/zip": archive,
        f"{root}/actions/workflows/session-review.yml": {"id": 101, "path": provenance.WORKFLOW},
        f"{root}/check-suites/55": {"id": 55, "head_sha": original["head_sha"], "app": {"id": 15368}},
        f"{root}/check-suites/56": {"id": 56, "head_sha": source, "app": {"id": 15368}},
        f"{root}/git/commits/{source}": {"sha": source, "tree": {"sha": "7"*40}},
        f"{root}/git/commits/{original['base_sha']}": {"sha": original["base_sha"], "tree": {"sha": "7"*40}},
        f"{root}/git/trees/{'7'*40}?recursive=1": tree,
        f"{root}/contents/{provenance.POLICY}?ref={original['base_sha']}": {
            "type": "file", "encoding": "base64", "sha": blob, "content": base64.b64encode(policy).decode()},
    }
    for preview in (original["merge_preview_sha"], current_preview):
        responses[f"{root}/git/commits/{preview}"] = {
            "sha": preview, "tree": {"sha": "9" * 40},
            "parents": [{"sha": original["base_sha"]}, {"sha": original["head_sha"]}],
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


def test_suites_have_different_anchors_and_v2_binds_exact_report(monkeypatch):
    value = canonical_report()
    api, check, _, run, calls = remote(value)
    assert check["check_suite"]["id"] != run["check_suite_id"]
    monkeypatch.setattr(MODULE, "run_gh", api)
    check_id, binding = trusted_check(value)
    assert check_id == 7 and binding["origin"]["run_id"] == 8
    assert not any(path.endswith("/actions/runs/7") for _, path in calls)
    with pytest.raises(ValueError, match="exact audit report"):
        trusted_check(value, "b" * 64)


@pytest.mark.parametrize(("field", "change", "failure"), [
    ("conclusion", "failure", "not green"),
    ("details_url", "https://github.com/owner/repo/runs/8", "invalid review workflow run URL"),
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


def test_binary_transport_reads_exact_bytes_and_bounds_stream():
    command = [sys.executable, "-c", "import sys;sys.stdout.buffer.write(bytes(range(256)))"]
    assert MODULE.read_bounded_archive(command, 256) == bytes(range(256))
    with pytest.raises(ValueError, match="size bound"):
        MODULE.read_bounded_archive(command, 255)


def test_protected_source_requires_ancestry_and_executable_closure(monkeypatch):
    value = canonical_report()
    api, _, _, run, _ = remote(value)
    root = "/repos/owner/repo"
    source, tip = run["head_sha"], "a" * 40
    comparison = {"status": "diverged", "merge_base_commit": {"sha": "b" * 40}}
    source_tree = None

    def facts(path, **kwargs):
        if path == f"{root}/branches/main":
            return {"protected": True, "commit": {"sha": tip}}
        if path == f"{root}/compare/{source}...{tip}?per_page=1":
            return comparison
        if path == f"{root}/git/commits/{source}" and source_tree is not None:
            return {"sha": source, "tree": {"sha": "a" * 40}}
        if path == f"{root}/git/trees/{'a' * 40}?recursive=1":
            return source_tree
        return api(path, **kwargs)

    monkeypatch.setattr(MODULE, "run_gh", facts)
    with pytest.raises(ValueError, match="protected branch ancestry"):
        trusted_check(value)
    comparison.update(status="ahead", merge_base_commit={"sha": source})
    assert trusted_check(value)[0] == 7
    source_tree = api(f"{root}/git/trees/{'7' * 40}?recursive=1")
    source_tree["sha"] = "a" * 40
    next(x for x in source_tree["tree"] if x["path"] == "scripts/dispatch_session_review.py")["sha"] = tip
    with pytest.raises(ValueError, match="source differs"):
        trusted_check(value)


def test_direct_workflow_url_still_requires_exact_v2_origin(monkeypatch):
    value = canonical_report()
    api, check, _, _, calls = remote(value)
    check["details_url"] = "https://github.com/owner/repo/actions/runs/8"
    monkeypatch.setattr(MODULE, "run_gh", api)
    assert trusted_check(value)[1]["origin"]["run_id"] == 8
    parsed = json.loads(check["output"]["text"])
    parsed.pop("publication_origin")
    check["output"]["text"] = json.dumps(parsed)
    calls.clear()
    with pytest.raises(ValueError, match="official V2"):
        trusted_check(value)
    assert not any("/actions/runs/" in path for _, path in calls)


@pytest.mark.parametrize(("modify", "error"), [
    (lambda x: x["attempt"].update(run_attempt=2), "attempt differs"),
    (lambda x: x["run"].update(run_attempt=2), "attempt differs"),
    (lambda x: [x[k].update(workflow_id=102) for k in ("run", "attempt")], "workflow identity"),
    (lambda x: x["attempt"]["repository"].update(id=19), "protected-source"),
    (lambda x: x["check"]["app"].update(id=15368.0), "not produced by GitHub Actions"),
    (lambda x: x["artifacts"].update(total_count=0, artifacts=[]), "unique review origin"),
    (lambda x: x["artifacts"].update(total_count=2, artifacts=[x["artifact"]]*2), "unique review origin"),
    (lambda x: x["artifact"].update(expired=True), "expiry"),
    (lambda x: x["artifact"].update(expires_at="2000-01-01T00:00:00Z"), "is expired"),
    (lambda x: x["artifact"]["workflow_run"].update(head_repository_id=19), "artifact identity"),
    (lambda x: x["artifact"].update(digest="sha256:" + "b" * 64), "authenticated digest"),
    (lambda x: x.update(member="8.json"), "artifact member"),
    (lambda x: x.update(extra=True), "artifact member"),
    (lambda x: x["record"].update(schema_version=2.0), "exact receipt"),
    (lambda x: x["record"].update(check_suite_id=56), "exact receipt"),
    (lambda x: x["record"].update(receipt_sha256="c"*64), "exact receipt"),
])
def test_v2_requires_current_authentic_origin(monkeypatch, modify, error):
    value = canonical_report()
    api, _, _, _, calls = remote(value, edit_origin=modify)
    monkeypatch.setattr(MODULE, "run_gh", api)
    with pytest.raises(ValueError, match=error):
        trusted_check(value)
    assert not any(path.endswith("/issues/comments/9") for _, path in calls)


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


@pytest.mark.parametrize("regenerated_preview", [None, "4" * 40])
def test_cli_appends_and_reuses_authorized_immutable_readback(tmp_path, monkeypatch, capsys, regenerated_preview):
    value = full_report(tmp_path)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))
    api, _, _, _, calls = remote(value, regenerated_preview=regenerated_preview)
    monkeypatch.setattr(MODULE, "run_gh", api)
    apply_arguments(monkeypatch, path)
    assert MODULE.main() == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "published" and receipt["audit_review_comment_id"] == 9
    assert receipt["audit_report_sha256"] == MODULE.digest(MODULE.canonical(value))
    assert json.loads(path.read_bytes())["identity"]["merge_preview_sha"] == "3" * 40
    assert ("GET", f"/repos/owner/repo/git/commits/{'3' * 40}") in calls
    if regenerated_preview:
        assert ("GET", f"/repos/owner/repo/git/commits/{regenerated_preview}") in calls
    assert MODULE.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "already-published"
    assert [m for m, _ in calls if m != "GET"] == ["POST"]


def issue_comment(number, body):
    return {"id": number, "body": body,
            "issue_url": f"{MODULE.provenance.API_ROOT}/repos/owner/repo/issues/196"}


def add_comment_requirement(value, comment, line, text, *, include_decision=True):
    suffix = f"{comment['id']}-{line}"
    req_id = f"REQ-C-{suffix}"
    source_id, locator = f"SRC-C-{comment['id']}", f"issue-comment:{comment['id']}"
    digest = MODULE.digest(comment["body"].encode())
    req = deepcopy(value["requirements"][0])
    req.update(id=req_id, origin=source_id, source_locator=locator,
               source_sha256=digest, source_line=line, statement=text)
    value["requirements"].append(req)
    if include_decision:
        row = criterion(f"AC-C-{suffix}", req_id, line, text, "unchecked")
        row.update(origin="issue-comment", source_id=source_id, source_locator=locator,
                   source_sha256=digest, evidence=req["evidence"])
        value["acceptance_criteria"].append(row)


def comment_inventory(value, *, first_row=True, second_rows=True):
    statement = "Preservar a quantidade explícita."
    first = issue_comment(31,
        f"## Critérios de aceite\n- [ ] {statement}\n- [ ] {statement}\n")
    add_comment_requirement(value, first, 2, statement, include_decision=first_row)
    add_comment_requirement(value, first, 3, statement)
    second = issue_comment(32,
        "## Acceptance criteria\n- [ ] Manter o campo original.\n- [ ] Registrar o resultado.\n")
    add_comment_requirement(value, second, 2, "Manter o campo original.", include_decision=second_rows)
    add_comment_requirement(value, second, 3, "Registrar o resultado.", include_decision=second_rows)
    explanatory = issue_comment(33, "## Escopo\n- Preservar o histórico.\n")
    add_comment_requirement(value, explanatory, 2, "Preservar o histórico.", include_decision=False)
    unrelated = issue_comment(34, "## Critérios de aceite\n- [ ] Exemplo não selecionado.\n")
    return [first, second, explanatory, unrelated]


@pytest.mark.parametrize(("missing", "expected"), [
    ("none", None),
    ("one-of-identical", "issue-comment:31 (missing=[2])"),
    ("whole-selected-comment", "issue-comment:32 (missing=[2, 3])"),
])
def test_cli_requires_complete_line_inventory_for_each_selected_comment(tmp_path, monkeypatch, capsys,
                                                                  missing, expected):
    value = full_report(tmp_path)
    comments = comment_inventory(value, first_row=missing != "one-of-identical",
                                 second_rows=missing != "whole-selected-comment")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))
    api, _, _, _, calls = remote(value, source_comments=comments)
    monkeypatch.setattr(MODULE, "run_gh", api)
    apply_arguments(monkeypatch, path)
    assert MODULE.main() == (0 if expected is None else 2)
    captured = capsys.readouterr()
    if expected is None:
        assert json.loads(captured.out)["status"] == "published"
        assert [m for m, _ in calls if m != "GET"] == ["POST"]
    else:
        assert expected in captured.err
        assert all(method == "GET" for method, _ in calls)


@pytest.mark.parametrize(("change", "message"), [
    ("missing", "unavailable normative issue comments"),
    ("edited", "source changed since the audit"),
    ("expanded", "source changed since the audit"),
    ("duplicate", "ambiguous or unauthenticated normative issue comment"),
    ("other-issue", "ambiguous or unauthenticated normative issue comment"),
])
def test_cli_rechecks_normative_comment_readback_before_post(tmp_path, monkeypatch, capsys, change, message):
    value = full_report(tmp_path)
    comments = comment_inventory(value)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))
    api, _, _, _, calls = remote(value, source_comments=comments)
    reads = 0

    def facts(route, **kwargs):
        nonlocal reads
        result = api(route, **kwargs)
        if not route.endswith("/issues/196/comments?per_page=100"):
            return result
        reads += 1
        if reads != 2:
            return result
        selected = next(c for c in result if c["id"] == 32)
        if change == "missing":
            result.remove(selected)
        elif change == "edited":
            selected["body"] = selected["body"].replace("original", "revisado")
        elif change == "expanded":
            selected["body"] += "- [ ] Critério novo.\n"
        elif change == "duplicate":
            result.append(deepcopy(selected))
        elif change == "other-issue":
            selected["issue_url"] = selected["issue_url"].replace("/196", "/197")
        return result

    monkeypatch.setattr(MODULE, "run_gh", facts)
    apply_arguments(monkeypatch, path)
    assert MODULE.main() == 2
    assert message in capsys.readouterr().err
    assert reads == 2 and all(method == "GET" for method, _ in calls)


@pytest.mark.parametrize(("body", "reason"), [
    ("## Critérios de aceite\nTexto sem lista.\n", "has no list items"),
    ("## Critérios de aceite\n- [ ] Primeiro.\n"
     "## Acceptance criteria\n- [ ] Segundo.\n", "Expected exactly one"),
])
def test_selected_comment_requires_well_formed_acceptance_section_when_present(body, reason):
    value = report()
    selected = issue_comment(32, body)
    add_comment_requirement(value, selected, 2, "Declarar o critério.", include_decision=False)
    with pytest.raises(ValueError, match=reason):
        validate_report_against_sources(value, repository="owner/repo", issue_number=196,
                                        head_sha="1"*40, issue=issue(), comments=[selected])


def test_issue_body_still_requires_actual_acceptance_section():
    value = report()
    body = "## Escopo\n- Preservar o histórico.\n"
    value["identity"]["issue_snapshot_sha256"] = MODULE.digest(body.encode())
    value["acceptance_criteria"] = []
    with pytest.raises(ValueError, match="Expected exactly one"):
        validate_report_against_sources(value, repository="owner/repo", issue_number=196,
                                        head_sha="1"*40, issue={**issue(), "body": body}, comments=[])


def test_rejects_same_comment_line_with_two_separate_decisions():
    value = report()
    comments = comment_inventory(value)
    duplicate = deepcopy(value["acceptance_criteria"][-1])
    duplicate["id"] = "AC-DUPLICATE"
    req = deepcopy(value["requirements"][-2])
    req["id"] = "REQ-DUPLICATE"
    duplicate["requirement_id"] = req["id"]
    value["requirements"].append(req)
    value["acceptance_criteria"].append(duplicate)
    with pytest.raises(ValueError, match="criterion source locations must be unique"):
        validate_report_against_sources(value, repository="owner/repo", issue_number=196,
                                        head_sha="1"*40, issue=issue(), comments=comments)


@pytest.mark.parametrize(("drift", "error"), [
    ("null-current", "invalid certified or live merge preview"),
    ("reversed-parents", "incorrect authenticated ordered parents"),
    ("extra-parent", "incorrect authenticated ordered parents"),
    ("tree-change", "different authenticated Git trees"),
    ("missing-tree", "missing authenticated Git tree"),
    ("wrong-object", "commit missing or mismatched"),
    ("missing-commit", "commit missing or mismatched"),
    ("invalid-certification-despite-same-sha", "incorrect authenticated ordered parents"),
])
def test_cli_fails_before_publication_for_unproven_merge_preview(tmp_path, monkeypatch, capsys, drift, error):
    value = full_report(tmp_path)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))
    certified, regenerated = "3" * 40, "4" * 40
    if drift == "invalid-certification-despite-same-sha":
        regenerated = certified
    api, _, _, _, calls = remote(value, regenerated_preview=regenerated)
    preview_route = f"/repos/owner/repo/git/commits/{regenerated}"

    def with_drift(route, **kwargs):
        obj = api(route, **kwargs)
        if drift == "null-current" and route == "/repos/owner/repo/pulls/99":
            obj["merge_commit_sha"] = None
        if route == preview_route:
            if drift in {"reversed-parents", "invalid-certification-despite-same-sha"}:
                obj["parents"].reverse()
            elif drift == "extra-parent":
                obj["parents"].append({"sha": "5" * 40})
            elif drift == "tree-change":
                obj["tree"]["sha"] = "5" * 40
            elif drift == "missing-tree":
                del obj["tree"]
            elif drift == "wrong-object":
                obj["sha"] = certified
            elif drift == "missing-commit":
                return {}
        return obj

    monkeypatch.setattr(MODULE, "run_gh", with_drift)
    apply_arguments(monkeypatch, path)
    assert MODULE.main() == 2
    assert error in capsys.readouterr().err
    assert all(method == "GET" for method, _ in calls)


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


@pytest.mark.parametrize("mutation", ["wrong-requirement", "wrong-evidence", "wrong-source",
                                      "wrong-line", "wrong-digest", "wrong-text", "missing-binding",
                                      "inconclusive", "partial", "failed", "unjustified-na"])
def test_cli_rejects_inconsistent_criterion_before_post(tmp_path, monkeypatch, capsys, mutation):
    value = full_report(tmp_path)
    item, req = value["acceptance_criteria"][1], value["requirements"][1]
    if mutation == "wrong-requirement":
        item.update(requirement_id="REQ-1", evidence=value["requirements"][0]["evidence"])
    elif mutation == "wrong-evidence":
        item["evidence"] = value["requirements"][0]["evidence"]
    elif mutation == "wrong-source":
        req["origin"] = "SRC-OTHER"
    elif mutation == "wrong-line":
        req["source_line"] = 7
    elif mutation == "wrong-digest":
        req["source_sha256"] = HASH
    elif mutation == "wrong-text":
        req["statement"] = value["requirements"][0]["statement"]
    elif mutation == "missing-binding":
        del req["source_locator"]
    elif mutation == "unjustified-na":
        item.update(decision="not-applicable", evidence=[], proposed_checkbox_state="unchecked")
        req["status"] = "Fora do escopo"
    else:
        item.update(decision=mutation, evidence=[], proposed_checkbox_state="unchecked")
        req["status"] = {"inconclusive": "Nao verificavel", "partial": "Parcial", "failed": "Incorreto"}[mutation]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(value))
    api, _, _, _, calls = remote(value)
    monkeypatch.setattr(MODULE, "run_gh", api)
    apply_arguments(monkeypatch, path)
    assert MODULE.main() == 2
    assert "BLOCK:" in capsys.readouterr().err
    assert all(method == "GET" for method, _ in calls)


@pytest.mark.parametrize("opener,example", [("```", "- [ ] Example"), ("~~~", "- [ ] Example"),
    ("<!--", "- [ ] Hidden"), ("<pre>", "- [ ] Raw"), ("<div>", "- [ ] Raw")])
@pytest.mark.parametrize("indent", ["  ", "    "])
def test_container_inert_block_does_not_swallow_sibling(opener, example, indent):
    prefix = "- [ ] " if indent == "  " else "  - [ ] "
    parent = "" if indent == "  " else "- [ ] Parent\n"
    markdown = ("## Acceptance criteria\n" + parent + prefix + "First\n" + indent + opener +
                "\n" + indent + example + "\n" + prefix + "Second\n")
    expected = [2, 5] if not parent else [2, 3, 6]
    assert MODULE.acceptance_lines(markdown) == expected


def test_duplicate_text_criteria_require_distinct_source_lines():
    body = "## Acceptance criteria\n- [ ] Identical criterion.\n- [ ] Identical criterion.\n"
    value = report()
    digest = MODULE.digest(body.encode())
    value["identity"]["issue_snapshot_sha256"] = digest
    for i, (item, req) in enumerate(zip(value["acceptance_criteria"], value["requirements"], strict=True), 2):
        item.update(text="Identical criterion.", source_line=i, source_sha256=digest,
                    initial_checkbox_state="unchecked")
        req.update(statement=item["text"], source_line=i, source_sha256=digest)
    def check():
        validate_report_against_sources(value, repository="owner/repo", issue_number=196,
                                        head_sha="1"*40, issue={"state": "open", "body": body}, comments=[])
    check()
    value["acceptance_criteria"][1]["requirement_id"] = "REQ-1"
    with pytest.raises(ValueError, match="distinct atomic requirements"):
        check()
