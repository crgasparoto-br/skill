"""Fail-closed checks for GitHub-hosted handoff evidence preparation."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepare_actions_handoff.py"
spec = importlib.util.spec_from_file_location("prepare_actions_handoff", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
HEAD = "a" * 40
BASE = "b" * 40


def event(*, title="Issue #112: test policy", body="Related to Issue #112",
          head=HEAD, fork=False, base="develop"):
    return {"repository": {"full_name": "team/skill"}, "pull_request": {
        "number": 113, "title": title, "body": body,
        "head": {"sha": head, "repo": {"full_name": "other/fork" if fork else "team/skill"}},
        "base": {"sha": BASE, "ref": base}}}


def test_resolves_one_issue_and_parenthesized_pr_title(tmp_path):
    p = tmp_path / "event.json"
    p.write_text(json.dumps(event()))
    assert mod.read_event(p) == ("team/skill", 113, 112, HEAD, BASE)
    p.write_text(json.dumps(event(title="feat: governance (#112)", body="")))
    assert mod.read_event(p)[2] == 112
    p.write_text(json.dumps(event(title="Issue #112", body="Issue #77")))
    with pytest.raises(ValueError, match="exactly one"):
        mod.read_event(p)


def test_primary_title_issue_allows_related_issue_mentions_in_description(tmp_path):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event(
        title="fix: strengthen semantic certification (#112)",
        body="Issue #112 is the delivery target. Related branch-ruleset Issue #119 stays open.",
    )))
    assert mod.read_event(path)[2] == 112


def test_primary_title_issue_rejects_conflicting_closing_reference(tmp_path):
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event(
        title="fix: strengthen semantic certification (#112)",
        body="Related Issue #119. Fixes #119.",
    )))
    with pytest.raises(ValueError, match="closing reference conflicts"):
        mod.read_event(path)


@pytest.mark.parametrize("change,expected", [
    ({"fork": True}, "forked"),
    ({"head": "short"}, "exact SHA"),
    ({"base": "main"}, "base ref"),
    ({"title": "test", "body": ""}, "exactly one"),
])
def test_untrusted_or_ambiguous_metadata_fails_closed(tmp_path, change, expected):
    p = tmp_path / "event.json"
    p.write_text(json.dumps(event(**change)))
    with pytest.raises(ValueError, match=expected):
        mod.read_event(p)


def test_actual_git_sha_must_match(tmp_path):
    with (
        patch.object(mod.subprocess, "run", return_value=SimpleNamespace(stdout=BASE + "\n")),
        pytest.raises(ValueError, match="differs"),
    ):
        mod.check_checkout(tmp_path, HEAD)


def test_prepare_preserves_pending_and_never_builds_certificate(tmp_path, monkeypatch):
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps(event()))
    monkeypatch.setenv("GITHUB_TOKEN", "dummy")
    monkeypatch.setattr(mod, "issue_body", lambda *a: "## Escopo\n- Executar teste negativo.\n")
    monkeypatch.setattr(mod, "check_checkout", lambda *a: None)

    def fake_script(script, *args):
        path = Path(args[args.index("--out") + 1])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"status": "pending", "script": script}))

    monkeypatch.setattr(mod, "run_script", fake_script)
    out = tmp_path / "out"
    mod.prepare(SimpleNamespace(event=ev, root=tmp_path, out=out, base_ref="develop"))
    status = json.loads((out / "handoff-preflight.json").read_text())
    closure = json.loads((out / ".audit/entregar-issue/requirement-closure.json").read_text())
    assert status["status"] == "blocked"
    assert status["identity"]["material_head_sha"] == HEAD
    assert "handoff-certificate" in status["unverified"]
    assert closure["status"] == "pending"
    assert not (out / ".audit/entregar-issue/handoff-ready.json").exists()


def test_test_execution_records_real_digest_but_not_semantic_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "check_checkout", lambda *a: None)
    out = tmp_path / "out"
    out.mkdir()
    (out / "handoff-preflight.json").write_text(json.dumps({"identity": {"material_head_sha": HEAD}}))
    (out / "pytest-exact-head.log").write_text("1 passed\n")
    mod.record_tests(SimpleNamespace(out=out, root=tmp_path, exit_code=0, test_command="python -m pytest"))
    facts = json.loads((out / "test-execution-facts.json").read_text())
    assert facts["subject_sha"] == HEAD
    assert facts["verification"] == "passed"
    assert facts["semantic_control_mapping"] == "UNKNOWN"
    assert len(facts["execution"]["log_sha256"]) == 64
    with pytest.raises(ValueError, match="missing exact exit"):
        mod.record_tests(SimpleNamespace(out=out, root=tmp_path, exit_code=-1, test_command="python -m pytest"))

def _certification_fixture(tmp_path, monkeypatch):
    import hashlib

    monkeypatch.setattr(mod, "check_checkout", lambda *a: None)
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps(event(title="feat: governance (#112)", body="")))
    out = tmp_path / "out"
    audit = out / ".audit" / "entregar-issue"
    audit.mkdir(parents=True)
    (out / "handoff-preflight.json").write_text(json.dumps({"identity": {
        "repository": "team/skill", "issue_number": 112, "pull_request_number": 113,
        "material_head_sha": HEAD, "base_sha": BASE,
    }}))
    log = out / "pytest-exact-head.log"
    log.write_bytes(b"test facts from exact SHA")
    (out / "pytest-exact-head.xml").write_text("<testsuite/>")
    (out / "test-execution-facts.json").write_text(json.dumps({
        "subject_sha": HEAD,
        "execution": {"exit_code": 0, "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()},
    }))
    args = SimpleNamespace(event=ev, out=out, root=tmp_path, base_ref="develop")
    return args, audit


def test_certification_missing_semantic_inputs_fails_closed(tmp_path, monkeypatch):
    args, _audit = _certification_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match=r"certification-inputs\.json absent"):
        mod.certify(args)
    status = json.loads((args.out / "handoff-certification-status.json").read_text())
    assert status["status"] == "blocked"
    assert status["certificate_published"] is False


def test_certification_rejects_tampered_test_log(tmp_path, monkeypatch):
    args, audit = _certification_fixture(tmp_path, monkeypatch)
    (args.out / "pytest-exact-head.log").write_text("tampered")
    (args.out / "certification-inputs.json").write_text(json.dumps({"subject_sha": HEAD}))
    with pytest.raises(ValueError, match="log digest"):
        mod.certify(args)
    assert not (audit / "handoff-ready.json").exists()


@pytest.mark.parametrize("invalid", [
    {"subject_sha": BASE}, {"subject_sha": HEAD, "evidence_profile": "none"},
    {"subject_sha": HEAD, "evidence_profile": "critical", "work_item_start_sha": BASE,
     "audit_history": "UNKNOWN"},
])
def test_certification_rejects_invalid_provenance(tmp_path, monkeypatch, invalid):
    args, audit = _certification_fixture(tmp_path, monkeypatch)
    (args.out / "certification-inputs.json").write_text(json.dumps(invalid))
    with pytest.raises(ValueError):
        mod.certify(args)
    assert not (audit / "handoff-ready.json").exists()


def test_certification_requires_real_closure_and_calls_official_gates(tmp_path, monkeypatch):
    args, audit = _certification_fixture(tmp_path, monkeypatch)
    cfg = {"subject_sha": HEAD, "evidence_profile": "light",
           "work_item_start_sha": BASE, "audit_history": "verified-no-rejection",
           "head_ref": "feat/112-lifecycle", "base_ref": "develop"}
    (args.out / "certification-inputs.json").write_text(json.dumps(cfg))
    filenames = ["specification-snapshot.json", "requirement-closure.json",
                 "codebase-grounding.json", "code-growth.json"]
    for filename in filenames:
        (audit / filename).write_text(json.dumps({"subject_sha": HEAD}))

    def fake_git(cmd, **_kwargs):
        if cmd[1] == "merge-base":
            return SimpleNamespace(returncode=0)
        return SimpleNamespace(stdout="src/service.py", returncode=0)

    monkeypatch.setattr(mod.subprocess, "run", fake_git)
    calls = []

    def capture(script, *argv):
        calls.append((script, list(argv)))

    monkeypatch.setattr(mod, "run_script", capture)
    mod.certify(args)
    assert [row[0] for row in calls] == [
        "validate_codebase_grounding.py", "check_code_growth.py",
        "build_handoff_certificate.py", "validate_handoff_certificate.py"]
    assert "--codebase-grounding" in calls[2][1]
    assert "--code-growth" in calls[2][1]
    assert "--issue-changed-path" in calls[2][1]
    result = json.loads((args.out / "handoff-certification-status.json").read_text())
    assert result["status"] == "certificate-generated"
    assert result["terminal_ready"] is False
    assert result["certificate_published"] is False

def test_allows_explicit_non_develop_branch_without_weakening_default(tmp_path):
    ev = event(base="integration")
    path = tmp_path / "event.json"
    path.write_text(json.dumps(ev))
    with pytest.raises(ValueError, match="base ref"):
        mod.read_event(path)
    assert mod.read_event(path, "integration") == ("team/skill", 113, 112, HEAD, BASE)

def test_reusable_handoff_isolates_tooling_from_consumer_tests(tmp_path):
    """Exercise the actual runner shell steps, not just a filename convention."""
    workflow_path = SCRIPT.parents[2] / ".github" / "workflows" / "reusable-handoff.yml"
    jobs = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"]
    steps = jobs["evidence"]["steps"]
    stage = next(step for step in steps if step.get("name") ==
                 "Isolate official Skill checkout outside the consumer tree")
    cleanup = next(step for step in steps if step.get("name") ==
                   "Restore official Skill checkout for Actions post-job cleanup")
    test_step = next(step for step in steps if step.get("name") ==
                     "Run consumer tests against material SHA")
    assert steps.index(stage) < steps.index(test_step) < steps.index(cleanup)
    for step in steps[steps.index(stage) + 1:steps.index(cleanup)]:
        command = step.get("run", "")
        assert "python .handoff-tooling/" not in command

    consumer = tmp_path / "consumer"
    consumer.mkdir()
    checkout = consumer / ".handoff-tooling"
    checkout.mkdir()
    (checkout / "test_duplicate.py").write_text("assert True\\n", encoding="utf-8")
    temporary = tmp_path / "runner-temp"
    temporary.mkdir()
    env_file = tmp_path / "github-env"
    env = {**os.environ, "RUNNER_TEMP": str(temporary), "GITHUB_ENV": str(env_file)}

    subprocess.run(["bash", "-e", "-o", "pipefail", "-c", stage["run"]],
                   cwd=consumer, env=env, capture_output=True, text=True, check=True)
    target = temporary / "solverit-handoff-tooling"
    assert not checkout.exists()
    assert (target / "test_duplicate.py").is_file()
    assert env_file.read_text(encoding="utf-8").strip() == f"HANDOFF_TOOLING={target}"
    assert not list(consumer.rglob("test_duplicate.py"))

    env["HANDOFF_TOOLING"] = str(target)
    subprocess.run(["bash", "-e", "-o", "pipefail", "-c", cleanup["run"]],
                   cwd=consumer, env=env, capture_output=True, text=True, check=True)
    assert (checkout / "test_duplicate.py").is_file()
    assert not target.exists()
