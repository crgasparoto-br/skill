"""Fail-closed controls for the separate solo Ed25519 exact-SHA gate."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "entregar-issue" / "scripts"))

import handoff_merge_preview as preview  # noqa: E402 - sys.path ajustado acima antes do import local
import solo_audit_check_runs as checks  # noqa: E402 - sys.path ajustado acima antes do import local
import solo_audit_contract as contract  # noqa: E402 - sys.path ajustado acima antes do import local
import solo_audit_events as events  # noqa: E402 - sys.path ajustado acima antes do import local
import solo_audit_github as ghgate  # noqa: E402 - sys.path ajustado acima antes do import local
import solo_audit_source as source  # noqa: E402 - sys.path ajustado acima antes do import local
import verify_independent_pr_audit as native  # noqa: E402 - sys.path ajustado acima antes do import local
import verify_session_review as session_runner  # noqa: E402 - sys.path ajustado acima antes do import local
import verify_solo_audit_attestation as gate  # noqa: E402 - sys.path ajustado acima antes do import local

REPO = "crgasparoto-br/skill"
API_BASE = "https://example.com"
BASE = "b" * 40
HEAD = "a" * 40
PREVIEW = "c" * 40
ISSUE = 175
PR = 174
OPERATOR = 12345678
KEY_ID = "solo-key-1"


@pytest.fixture(autouse=True)
def use_reserved_github_api_base(monkeypatch):
    monkeypatch.setenv("GITHUB_API_URL", API_BASE)


def values(*, enabled="true", operator=str(OPERATOR), key_id=KEY_ID, repositories=None, registry=None):
    registry = registry or {
        "schema_version": 1,
        "auditors": [{"key_id": KEY_ID, "enabled": True, "repositories": repositories or [REPO]}],
    }
    return {
        "SOLVERIT_TRUSTED_AUDITORS_JSON": json.dumps(registry, separators=(",", ":")),
        "SOLVERIT_SOLO_AUDIT_OPERATOR_ID": operator,
        "SOLVERIT_SOLO_AUDIT_KEY_ID": key_id,
        "SOLVERIT_SOLO_AUDIT_ENABLED": enabled,
    }


def config(**kwargs):
    return contract.parse_trusted_config(values(**kwargs), REPO)


def report_payload(**overrides):
    payload = {
        "schema_version": 3,
        "report_id": "report-identity-123456",
        "repository": REPO,
        "issue": ISSUE,
        "pull_request": PR,
        "issue_body_sha256": "d" * 64,
        "assurance_mode": contract.ASSURANCE_MODE,
        "independent": False,
        "same_conversation": False,
        "operator_github_id": OPERATOR,
        "verdict": "approved",
        "findings": [],
        "recommendations": [],
        "limitations": [],
    }
    payload.update(overrides)
    return payload


def comment(body=None, *, user_id=OPERATOR, login="gaspa", user_type="User", updated=None):
    body = body if body is not None else contract.COMMENT_MARKER + "\n" + json.dumps(report_payload())
    return {
        "id": 42,
        "body": body,
        "user": {"id": user_id, "login": login, "type": user_type},
        "url": f"{API_BASE}/repos/{REPO}/issues/comments/42",
        "issue_url": f"{API_BASE}/repos/{REPO}/issues/{PR}",
        "created_at": "2026-11-03T17:00:00Z",
        "updated_at": updated or "2026-11-03T17:00:00Z",
    }


def live_pr(number=PR, *, head=HEAD, base=BASE, body=None):
    return {
        "number": number,
        "state": "open",
        "merged": False,
        "draft": False,
        "body": body or f"Closes #{ISSUE}",
        "merge_commit_sha": PREVIEW,
        "base": {"ref": "develop", "sha": base, "repo": {"full_name": REPO}},
        "head": {"sha": head, "ref": "feature/test", "repo": {"full_name": REPO}},
    }


def identity(**overrides):
    result = {
        "repository": REPO,
        "pull_request": PR,
        "issue": ISSUE,
        "base_ref": "develop",
        "base_sha": BASE,
        "head_sha": HEAD,
        "merge_preview_sha": PREVIEW,
        "issue_body_sha256": "d" * 64,
    }
    result.update(overrides)
    return result


def make_signed_report(tmp_path, target):
    private_key, public_key = tmp_path / "private.pem", tmp_path / "public.pem"
    report_path = tmp_path / "report.json"
    scripts = ROOT / "auditar-issue" / "scripts"
    subprocess.run([
        sys.executable, str(scripts / "generate_auditor_keypair.py"),
        "--private-out", str(private_key), "--public-out", str(public_key),
    ], check=True, capture_output=True, text=True)
    public_pem = public_key.read_text(encoding="utf-8")
    registry = {"schema_version": 1, "auditors": [{
        "key_id": KEY_ID, "name": "Configured solo operator", "enabled": True,
        "repositories": [target["repository"]], "public_key_pem": public_pem,
        "public_key_sha256": hashlib.sha256(public_pem.encode("utf-8")).hexdigest(),
    }]}
    registry_raw = json.dumps(registry, separators=(",", ":")).encode("utf-8")
    subprocess.run([
        sys.executable, str(scripts / "init_external_audit_report.py"),
        "--repository", target["repository"], "--issue", str(target["issue"]),
        "--pull-request", str(target["pull_request"]),
        "--issue-body-sha256", target["issue_body_sha256"],
        "--assurance-mode", contract.ASSURANCE_MODE,
        "--operator-github-id", str(OPERATOR), "--base-ref", target["base_ref"],
        "--head-sha", target["head_sha"], "--base-sha", target["base_sha"],
        "--merge-preview-sha", target["merge_preview_sha"],
        "--orchestration-cycle", "1", "--implementation-context-id", "implementation-context-1",
        "--audit-context-id", "separate-audit-context-1", "--context-proof-kind", "agent-run-id",
        "--context-proof-value", "separate-audit-context-1", "--context-proof-issuer", "configured-runner",
        "--origin", "Declared separate context; no third-party human approval claimed",
        "--out", str(report_path),
    ], check=True, capture_output=True, text=True)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["evidence"] = [{"id": "EV-1", "claim": "Exact target reviewed in declared context.",
                            "source": "configured execution log", "observed_at": payload["issued_at"]}]
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    subprocess.run([
        sys.executable, str(scripts / "sign_external_audit_report.py"),
        str(report_path), "--private-key", str(private_key), "--key-id", KEY_ID,
    ], check=True, capture_output=True, text=True)
    raw_report = report_path.read_bytes()
    trusted = contract.TrustedConfig(OPERATOR, KEY_ID, registry_raw, registry,
                                     hashlib.sha256(registry_raw).hexdigest())
    entry = comment(body=contract.COMMENT_MARKER + "\n" + raw_report.decode("utf-8"))
    return trusted, entry, raw_report


def test_valid_configuration_requires_exact_repo_operator_and_enabled_key():
    trusted = config()
    assert trusted.operator_id == OPERATOR
    assert trusted.key_id == KEY_ID
    assert trusted.registry["auditors"][0]["repositories"] == [REPO]
    assert len(trusted.fingerprint) == 64


@pytest.mark.parametrize("mutation", [
    "missing-registry", "disabled", "uppercase-enabled", "operator-zero", "operator-leading-zero",
    "operator-plus", "bad-key-id", "wrong-key-id", "missing-variable",
])
def test_configuration_is_never_silently_downgraded(mutation):
    supplied = values()
    if mutation == "missing-registry":
        supplied["SOLVERIT_TRUSTED_AUDITORS_JSON"] = ""
    elif mutation == "disabled":
        supplied["SOLVERIT_SOLO_AUDIT_ENABLED"] = "false"
    elif mutation == "uppercase-enabled":
        supplied["SOLVERIT_SOLO_AUDIT_ENABLED"] = "TRUE"
    elif mutation == "operator-zero":
        supplied["SOLVERIT_SOLO_AUDIT_OPERATOR_ID"] = "0"
    elif mutation == "operator-leading-zero":
        supplied["SOLVERIT_SOLO_AUDIT_OPERATOR_ID"] = "0123"
    elif mutation == "operator-plus":
        supplied["SOLVERIT_SOLO_AUDIT_OPERATOR_ID"] = "+123"
    elif mutation == "bad-key-id":
        supplied["SOLVERIT_SOLO_AUDIT_KEY_ID"] = "x"
    elif mutation == "wrong-key-id":
        supplied["SOLVERIT_SOLO_AUDIT_KEY_ID"] = "other-key"
    else:
        del supplied["SOLVERIT_SOLO_AUDIT_ENABLED"]
    with pytest.raises(ValueError):
        contract.parse_trusted_config(supplied, REPO)


@pytest.mark.parametrize("pattern", ["*", "owner/*", "crgasparoto-br/sk?ll", "crgasparoto-br/[s]kill"])
def test_solo_registry_rejects_wildcard_repository_authorization(pattern):
    with pytest.raises(ValueError, match=r"wildcards|exact repository"):
        config(repositories=[pattern])


def test_solo_registry_accepts_multiple_literal_repositories():
    trusted = config(repositories=[REPO, "owner/other"])
    assert trusted.registry["auditors"][0]["repositories"] == [REPO, "owner/other"]


@pytest.mark.parametrize("malformed", ["owner/repo/extra", "owner", "owner/repo with space"])
def test_solo_registry_rejects_malformed_additional_exact_scopes(malformed):
    with pytest.raises(ValueError, match="valid owner/repo literals"):
        config(repositories=[REPO, malformed])


def test_solo_registry_rejects_duplicate_exact_repository_scopes():
    with pytest.raises(ValueError, match="scopes must be unique"):
        config(repositories=[REPO, REPO])


def test_registry_rejects_duplicate_signing_key_ids():
    registry = {"schema_version": 1, "auditors": [
        {"key_id": KEY_ID, "enabled": True, "repositories": [REPO]},
        {"key_id": KEY_ID, "enabled": True, "repositories": [REPO]},
    ]}
    with pytest.raises(ValueError, match="unique"):
        config(registry=registry)


def test_registry_byte_limit_is_checked_before_json_parsing():
    oversized = '{"schema_version":1,"auditors":[],"padding":"' + "x" * contract.MAX_REGISTRY_BYTES + '"}'
    supplied = values()
    supplied["SOLVERIT_TRUSTED_AUDITORS_JSON"] = oversized
    with pytest.raises(ValueError, match="32 KiB"):
        contract.parse_trusted_config(supplied, REPO)


@pytest.mark.parametrize("raw", ['{"schema_version":1,"schema_version":1}', '{"value":NaN}', "[]"])
def test_strict_json_rejects_duplicates_non_json_constants_and_non_objects(raw):
    with pytest.raises(ValueError):
        contract.strict_json(raw, limit=1024)


def test_strict_json_rejects_excessive_nesting():
    raw = '{"x":' * (contract.MAX_JSON_DEPTH + 2) + "0" + "}" * (contract.MAX_JSON_DEPTH + 2)
    with pytest.raises(ValueError, match="nesting"):
        contract.strict_json(raw, limit=4096)


def test_exact_comment_marker_and_json_object_are_accepted():
    payload = json.dumps(report_payload(), separators=(",", ":")).encode()
    raw, parsed = contract.parse_report_comment_body(contract.COMMENT_MARKER + "\n" + payload.decode())
    assert raw == payload
    assert parsed["assurance_mode"] == contract.ASSURANCE_MODE


@pytest.mark.parametrize("body", [
    "narrative\n" + contract.COMMENT_MARKER + "\n{}",
    contract.COMMENT_MARKER + "\n{}\nextra narrative",
    contract.COMMENT_MARKER + "\n{}\n" + contract.COMMENT_MARKER,
    contract.COMMENT_MARKER + "\n{\"a\":1,\"a\":2}",
    contract.COMMENT_MARKER + "\n{\"a\":NaN}",
    contract.COMMENT_MARKER + "\n[]",
])
def test_comment_parser_rejects_narrative_duplicate_marker_or_invalid_json(body):
    with pytest.raises(ValueError):
        contract.parse_report_comment_body(body)


def test_full_comment_limit_is_enforced_before_json_parsing():
    body = contract.COMMENT_MARKER + "\n{}" + " " * contract.MAX_COMMENT_BYTES
    with pytest.raises(ValueError, match="48 KiB"):
        contract.parse_report_comment_body(body)


def test_comment_selection_requires_exactly_one_marker_candidate():
    one = comment()
    assert contract.select_report_comment([one]) == one
    for entries in ([], [one, copy.deepcopy(one)], [comment("quoted " + contract.COMMENT_MARKER)]):
        with pytest.raises(ValueError, match="exactly one"):
            contract.select_report_comment(entries)


@pytest.mark.parametrize("body,expected", [("Closes #175", 175), ("Context\nRefs #175\nMore", 175)])
def test_canonical_issue_reference_requires_one_isolated_line(body, expected):
    assert contract.canonical_issue_reference(body) == expected


@pytest.mark.parametrize("body", ["Closes #175 and #176", "Closes #175\nRefs #176", "Closes #175.\n", "ordinary text #175", None])
def test_ambiguous_or_noncanonical_issue_reference_fails(body):
    with pytest.raises(ValueError):
        contract.canonical_issue_reference(body)


def test_current_target_uses_live_issue_and_authenticated_parent_checked_preview(monkeypatch):
    pr = live_pr()
    issue_body = "## Objetivo\nSigned report target\n"
    monkeypatch.setattr(ghgate.session_runner, "api", lambda path, **_: (
        pr if path.endswith(f"/pulls/{PR}") else {"number": ISSUE, "body": issue_body}
    ))
    calls = []
    monkeypatch.setattr(ghgate, "require_event_merge_preview", lambda *args: calls.append(args) or PREVIEW)
    resolved, observed = ghgate.current_target(REPO, PR)
    assert observed is pr and resolved["issue"] == ISSUE and resolved["pull_request"] == PR
    assert resolved["issue_body_sha256"] == ghgate.sha256(issue_body.encode())
    assert resolved["merge_preview_sha"] == PREVIEW and len(calls) == 1


def test_current_target_rejects_foreign_pr_and_issue_mismatch(monkeypatch):
    pr = live_pr()
    pr["head"]["repo"]["full_name"] = "attacker/fork"
    monkeypatch.setattr(ghgate.session_runner, "api", lambda path, **_: pr)
    with pytest.raises(ValueError, match="cross-repository"):
        ghgate.current_target(REPO, PR)
    pr = live_pr()
    monkeypatch.setattr(ghgate.session_runner, "api", lambda path, **_: pr)
    with pytest.raises(ValueError, match="PR canonical issue changed"):
        ghgate.current_target(REPO, PR, ISSUE + 1)


def test_shared_head_across_open_prs_is_rejected(monkeypatch):
    rows = [live_pr(), live_pr(number=PR + 1)]
    monkeypatch.setattr(ghgate.session_runner, "pages", lambda *args, **kwargs: rows)
    with pytest.raises(ValueError, match="multiple open PRs share one HEAD"):
        ghgate.require_unique_open_pr_head(REPO, PR, HEAD)
    monkeypatch.setattr(ghgate.session_runner, "pages", lambda *args, **kwargs: rows[:1])
    ghgate.require_unique_open_pr_head(REPO, PR, HEAD)


def test_report_comment_binds_user_id_permission_and_immutable_body(monkeypatch):
    trusted, entry = config(), comment()
    monkeypatch.setattr(ghgate.session_runner, "pages", lambda *args, **kwargs: [entry])
    monkeypatch.setattr(ghgate, "is_authorized_reviewer", lambda repo, login, token: login == "gaspa")
    monkeypatch.setattr(ghgate, "github_token", lambda: "token")
    selected, report, raw = ghgate.report_comment(REPO, PR, trusted)
    assert selected["snapshot"]["id"] == entry["id"] and report["pull_request"] == PR and raw


@pytest.mark.parametrize("entry,pattern", [
    (comment(user_id=OPERATOR + 1), "configured solo operator"),
    (comment(user_type="Bot"), "review author identity missing"),
    (comment(updated="2026-11-03T17:01:00Z"), "edited audit comment"),
])
def test_report_comment_rejects_wrong_or_mutable_author(entry, pattern, monkeypatch):
    monkeypatch.setattr(ghgate.session_runner, "pages", lambda *args, **kwargs: [entry])
    monkeypatch.setattr(ghgate, "is_authorized_reviewer", lambda *args: True)
    monkeypatch.setattr(ghgate, "github_token", lambda: "token")
    with pytest.raises(ValueError, match=pattern):
        ghgate.report_comment(REPO, PR, config())


def test_real_ed25519_report_passes_canonical_exact_target_adapter(tmp_path):
    target = identity()
    trusted, entry, raw_report = make_signed_report(tmp_path, target)
    selected = {"comment": entry}
    assert ghgate.validate_signed_report(REPO, target, trusted, selected, raw_report) == hashlib.sha256(raw_report).hexdigest()


def test_evaluate_target_integrates_real_signature_final_reads_and_exact_publication(tmp_path, monkeypatch, capsys):
    issue_body = "## Objetivo\nIntegrated signed-report target\n"
    target = identity(issue_body_sha256=hashlib.sha256(issue_body.encode("utf-8")).hexdigest())
    trusted, entry, _ = make_signed_report(tmp_path, target)
    pr = live_pr(body=f"Closes #{ISSUE}")
    run_id = "12345"
    workflow_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    monkeypatch.setenv("GITHUB_WORKFLOW_SHA", workflow_sha)
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", f"{REPO}/{source.WORKFLOW_PATH}@refs/heads/develop")
    monkeypatch.setenv("GITHUB_REF_PROTECTED", "true")
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_API_URL", API_BASE)

    config_values = values(registry=trusted.registry)
    variable_rows = [{"name": name, "value": value} for name, value in config_values.items()]
    workflow_jobs = [
        ("Structure and tests", ".github/workflows/validate.yml"),
        ("Offline authorization tests", ".github/workflows/github-audit-mcp.yml"),
        ("collect / Require certified semantic handoff (exact SHA)", ".github/workflows/handoff-evidence.yml"),
    ]
    required_checks, runs, jobs = [], {}, {}
    for index, (name, workflow) in enumerate(workflow_jobs, start=1):
        check_id, run_number, job_id, suite_id = 100 + index, 200 + index, 300 + index, 400 + index
        required_checks.append({
            "id": check_id, "name": name, "head_sha": HEAD, "status": "completed",
            "conclusion": "success", "app": {"id": native.APP_ID},
            "details_url": f"https://github.com/{REPO}/actions/runs/{run_number}/job/{job_id}",
            "check_suite": {"id": suite_id},
        })
        runs[run_number] = {
            "path": f"{workflow}@refs/heads/develop", "check_suite_id": suite_id,
            "head_sha": HEAD, "event": "pull_request",
            "pull_requests": [{"number": PR, "base": {"sha": BASE}}],
            "status": "completed", "conclusion": "success",
        }
        jobs[job_id] = {
            "id": job_id, "run_id": run_number, "name": name,
            "check_run_url": f"{API_BASE}/repos/{REPO}/check-runs/{check_id}",
            "status": "completed", "conclusion": "success",
        }

    events_log = []
    check_run = {}

    def api(path, *, method="GET", data=None):
        events_log.append(("session-api", method, path))
        if path == f"/repos/{REPO}":
            return {"default_branch": "main"}
        if path == f"/repos/{REPO}/git/ref/heads/main":
            return {"object": {"sha": "f" * 40}}
        if path == f"/repos/{REPO}/pulls/{PR}":
            return pr
        if path == f"/repos/{REPO}/issues/{ISSUE}":
            return {"number": ISSUE, "body": issue_body}
        if path == f"/repos/{REPO}/issues/comments/{entry['id']}":
            return entry
        if path == f"/repos/{REPO}/check-runs" and method == "POST":
            check_run.update({"id": 900, "name": data["name"], "head_sha": data["head_sha"],
                              "external_id": data["external_id"], "details_url": data["details_url"],
                              "status": data["status"], "conclusion": None,
                              "app": {"id": native.APP_ID}})
            return dict(check_run)
        if path == f"/repos/{REPO}/check-runs/900" and method == "GET":
            return dict(check_run)
        if path == f"/repos/{REPO}/check-runs/900" and method == "PATCH":
            check_run.update(data)
            return dict(check_run)
        raise AssertionError((method, path))

    def pages(repo, path, **kwargs):
        events_log.append(("session-pages", "GET", path))
        if path == "actions/variables":
            return variable_rows
        if path == f"commits/{HEAD}/pulls":
            return [pr]
        if path == f"issues/{PR}/comments":
            return [entry]
        if path == f"commits/{HEAD}/check-runs?filter=all":
            return required_checks
        raise AssertionError(path)

    def content(repo, path, sha):
        return (ROOT.joinpath(path).read_bytes(), "a" * 40)

    def github(path, token):
        events_log.append(("github-api", "GET", path))
        if "/actions/runs/" in path:
            return runs[int(path.rsplit("/", 1)[1])]
        if "/actions/jobs/" in path:
            return jobs[int(path.rsplit("/", 1)[1])]
        if "/contents/" in path:
            relative_path = path.split("/contents/", 1)[1].split("?ref=", 1)[0]
            source_bytes = ROOT.joinpath(relative_path).read_bytes()
            git_blob = b"blob " + str(len(source_bytes)).encode("ascii") + b"\0" + source_bytes
            return {
                "type": "file",
                "sha": hashlib.sha1(git_blob, usedforsecurity=False).hexdigest(),
                "encoding": "base64",
                "content": base64.b64encode(source_bytes).decode("ascii"),
            }
        if path.endswith(f"/pulls/{PR}/reviews?per_page=100&page=1"):
            return []
        if "/collaborators/" in path:
            return {"permission": "admin"}
        raise AssertionError(path)

    def preview_read(path):
        events_log.append(("merge-preview-api", "GET", path))
        if path == f"repos/{REPO}/pulls/{PR}":
            return pr
        if path == f"repos/{REPO}/git/commits/{PREVIEW}":
            return {"sha": PREVIEW, "parents": [{"sha": BASE}, {"sha": HEAD}]}
        raise AssertionError(path)

    monkeypatch.setattr(gate.session_runner, "api", api)
    monkeypatch.setattr(gate.session_runner, "pages", pages)
    monkeypatch.setattr(gate.session_runner, "content", content)
    monkeypatch.setattr(native, "github", github)
    monkeypatch.setattr(preview, "_read_json", preview_read)

    assert gate.evaluate_target(REPO, PR, ISSUE, workflow_sha, run_id) == 0
    assert check_run["status"] == "completed" and check_run["conclusion"] == "success"
    assert check_run["external_id"] == checks.exact_external_id(target, run_id)
    assert check_run["details_url"] == f"https://github.com/{REPO}/actions/runs/{run_id}"
    assert "no third-party human approval claimed" in check_run["output"]["summary"]
    positions = [index for index, event in enumerate(events_log)
                 if event[0] == "session-api" and event[1] == "PATCH"]
    final_jobs = [index for index, event in enumerate(events_log)
                  if event[0] == "github-api" and "/actions/jobs/" in event[2]]
    publication_gets = [index for index, event in enumerate(events_log)
                         if event[0] == "session-api" and event[1] == "GET"
                         and event[2] == f"/repos/{REPO}/check-runs/900"]
    final_permission = max(index for index, event in enumerate(events_log)
                           if event[0] == "github-api" and "/collaborators/" in event[2])
    unique_head_checks = [index for index, event in enumerate(events_log)
                          if event[0] == "session-pages" and event[2] == f"commits/{HEAD}/pulls"]
    assert positions and final_jobs and len(publication_gets) == 2 and len(unique_head_checks) == 3
    assert (publication_gets[0] < max(final_jobs) < final_permission < max(unique_head_checks)
            < publication_gets[1] < positions[-1])
    assert contract.ACCEPTED_TEXT in capsys.readouterr().out


def test_deleted_comment_event_routes_to_live_pr_for_revalidation(monkeypatch):
    event = {"repository": {"full_name": REPO}, "action": "deleted",
             "issue": {"number": PR, "pull_request": {"url": "untrusted locator"}}}
    monkeypatch.setattr(events.session_runner, "api", lambda path: live_pr())
    assert events.resolve_targets(REPO, event, "issue_comment") == [(PR, None)]


@pytest.mark.parametrize(
    "event",
    [
        {"repository": {"full_name": REPO}},
        {"repository": {"full_name": REPO}, "issue": None},
        {"repository": {"full_name": REPO}, "issue": []},
        {"repository": {"full_name": REPO}, "issue": {}},
        {"repository": {"full_name": REPO}, "issue": {"number": True}},
        {"repository": {"full_name": REPO}, "issue": {"number": PR, "pull_request": None}},
        {"repository": {"full_name": REPO}, "issue": {"number": PR, "pull_request": []}},
    ],
)
def test_issue_comment_rejects_missing_or_malformed_issue_payload(event):
    with pytest.raises(ValueError, match="issue-comment"):
        events.resolve_targets(REPO, event, "issue_comment")


def test_issue_comment_on_valid_non_pr_issue_is_no_target():
    event = {"repository": {"full_name": REPO}, "issue": {"number": ISSUE}}
    assert events.resolve_targets(REPO, event, "issue_comment") == []


def _run_main_with_event(tmp_path, monkeypatch, event_name, event):
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
    monkeypatch.setattr(gate, "verify_runtime_context", lambda *args: None)
    args = ["--repo", REPO, "--event", str(event_path), "--workflow-sha", HEAD, "--run-id", "12345"]
    return gate.main(args)


def test_main_blocks_malformed_issue_comment(tmp_path, monkeypatch, capsys):
    event = {"repository": {"full_name": REPO}}
    assert _run_main_with_event(tmp_path, monkeypatch, "issue_comment", event) == 2
    assert "BLOCK: trusted solo gate could not validate event" in capsys.readouterr().err


def test_main_blocks_malformed_issues_pr_marker(tmp_path, monkeypatch, capsys):
    event = {
        "repository": {"full_name": REPO},
        "issue": {"number": PR, "pull_request": {}},
    }
    assert _run_main_with_event(tmp_path, monkeypatch, "issues", event) == 2
    assert "BLOCK: trusted solo gate could not validate event" in capsys.readouterr().err


def test_main_allows_valid_issues_pr_marker_no_target(tmp_path, monkeypatch, capsys):
    pull_url = f"{API_BASE}/repos/{REPO}/pulls/{PR}"
    event = {
        "repository": {"full_name": REPO},
        "issue": {"number": PR, "pull_request": {"url": pull_url}},
    }
    assert _run_main_with_event(tmp_path, monkeypatch, "issues", event) == 0
    assert "No eligible open PR targets" in capsys.readouterr().out


def test_main_allows_valid_non_pr_issue_comment_no_target(tmp_path, monkeypatch, capsys):
    event = {"repository": {"full_name": REPO}, "issue": {"number": ISSUE}}
    assert _run_main_with_event(tmp_path, monkeypatch, "issue_comment", event) == 0
    assert "No eligible open PR targets" in capsys.readouterr().out


@pytest.mark.parametrize(
    "issue",
    [None, [], {}, {"number": True}, {"number": ISSUE, "pull_request": None},
     {"number": ISSUE, "pull_request": []}],
)
def test_issues_event_rejects_missing_or_malformed_issue(issue):
    event = {"repository": {"full_name": REPO}, "issue": issue}
    with pytest.raises(ValueError, match="issue event"):
        events.resolve_targets(REPO, event, "issues")


def test_issues_event_for_valid_pr_issue_is_no_target():
    pull_url = f"{API_BASE}/repos/{REPO}/pulls/{PR}"
    event = {
        "repository": {"full_name": REPO},
        "issue": {"number": PR, "pull_request": {"url": pull_url}},
    }
    assert events.resolve_targets(REPO, event, "issues") == []


def test_issues_event_requires_trusted_api_base(monkeypatch):
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    event = {
        "repository": {"full_name": REPO},
        "issue": {"number": PR, "pull_request": {"url": f"{API_BASE}/repos/{REPO}/pulls/{PR}"}},
    }
    with pytest.raises(ValueError, match="trusted GitHub API base is unavailable"):
        events.resolve_targets(REPO, event, "issues")


@pytest.mark.parametrize(
    "pull_request",
    [
        {},
        {"url": None},
        {"url": f"{API_BASE}/repos/other/repo/pulls/174"},
        {"url": f"{API_BASE}/repos/{REPO}/pulls/{PR + 1}"},
        {"url": f"https://example.net/repos/{REPO}/pulls/{PR}"},
    ],
)
def test_issues_event_rejects_malformed_pr_marker(pull_request):
    event = {
        "repository": {"full_name": REPO},
        "issue": {"number": PR, "pull_request": pull_request},
    }
    with pytest.raises(ValueError, match="issue event pull-request URL is malformed"):
        events.resolve_targets(REPO, event, "issues")


def test_issues_event_with_no_open_prs_is_a_valid_no_target(monkeypatch):
    event = {"repository": {"full_name": REPO}, "issue": {"number": ISSUE}}
    monkeypatch.setattr(events.session_runner, "pages", lambda *args: [])
    assert events.resolve_targets(REPO, event, "issues") == []


@pytest.mark.parametrize("inventory", [None, {}, [None], [{}], [{"number": "bad"}]])
def test_issue_and_push_events_reject_malformed_open_pr_inventory(monkeypatch, inventory):
    monkeypatch.setattr(events.session_runner, "pages", lambda *args: inventory)
    issue_event = {"repository": {"full_name": REPO}, "issue": {"number": ISSUE}}
    push_event = {"repository": {"full_name": REPO}, "ref": "refs/heads/develop"}
    with pytest.raises(ValueError, match="open pull-request"):
        events.resolve_targets(REPO, issue_event, "issues")
    with pytest.raises(ValueError, match="open pull-request"):
        events.resolve_targets(REPO, push_event, "push")


@pytest.mark.parametrize("body", [None, "No canonical issue reference", f"Closes #{ISSUE}\nRefs #{ISSUE + 1}"])
def test_issues_event_rejects_missing_or_ambiguous_pr_issue_reference(monkeypatch, body):
    bad_pr = live_pr()
    bad_pr["body"] = body
    monkeypatch.setattr(events.session_runner, "pages", lambda *args: [bad_pr])
    event = {"repository": {"full_name": REPO}, "issue": {"number": ISSUE}}
    with pytest.raises(ValueError, match=r"PR body|canonical PR-to-issue reference"):
        events.resolve_targets(REPO, event, "issues")


def test_issues_event_routes_only_canonical_matching_pr(monkeypatch):
    matching_pr = live_pr(body=f"Refs #{ISSUE}")
    monkeypatch.setattr(events.session_runner, "pages", lambda *args: [matching_pr])
    monkeypatch.setattr(events.session_runner, "api", lambda path: live_pr(body=f"Refs #{ISSUE}"))
    event = {"repository": {"full_name": REPO}, "issue": {"number": ISSUE}}
    assert events.resolve_targets(REPO, event, "issues") == [(PR, ISSUE)]


def test_issues_event_does_not_route_canonical_link_to_another_issue(monkeypatch):
    unrelated_pr = live_pr(body=f"Closes #{ISSUE + 1}")
    monkeypatch.setattr(events.session_runner, "pages", lambda *args: [unrelated_pr])
    event = {"repository": {"full_name": REPO}, "issue": {"number": ISSUE}}
    assert events.resolve_targets(REPO, event, "issues") == []


def test_push_event_with_empty_open_pr_inventory_is_a_valid_no_target(monkeypatch):
    monkeypatch.setattr(events.session_runner, "pages", lambda *args: [])
    event = {"repository": {"full_name": REPO}, "ref": "refs/heads/develop"}
    assert events.resolve_targets(REPO, event, "push") == []


@pytest.mark.parametrize("ref", [None, "refs/heads/feature", [], {}])
def test_push_event_rejects_unprotected_or_malformed_ref(ref):
    event = {"repository": {"full_name": REPO}, "ref": ref}
    with pytest.raises(ValueError, match="push is outside protected branches"):
        events.resolve_targets(REPO, event, "push")


def _workflow_event(head_repository, pull_requests=None, head_sha=HEAD):
    return {
        "repository": {"full_name": REPO},
        "workflow_run": {
            "event": "pull_request",
            "head_repository": head_repository,
            "pull_requests": pull_requests,
            "head_sha": head_sha,
        },
    }


@pytest.mark.parametrize("head_repository", [None, [], {}, {"full_name": None}, {"full_name": "invalid"}])
def test_workflow_run_rejects_malformed_head_repository(head_repository):
    event = _workflow_event(head_repository, [])
    with pytest.raises(ValueError, match="workflow completion head repository"):
        events.resolve_targets(REPO, event, "workflow_run")


def test_workflow_run_ignores_valid_foreign_repository_without_targets():
    event = _workflow_event({"full_name": "fork-owner/skill"}, [])
    assert events.resolve_targets(REPO, event, "workflow_run") == []


def test_workflow_run_revalidates_linked_target_via_api(monkeypatch):
    event = _workflow_event({"full_name": REPO}, [{"number": PR}])
    monkeypatch.setattr(events.session_runner, "api", lambda path: live_pr())
    assert events.resolve_targets(REPO, event, "workflow_run") == [(PR, None)]


@pytest.mark.parametrize("repository_name", [REPO, "fork-owner/skill"])
@pytest.mark.parametrize("head_sha", [None, "not-a-sha", "A" * 40, "0" * 39])
def test_workflow_run_rejects_malformed_head_sha_before_routing(repository_name, head_sha):
    event = _workflow_event({"full_name": repository_name}, [{"number": PR}], head_sha)
    with pytest.raises(ValueError, match="workflow completion HEAD is malformed"):
        events.resolve_targets(REPO, event, "workflow_run")


@pytest.mark.parametrize("run", [None, [], "malformed", {"event": "push"}])
def test_workflow_run_rejects_missing_or_non_pull_request_run(run):
    event = {"repository": {"full_name": REPO}, "workflow_run": run}
    with pytest.raises(ValueError, match="workflow completion"):
        events.resolve_targets(REPO, event, "workflow_run")


@pytest.mark.parametrize("head_repository", [{"full_name": REPO}, {"full_name": "fork-owner/skill"}])
@pytest.mark.parametrize("links", [None, "unexpected", [{}], [{"number": True}]])
def test_workflow_run_rejects_malformed_pull_request_links(head_repository, links):
    event = _workflow_event(head_repository, links)
    with pytest.raises(ValueError, match="workflow completion"):
        events.resolve_targets(REPO, event, "workflow_run")


@pytest.mark.parametrize(
    "associated",
    [
        None,
        {},
        [None],
        [{"number": PR}],
        [{"number": True, "head": {"repo": {"full_name": REPO}}}],
        [{"number": PR, "head": None}],
        [{"number": PR, "head": {"repo": None}}],
        [{"number": PR, "head": {"repo": {"full_name": None}}}],
    ],
)
def test_workflow_run_rejects_malformed_associated_pull_request_rows(monkeypatch, associated):
    event = _workflow_event({"full_name": REPO}, [])
    monkeypatch.setattr(events.session_runner, "pages", lambda *args: associated)
    with pytest.raises(ValueError, match="workflow-associated PR"):
        events.resolve_targets(REPO, event, "workflow_run")


def test_workflow_run_ignores_valid_foreign_associated_pull_request(monkeypatch):
    event = _workflow_event({"full_name": REPO}, [])
    foreign = {"number": PR, "head": {"repo": {"full_name": "fork-owner/skill"}}}
    monkeypatch.setattr(events.session_runner, "pages", lambda *args: [foreign])
    assert events.resolve_targets(REPO, event, "workflow_run") == []


def test_workflow_run_returns_no_targets_for_valid_empty_association(monkeypatch):
    event = _workflow_event({"full_name": REPO}, [])
    monkeypatch.setattr(events.session_runner, "pages", lambda *args: [])
    assert events.resolve_targets(REPO, event, "workflow_run") == []


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("not-object", "live PR response"),
        ("missing-number", "live PR number"),
        ("invalid-number", "live PR number"),
        ("wrong-number", "response identity"),
        ("state", "live PR state"),
        ("base", "live PR base"),
        ("base-repo", "live PR base repository"),
        ("foreign-base", "base repository differs"),
        ("base-ref", "live PR base ref"),
        ("base-sha", "live PR base SHA"),
        ("draft", "draft/merged flags"),
        ("merged", "draft/merged flags"),
        ("body", "live PR body"),
        ("head", "live PR head"),
        ("head-sha", "live PR head SHA"),
        ("head-ref", "live PR head ref"),
        ("head-repo", "live PR head repository is malformed"),
        ("head-name", "live PR head repository identity"),
    ],
)
def test_authoritative_router_rejects_malformed_live_pr_response(monkeypatch, mutation, expected):
    response = live_pr()
    if mutation == "not-object":
        response = None
    elif mutation == "missing-number":
        del response["number"]
    elif mutation == "invalid-number":
        response["number"] = True
    elif mutation == "wrong-number":
        response["number"] = PR + 1
    elif mutation == "state":
        response["state"] = []
    elif mutation == "base":
        response["base"] = None
    elif mutation == "base-repo":
        response["base"]["repo"] = None
    elif mutation == "foreign-base":
        response["base"]["repo"]["full_name"] = "other-owner/skill"
    elif mutation == "base-ref":
        response["base"]["ref"] = None
    elif mutation == "base-sha":
        response["base"]["sha"] = "not-a-sha"
    elif mutation == "draft":
        response["draft"] = "false"
    elif mutation == "merged":
        response["merged"] = 0
    elif mutation == "body":
        response["body"] = None
    elif mutation == "head":
        response["head"] = None
    elif mutation == "head-sha":
        response["head"]["sha"] = "not-a-sha"
    elif mutation == "head-ref":
        response["head"]["ref"] = None
    elif mutation == "head-repo":
        response["head"]["repo"] = None
    elif mutation == "head-name":
        response["head"]["repo"]["full_name"] = None
    monkeypatch.setattr(events.session_runner, "api", lambda path: response)
    event = {"repository": {"full_name": REPO}, "pull_request": {"number": PR}}
    with pytest.raises(ValueError, match=expected):
        events.resolve_targets(REPO, event, "pull_request_target")


def test_authoritative_router_preserves_closed_and_out_of_scope_no_targets(monkeypatch):
    event = {"repository": {"full_name": REPO}, "pull_request": {"number": PR}}
    closed_pr = live_pr()
    closed_pr["state"] = "closed"
    monkeypatch.setattr(events.session_runner, "api", lambda path: closed_pr)
    assert events.resolve_targets(REPO, event, "pull_request_target") == []
    out_of_scope = live_pr()
    out_of_scope["base"]["ref"] = "release"
    monkeypatch.setattr(events.session_runner, "api", lambda path: out_of_scope)
    assert events.resolve_targets(REPO, event, "pull_request_target") == []


@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_begin_check_creates_only_the_separate_custom_check(monkeypatch, status):
    writes = []
    provisional = checks.provisional_external_id(PR, HEAD, "12345")
    monkeypatch.setattr(checks.session_runner, "pages", lambda *args, **kwargs: [])

    def api(path, *, method="GET", data=None):
        writes.append((path, method, data))
        assert method == "POST"
        return {"id": 71, "name": contract.CHECK_NAME, "head_sha": HEAD,
                "external_id": provisional, "status": status, "conclusion": None,
                "details_url": f"https://github.com/{REPO}/actions/runs/12345",
                "app": {"id": native.APP_ID}}

    monkeypatch.setattr(checks.session_runner, "api", api)
    assert checks.begin_check(REPO, HEAD, PR, "12345") == 71
    assert len(writes) == 1 and writes[0][2]["name"] == contract.CHECK_NAME
    assert writes[0][2]["head_sha"] == HEAD and writes[0][2]["external_id"] == provisional


@pytest.mark.parametrize("status,conclusion", [
    ("queued", "success"), ("in_progress", "failure"),
    ("completed", "failure"), ("completed", "success"), ("skipped", None),
])
def test_begin_check_rejects_nonpending_or_inconsistent_response(monkeypatch, status, conclusion):
    provisional = checks.provisional_external_id(PR, HEAD, "12345")
    monkeypatch.setattr(checks.session_runner, "api", lambda *args, **kwargs: {
        "id": 71, "name": contract.CHECK_NAME, "head_sha": HEAD,
        "external_id": provisional, "details_url": f"https://github.com/{REPO}/actions/runs/12345",
        "status": status, "conclusion": conclusion, "app": {"id": native.APP_ID},
    })
    with pytest.raises(ValueError, match="fail-closed"):
        checks.begin_check(REPO, HEAD, PR, "12345")


def test_candidate_forged_check_with_legitimate_app_is_never_adopted(monkeypatch):
    target_external = checks.provisional_external_id(PR, HEAD, "12345")
    forged = {"id": 70, "name": contract.CHECK_NAME, "head_sha": HEAD,
              "external_id": target_external, "status": "in_progress", "conclusion": None,
              "details_url": f"https://github.com/{REPO}/actions/runs/12345",
              "app": {"id": native.APP_ID}}
    writes = []
    list_calls = []
    monkeypatch.setattr(checks.session_runner, "pages", lambda *args, **kwargs: list_calls.append(forged) or [forged])

    def api(path, *, method="GET", data=None):
        writes.append(method)
        assert method == "POST" and data["external_id"] == target_external
        return {"id": 72, "name": contract.CHECK_NAME, "head_sha": HEAD,
                "external_id": target_external, "status": "in_progress", "conclusion": None,
                "details_url": f"https://github.com/{REPO}/actions/runs/12345",
                "app": {"id": native.APP_ID}}

    monkeypatch.setattr(checks.session_runner, "api", api)
    assert checks.begin_check(REPO, HEAD, PR, "12345") == 72
    assert writes == ["POST"] and list_calls == []


def test_terminal_old_success_is_not_reused_as_new_pending_check(monkeypatch):
    previous = [{"id": 70, "name": contract.CHECK_NAME, "head_sha": HEAD,
                 "external_id": checks.provisional_external_id(PR, HEAD, "12345"),
                 "status": "completed", "conclusion": "success", "app": {"id": native.APP_ID}}]
    calls = []
    provisional = checks.provisional_external_id(PR, HEAD, "12345")
    monkeypatch.setattr(checks.session_runner, "pages", lambda *args, **kwargs: previous)

    def api(path, *, method="GET", data=None):
        calls.append(method)
        assert method == "POST"
        return {"id": 72, "name": contract.CHECK_NAME, "head_sha": HEAD,
                "external_id": provisional, "status": "in_progress", "conclusion": None,
                "details_url": f"https://github.com/{REPO}/actions/runs/12345",
                "app": {"id": native.APP_ID}}

    monkeypatch.setattr(checks.session_runner, "api", api)
    assert checks.begin_check(REPO, HEAD, PR, "12345") == 72
    assert calls == ["POST"]


def test_begin_check_rejects_untrusted_publisher(monkeypatch):
    monkeypatch.setattr(checks.session_runner, "pages", lambda *args, **kwargs: [])
    monkeypatch.setattr(checks.session_runner, "api", lambda *args, **kwargs: {
        "id": 71, "name": contract.CHECK_NAME, "head_sha": HEAD,
        "external_id": checks.provisional_external_id(PR, HEAD, "12345"),
        "details_url": f"https://github.com/{REPO}/actions/runs/12345",
        "status": "in_progress", "conclusion": None, "app": {"id": 7},
    })
    with pytest.raises(ValueError, match="fail-closed"):
        checks.begin_check(REPO, HEAD, PR, "12345")


def test_success_publication_requires_terminal_identity_bound_run(monkeypatch):
    provisional = checks.provisional_external_id(PR, HEAD, "12345")
    exact = checks.exact_external_id(identity(), "12345")
    responses = iter([
        {"id": 71, "name": contract.CHECK_NAME, "head_sha": HEAD,
         "external_id": provisional, "details_url": f"https://github.com/{REPO}/actions/runs/12345",
         "status": "in_progress", "conclusion": None,
         "app": {"id": native.APP_ID}},
        {"id": 71, "name": contract.CHECK_NAME, "head_sha": HEAD,
         "external_id": provisional, "status": "in_progress", "conclusion": None,
         "details_url": f"https://github.com/{REPO}/actions/runs/12345",
         "app": {"id": native.APP_ID}},
        {"id": 71, "name": contract.CHECK_NAME, "head_sha": HEAD,
         "external_id": exact, "status": "in_progress", "conclusion": "success",
         "details_url": f"https://github.com/{REPO}/actions/runs/12345",
         "app": {"id": native.APP_ID}},
    ])
    monkeypatch.setattr(checks.session_runner, "api", lambda *args, **kwargs: next(responses))
    with pytest.raises(ValueError, match="terminal"):
        checks.publish_check(REPO, HEAD, PR, 71, "12345", "success",
                             {"head_sha": HEAD, "pull_request": PR}, identity=identity(),
                             before_patch=lambda: None)


@pytest.mark.parametrize("mutation", ["external_id", "details_url", "terminal"])
def test_publish_refuses_check_run_metadata_drift_before_patch(monkeypatch, mutation):
    current = {"id": 71, "name": contract.CHECK_NAME, "head_sha": HEAD,
               "external_id": checks.provisional_external_id(PR, HEAD, "12345"),
               "details_url": f"https://github.com/{REPO}/actions/runs/12345",
               "status": "in_progress", "app": {"id": native.APP_ID}}
    if mutation == "external_id":
        current["external_id"] = "forged-target"
    elif mutation == "details_url":
        current["details_url"] = "https://github.com/attacker/repository/actions/runs/12345"
    else:
        current.update({"status": "completed", "conclusion": "success"})
    calls = []

    def api(path, *, method="GET", data=None):
        calls.append(method)
        if method == "GET":
            return current
        raise AssertionError("a mutated Check Run must not be patched")

    monkeypatch.setattr(checks.session_runner, "api", api)
    with pytest.raises(ValueError, match="belongs to another PR/target or publisher"):
        checks.publish_check(REPO, HEAD, PR, 71, "12345", "success",
                             {"head_sha": HEAD, "pull_request": PR}, identity=identity(),
                             before_patch=lambda: None)
    assert calls == ["GET"]


def test_success_publication_uses_explicit_solo_assurance_and_exact_external_target(monkeypatch):
    posted = {}
    exact = checks.exact_external_id(identity(), "12345")
    current = {"id": 72, "name": contract.CHECK_NAME, "head_sha": HEAD,
               "external_id": checks.provisional_external_id(PR, HEAD, "12345"),
               "details_url": f"https://github.com/{REPO}/actions/runs/12345",
               "status": "in_progress", "app": {"id": native.APP_ID}}
    calls = []

    def api(path, *, method="GET", data=None):
        calls.append(method)
        if method == "GET":
            return dict(current)
        posted.update(data)
        current.update(data)
        return dict(current)

    monkeypatch.setattr(checks.session_runner, "api", api)
    checks.publish_check(REPO, HEAD, PR, 72, "12345", "success",
                         {"head_sha": HEAD, "pull_request": PR}, identity=identity(),
                         before_patch=lambda: calls.append("revalidated"))
    assert posted["external_id"] == exact
    assert posted["output"]["title"] == contract.ACCEPTED_TEXT
    assert posted["output"]["summary"] == contract.ACCEPTED_TEXT
    assert calls == ["GET", "revalidated", "GET", "PATCH"]


def test_success_publication_requires_callback_before_any_api_write(monkeypatch):
    calls = []
    monkeypatch.setattr(checks.session_runner, "api", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="last-moment authority revalidation"):
        checks.publish_check(REPO, HEAD, PR, 72, "12345", "success",
                             {"head_sha": HEAD, "pull_request": PR}, identity=identity())
    assert calls == []


def test_publication_without_current_run_check_id_never_creates_replacement(monkeypatch):
    calls = []
    monkeypatch.setattr(checks.session_runner, "api", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="refusing to create a replacement"):
        checks.publish_check(REPO, HEAD, PR, None, "12345", "failure", {"head_sha": HEAD})
    assert calls == []


def test_required_evidence_vetoes_outstanding_request_changes(monkeypatch):
    check_rows = [
        {"id": 1, "name": "Structure and tests", "head_sha": HEAD, "app": {"id": native.APP_ID}},
        {"id": 2, "name": "Offline authorization tests", "head_sha": HEAD, "app": {"id": native.APP_ID}},
        {"id": 3, "name": "collect / Require certified semantic handoff (exact SHA)",
         "head_sha": HEAD, "app": {"id": native.APP_ID}},
    ]
    monkeypatch.setattr(checks.session_runner, "pages", lambda *args, field=None, **kwargs: check_rows)
    monkeypatch.setattr(checks, "github_token", lambda: "token")
    monkeypatch.setattr(checks, "required_checks_green", lambda *args, **kwargs: None)
    monkeypatch.setattr(checks, "page_all", lambda *args, **kwargs: [
        {"id": 55, "user": {"login": "reviewer"}, "state": "CHANGES_REQUESTED",
         "submitted_at": "2026-11-03T17:00:00Z"}
    ])
    with pytest.raises(ValueError, match="request for changes"):
        checks.required_evidence(REPO, identity())


def _success_fixture(monkeypatch, config_values=None):
    trusted = config_values or contract.TrustedConfig(
        operator_id=OPERATOR, key_id=KEY_ID, registry_raw=b"{}", registry={}, fingerprint="f" * 64
    )
    selected = {"comment": {"user": {"id": OPERATOR, "login": "gaspa", "type": "User"}},
                "snapshot": {"id": 42, "body": "signed"}, "raw_report": b"signed-json"}
    signed = {"issue": ISSUE, "pull_request": PR, "operator_github_id": OPERATOR}
    pr = live_pr()
    publications = []
    monkeypatch.setattr(gate.session_runner, "api", lambda path, **kwargs: pr)
    monkeypatch.setattr(gate, "begin_check", lambda *args: 80)
    monkeypatch.setattr(gate, "current_target", lambda repo, number, issue=None, pr=None: (identity(), live_pr()))
    monkeypatch.setattr(gate, "require_unique_open_pr_head", lambda *args: None)
    monkeypatch.setattr(gate, "load_config", lambda repo: trusted)
    source_state = {"base_sha": BASE, "workflow_sha": "e" * 40,
                    "default_branch_sha": "f" * 40, "local_files_sha256": "a" * 64}
    monkeypatch.setattr(gate, "verify_execution_source", lambda *args: source_state)
    monkeypatch.setattr(gate, "report_comment", lambda *args: (selected, signed, b"signed-json"))
    monkeypatch.setattr(gate, "validate_signed_report", lambda *args: "b" * 64)
    monkeypatch.setattr(gate, "required_evidence", lambda *args: [1, 2, 3])
    monkeypatch.setattr(gate, "_recheck_comment", lambda *args: None)
    monkeypatch.setattr(gate, "github_token", lambda: "token")
    monkeypatch.setattr(gate, "is_authorized_reviewer", lambda *args: True)
    monkeypatch.setattr(gate, "revalidate_execution_source", lambda *args: None)

    def publish(*args, **kwargs):
        if args[5] == "success" and callable(kwargs.get("before_patch")):
            kwargs["before_patch"]()
        publications.append((args, kwargs))

    monkeypatch.setattr(gate, "publish_check", publish)
    return publications, trusted, selected, source_state


def test_complete_target_evaluation_publishes_only_new_exact_head_check(monkeypatch, capsys):
    publications, _, _, _ = _success_fixture(monkeypatch)
    assert gate.evaluate_target(REPO, PR, ISSUE, "e" * 40, "12345") == 0
    args, kwargs = publications[0]
    assert args[1:6] == (HEAD, PR, 80, "12345", "success")
    assert args[6]["third_party_human_approval_claimed"] is False
    assert kwargs["identity"] == identity()
    assert contract.CHECK_NAME == "Verify solo audit attestation (exact SHA)"
    assert contract.ACCEPTED_TEXT in capsys.readouterr().out


@pytest.mark.parametrize("mutation", ["target", "config", "comment", "permission", "checks", "source", "shared-head"])
def test_drift_during_final_evidence_collection_prevents_success_patch(monkeypatch, mutation, capsys):
    publications, _, selected, _ = _success_fixture(monkeypatch)
    original_current = lambda *args, **kwargs: (identity(), live_pr())
    monkeypatch.setattr(gate, "current_target", original_current)
    evidence_calls = 0

    def evidence(*args):
        nonlocal evidence_calls
        evidence_calls += 1
        if evidence_calls == 3:
            if mutation == "target":
                monkeypatch.setattr(gate, "current_target",
                                    lambda *a, **k: (identity(issue_body_sha256="0" * 64), live_pr()))
            elif mutation == "config":
                monkeypatch.setattr(gate, "load_config",
                                    lambda _: contract.TrustedConfig(OPERATOR, KEY_ID, b"{}", {}, "0" * 64))
            elif mutation == "comment":
                changed = {**selected, "snapshot": {"id": 42, "body": "edited while collecting"}}
                monkeypatch.setattr(gate, "report_comment",
                                    lambda *a: (changed, {"issue": ISSUE, "pull_request": PR}, b"changed"))
            elif mutation == "permission":
                monkeypatch.setattr(gate, "is_authorized_reviewer", lambda *a: False)
            elif mutation == "checks":
                return [1, 2, 4]
            elif mutation == "shared-head":
                monkeypatch.setattr(gate, "require_unique_open_pr_head",
                                    lambda *a: (_ for _ in ()).throw(ValueError("shared HEAD appeared")))
            else:
                monkeypatch.setattr(gate, "revalidate_execution_source",
                                    lambda *a: (_ for _ in ()).throw(ValueError("source drift")))
        return [1, 2, 3]

    monkeypatch.setattr(gate, "required_evidence", evidence)
    assert gate.evaluate_target(REPO, PR, ISSUE, "e" * 40, "12345") == 2
    assert evidence_calls == 3
    assert len(publications) == 1 and publications[0][0][5] == "failure"
    assert not any(args[5] == "success" for args, _ in publications)
    assert "BLOCK:" in capsys.readouterr().err


@pytest.mark.parametrize("mutation", ["target", "config", "comment", "permission", "checks", "source"])
def test_final_revalidation_rejects_authority_drift(monkeypatch, mutation):
    publications, trusted, selected, source_state = _success_fixture(monkeypatch)
    if mutation == "target":
        monkeypatch.setattr(gate, "current_target", lambda *args, **kwargs: (identity(head_sha="e" * 40), live_pr()))
    elif mutation == "config":
        monkeypatch.setattr(gate, "load_config", lambda _: contract.TrustedConfig(OPERATOR, KEY_ID, b"{}", {}, "0" * 64))
    elif mutation == "comment":
        changed = {**selected, "snapshot": {"id": 42, "body": "edited"}}
        monkeypatch.setattr(gate, "report_comment", lambda *args: (changed, {"issue": ISSUE, "pull_request": PR}, b"changed"))
    elif mutation == "permission":
        monkeypatch.setattr(gate, "is_authorized_reviewer", lambda *args: False)
    elif mutation == "checks":
        monkeypatch.setattr(gate, "required_evidence", lambda *args: [1, 2, 4])
    else:
        monkeypatch.setattr(gate, "revalidate_execution_source", lambda *args: (_ for _ in ()).throw(ValueError("source drift")))
    with pytest.raises(ValueError):
        gate.final_revalidation(REPO, PR, identity(), trusted, selected, source_state, [1, 2, 3])
    assert publications == []


def test_configuration_drift_between_initial_and_final_reads_publishes_failure(monkeypatch, capsys):
    first = contract.TrustedConfig(OPERATOR, KEY_ID, b"{}", {}, "f" * 64)
    second = contract.TrustedConfig(OPERATOR, KEY_ID, b"{}", {}, "0" * 64)
    publications, _, _, _ = _success_fixture(monkeypatch, first)
    configs = iter([first, second])
    monkeypatch.setattr(gate, "load_config", lambda repo: next(configs))
    assert gate.evaluate_target(REPO, PR, ISSUE, "e" * 40, "12345") == 2
    args, _ = publications[-1]
    assert args[5] == "failure" and args[6]["blocker"] == "ValueError"
    assert "BLOCK:" in capsys.readouterr().err


def test_execution_source_requires_exact_local_workflow_sha_and_base_files(monkeypatch):
    workflow_sha = "e" * 40
    monkeypatch.setenv("GITHUB_WORKFLOW_SHA", workflow_sha)
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", f"{REPO}/{source.WORKFLOW_PATH}@refs/heads/main")
    monkeypatch.setenv("GITHUB_REF_PROTECTED", "true")
    monkeypatch.setattr(source.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 0, stdout=(workflow_sha + "\n").encode(), stderr=b""))
    monkeypatch.setattr(session_runner, "content", lambda repo, path, sha: ((source.ROOT / path).read_bytes(), "a" * 40))
    monkeypatch.setattr(source, "default_branch_head", lambda repo: "f" * 40)
    state = source.verify_execution_source(REPO, BASE, workflow_sha)
    assert state["workflow_sha"] == workflow_sha and len(state["local_files_sha256"]) == 64
    source.revalidate_execution_source(REPO, BASE, state)
    assert "entregar-issue/scripts/validate_finding_completion.py" in source.TRUSTED_PATHS
    assert "auditar-issue/requirements.lock.txt" in source.TRUSTED_PATHS


def test_execution_source_rejects_dependency_drift_or_unprotected_workflow(monkeypatch):
    workflow_sha = "e" * 40
    monkeypatch.setenv("GITHUB_WORKFLOW_SHA", workflow_sha)
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", f"{REPO}/{source.WORKFLOW_PATH}@refs/heads/main")
    monkeypatch.setenv("GITHUB_REF_PROTECTED", "true")
    monkeypatch.setattr(source.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 0, stdout=(workflow_sha + "\n").encode(), stderr=b""))
    monkeypatch.setattr(session_runner, "content", lambda *_: (b"different trusted base file", "a" * 40))
    with pytest.raises(ValueError, match="differs from protected PR base"):
        source.verify_execution_source(REPO, BASE, workflow_sha)
    monkeypatch.setenv("GITHUB_REF_PROTECTED", "false")
    with pytest.raises(ValueError, match="ref as protected"):
        source.verify_execution_source(REPO, BASE, workflow_sha)


def test_runtime_context_requires_protected_ref_and_restricts_review_ref(monkeypatch):
    workflow_sha = "e" * 40
    monkeypatch.setenv("GITHUB_REF_PROTECTED", "true")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/develop")
    gate.verify_runtime_context(REPO, workflow_sha, "12345", "issue_comment")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/174/merge")
    with pytest.raises(ValueError, match="protected branch"):
        gate.verify_runtime_context(REPO, workflow_sha, "12345", "issue_comment")
    gate.verify_runtime_context(REPO, workflow_sha, "12345", "pull_request_review")
    monkeypatch.setenv("GITHUB_REF_PROTECTED", "false")
    with pytest.raises(ValueError, match="ref as protected"):
        gate.verify_runtime_context(REPO, workflow_sha, "12345", "pull_request_review")
