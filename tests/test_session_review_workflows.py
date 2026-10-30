"""Trust-boundary and real shell controls for web-only review entrypoints."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_session_review_runner import runner

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ("session-review.yml", "prepare-neutral-audit-packet.yml")


def workflow(name):
    # BaseLoader keeps the GitHub `on` key as text instead of YAML 1.1 boolean.
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("name", WORKFLOWS)
def test_candidate_selected_refs_cannot_start_review_workflows(name):
    config = workflow(name)
    triggers = config["on"]
    # GitHub chooses default/base source for these events. Dispatch, workflow_call
    # and pull_request can select candidate source and must never enter this set.
    assert set(triggers) <= {"issue_comment", "issues", "workflow_run", "push", "pull_request_target"}
    assert not {"workflow_dispatch", "workflow_call", "pull_request"}.intersection(triggers)
    for event in ("push", "pull_request_target"):
        if event in triggers:
            assert set(triggers[event]["branches"]) == {"develop", "main"}
    job = next(iter(config["jobs"].values()))
    assert "(github.ref == 'refs/heads/develop' || github.ref == 'refs/heads/main') &&" in job["if"]
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in job["if"]
    checkouts = [step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 1
    assert checkouts[0]["with"] == {"ref": "${{ github.workflow_sha }}", "persist-credentials": "false"}
    assert job["steps"].index(checkouts[0]) < next(i for i, step in enumerate(job["steps"]) if "run" in step)
    assert config["permissions"]["checks"] == ("write" if name == "session-review.yml" else "read")


@pytest.mark.parametrize("name", WORKFLOWS)
def test_trusted_review_jobs_supply_same_authenticated_token_to_partial_handoff_reader(name):
    config = workflow(name)
    job = next(iter(config["jobs"].values()))
    step = next(item for item in job["steps"] if "run" in item)
    # The trusted packet and session-review readers both call the partial
    # handoff validator, which requires GITHUB_TOKEN for a live parent read.
    # This is an alias of the existing job-scoped Actions token, not a new
    # credential, an untrusted PR value or an authorization bypass.
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert step["env"]["GITHUB_TOKEN"] == step["env"]["GH_TOKEN"]
    assert "GITHUB_API_URL" not in step["env"]  # Runner-owned endpoint.
    assert "GITHUB_TOKEN" not in job.get("env", {})  # Scoped to trusted step.


def test_packet_request_requires_certified_same_repo_run_or_explicit_pr_comment():
    config = workflow("prepare-neutral-audit-packet.yml")
    assert config["on"]["workflow_run"] == {
        "workflows": ["Collect and certify exact-SHA handoff"], "types": ["completed"]}
    assert config["on"]["issue_comment"] == {"types": ["created"]}
    condition = config["jobs"]["packet"]["if"]
    for required in (
        "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)",
        "github.event.workflow_run.event == 'pull_request'",
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "github.event.issue.pull_request",
        "github.event.comment.body == '/solverit-audit-packet'",
    ):
        assert required in condition
    assert set(config["permissions"].values()) == {"read"}


@pytest.mark.parametrize("targets,codes,expected", [
    ([[10, 9], [11, 8]], [0, 0], 0),
    ([[10, 9]], [2], 2),
    ([], [], 1),
], ids=["all-live-targets", "certificate-failure", "no-eligible-target"])
def test_packet_shell_routes_live_targets_and_propagates_rejection(tmp_path, targets, codes, expected):
    job = workflow("prepare-neutral-audit-packet.yml")["jobs"]["packet"]
    step = next(item for item in job["steps"] if "run" in item)
    assert "${{" not in step["run"]  # Event fields are data, never generated shell/code.
    trusted = tmp_path / "trusted"
    scripts = trusted / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "verify_session_review.py").write_text(
        "import json, os\n"
        "from pathlib import Path\n"
        "def resolve_targets(repo, event):\n"
        "    assert repo == event['repository']['full_name']\n"
        "    return event['test_targets']\n"
        "def evaluate(repo, number, issue, packet_out):\n"
        "    assert packet_out.name == 'review-packet.json'\n"
        "    packet_out.parent.mkdir(parents=True, exist_ok=True)\n"
        "    packet_out.write_text(json.dumps({'repository':repo,'pull_request':number,'issue':issue}))\n"
        "    return json.loads(os.environ['TEST_CODES'])[str(number)]\n"
    )
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps({
        "repository": {"full_name": "owner/repo"}, "test_targets": targets,
        "comment": {"body": "$(touch injected); python candidate/scripts/verify_session_review.py"},
        "inputs": {"ref": "candidate", "pull_request": "$(touch injected)"},
    }))
    packets = tmp_path / "packets"
    environment = os.environ.copy()
    environment.update(REPOSITORY="owner/repo", GITHUB_EVENT_PATH=str(event_path),
                       PACKET_ROOT=str(packets), TEST_CODES=json.dumps(dict(zip((str(x[0]) for x in targets), codes, strict=True))))
    completed = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=trusted, env=environment,
                               capture_output=True, text=True, check=False, timeout=15)
    assert completed.returncode == expected, completed.stderr
    assert not (trusted / "injected").exists()
    observed = [json.loads((packets / f"pr-{number}" / "review-packet.json").read_text()) for number, _ in targets]
    assert observed == [{"repository": "owner/repo", "pull_request": number, "issue": issue} for number, issue in targets]

def test_completed_check_that_cannot_reopen_creates_new_pending_check(monkeypatch):
    sha = "a" * 40
    previous = [{"id": 88, "head_sha": sha, "name": runner.CHECK_NAME,
                 "status": "completed", "conclusion": "failure"}]
    writes = []

    def api(path, *, method="GET", data=None):
        writes.append((method, path, data))
        if method == "PATCH":
            return dict(previous[0])  # GitHub preserved the terminal failure state.
        if method == "POST":
            return {"id": 89, "head_sha": sha, "name": runner.CHECK_NAME,
                    "status": "in_progress"}
        raise AssertionError("unexpected GitHub request")

    monkeypatch.setattr(runner, "api", api)
    assert runner.begin_check("owner/repo", sha, {"minimum_comment_id": 100}, previous) == 89
    assert [method for method, _, _ in writes] == ["PATCH", "POST"]
    assert writes[1][2]["head_sha"] == sha
    assert "minimum_comment_id" in writes[1][2]["output"]["text"]


@pytest.mark.parametrize("mutation", ["head_sha", "id", "name"])
def test_reopen_response_identity_drift_is_not_recovered_by_new_check(monkeypatch, mutation):
    sha = "a" * 40
    previous = [{"id": 88, "head_sha": sha, "name": runner.CHECK_NAME,
                 "status": "completed", "conclusion": "failure"}]
    changed = dict(previous[0])
    changed[mutation] = "b" * 40 if mutation == "head_sha" else (99 if mutation == "id" else "other")
    writes = []

    def api(path, *, method="GET", data=None):
        writes.append(method)
        assert method == "PATCH"
        return changed

    monkeypatch.setattr(runner, "api", api)
    with pytest.raises(ValueError, match="existing check identity changed"):
        runner.begin_check("owner/repo", sha, {}, previous)
    assert writes == ["PATCH"]


@pytest.mark.parametrize(("status", "conclusion"), [
    ("queued", None),
    ("in_progress", None),
    ("completed", "failure"),
])
def test_begin_check_accepts_only_non_authorizing_github_states(monkeypatch, status, conclusion):
    head = "a" * 40
    previous = [{"id": 11, "head_sha": head, "name": runner.CHECK_NAME,
                 "status": "completed", "conclusion": "failure"}]
    calls = []

    def api(path, *, method="GET", data=None):
        calls.append(method)
        if method == "PATCH":
            return dict(previous[0])
        if method == "POST":
            return {"id": 12, "name": runner.CHECK_NAME, "head_sha": head,
                    "status": status, "conclusion": conclusion}
        raise AssertionError("unexpected call")

    monkeypatch.setattr(runner, "api", api)
    assert runner.begin_check("owner/repo", head, {}, previous) == 12
    assert calls == ["PATCH", "POST"]


@pytest.mark.parametrize(("status", "conclusion"), [
    ("completed", "success"),
    ("completed", "neutral"),
    ("completed", "skipped"),
    ("completed", None),
    ("in_progress", "success"),
    ("queued", "success"),
    ("in_progress", "failure"),
    ("waiting", None),
])
def test_begin_check_rejects_states_that_could_bypass_review(monkeypatch, status, conclusion):
    head = "a" * 40

    def api(path, *, method="GET", data=None):
        assert method == "POST"
        return {"id": 12, "name": runner.CHECK_NAME, "head_sha": head,
                "status": status, "conclusion": conclusion}

    monkeypatch.setattr(runner, "api", api)
    with pytest.raises(ValueError, match="fail-closed state not confirmed"):
        runner.begin_check("owner/repo", head, {}, [])


def _trusted_publisher_for_routing_tests():
    from importlib import import_module
    return import_module("entregar-issue.tests.test_publish_actions_handoff").publisher


@pytest.mark.parametrize("mode,expected", [("enabled", True), ("disabled", False)])
def test_session_routing_requires_policy_bytes_on_trusted_default_and_base(tmp_path, monkeypatch, mode, expected):
    publisher = _trusted_publisher_for_routing_tests()
    from base64 import b64encode
    local = tmp_path / ".github/session-review-policy.json"
    local.parent.mkdir()
    real = json.loads((ROOT / ".github/session-review-policy.json").read_text())
    real["mode"] = mode
    real["operators"] = real["operators"] if expected else []
    raw = json.dumps(real).encode()
    local.write_bytes(raw)
    monkeypatch.setattr(publisher, "SCRIPT_ROOT", tmp_path / "entregar-issue/scripts")
    queried = []

    def api(repo, endpoint):
        queried.append(endpoint)
        return {"type": "file", "encoding": "base64", "content": b64encode(raw).decode()}

    monkeypatch.setattr(publisher, "api_get", api)
    assert publisher.session_mode_active("owner/repo", "a" * 40) is expected
    assert queried == ["contents/.github/session-review-policy.json?ref=" + "a" * 40]


@pytest.mark.parametrize("tamper", ["different-base", "invalid-operator", "missing-file", "invalid-ref"])
def test_session_routing_refuses_policy_drift_and_invalid_authority(tmp_path, monkeypatch, tamper):
    publisher = _trusted_publisher_for_routing_tests()
    from base64 import b64encode
    local = tmp_path / ".github/session-review-policy.json"
    local.parent.mkdir()
    policy = json.loads((ROOT / ".github/session-review-policy.json").read_text())
    local.write_text(json.dumps(policy))
    monkeypatch.setattr(publisher, "SCRIPT_ROOT", tmp_path / "entregar-issue/scripts")
    if tamper == "invalid-ref":
        with pytest.raises(ValueError, match="protected-base SHA"):
            publisher.session_mode_active("owner/repo", "not-a-commit")
        return
    if tamper == "missing-file":
        local.unlink()
    if tamper == "invalid-operator":
        policy["operators"] = [{"id": 0, "login": "invalid"}]
        local.write_text(json.dumps(policy))
    candidate = json.dumps(policy).encode()
    if tamper == "different-base":
        candidate += b" "
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "type": "file", "encoding": "base64", "content": b64encode(candidate).decode()})
    with pytest.raises(ValueError, match=r"differs|policy is missing|operator identity"):
        publisher.session_mode_active("owner/repo", "a" * 40)


def test_session_routing_preserves_legacy_when_policy_is_absent_on_both_sides(tmp_path, monkeypatch):
    publisher = _trusted_publisher_for_routing_tests()
    from urllib.error import HTTPError
    monkeypatch.setattr(publisher, "SCRIPT_ROOT", tmp_path / "entregar-issue/scripts")
    def missing(*_):
        raise HTTPError("https://example.invalid", 404, "Not Found", None, None)
    monkeypatch.setattr(publisher, "api_get", missing)
    assert publisher.session_mode_active("owner/repo", "a" * 40) is False


def test_session_routing_never_silently_downgrades_policy_missing_from_base(tmp_path, monkeypatch):
    publisher = _trusted_publisher_for_routing_tests()
    from urllib.error import HTTPError
    policy = tmp_path / ".github/session-review-policy.json"
    policy.parent.mkdir()
    policy.write_text((ROOT / ".github/session-review-policy.json").read_text())
    monkeypatch.setattr(publisher, "SCRIPT_ROOT", tmp_path / "entregar-issue/scripts")
    def missing(*_):
        raise HTTPError("https://example.invalid", 404, "Not Found", None, None)
    monkeypatch.setattr(publisher, "api_get", missing)
    with pytest.raises(ValueError, match="protected-base session policy unavailable"):
        publisher.session_mode_active("owner/repo", "a" * 40)
