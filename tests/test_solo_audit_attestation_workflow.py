"""Static trust-boundary checks for the solo Ed25519 workflow entrypoint."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ".github/workflows/solo-audit-attestation.yml"
CHECK_NAME = "Verify solo audit attestation (exact SHA)"


def workflow():
    # BaseLoader preserves GitHub's `on` key as a string.
    return yaml.load((ROOT / WORKFLOW_PATH).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_solo_gate_uses_only_trusted_events_and_no_caller_selected_ref():
    config = workflow()
    triggers = config["on"]
    assert set(triggers) == {
        "pull_request_target", "pull_request_review", "issue_comment", "issues", "workflow_run", "push"
    }
    assert "workflow_dispatch" not in triggers
    assert "workflow_call" not in triggers
    assert "pull_request" not in triggers
    assert triggers["pull_request_target"]["branches"] == ["develop", "main"]
    assert triggers["push"]["branches"] == ["develop", "main"]
    assert triggers["issue_comment"]["types"] == ["created", "edited", "deleted"]
    assert triggers["pull_request_review"]["types"] == ["submitted", "edited", "dismissed"]
    assert triggers["workflow_run"]["workflows"] == [
        "Validate skills", "Validate GitHub Audit MCP", "Collect and certify exact-SHA handoff"
    ]


def test_workflow_checks_out_workflow_sha_and_never_executes_candidate_code():
    config = workflow()
    job = config["jobs"]["revalidate"]
    steps = job["steps"]
    assert "github.ref_protected" in job["if"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"] == {"ref": "${{ github.workflow_sha }}", "persist-credentials": "false"}
    assert steps.index(checkout) < next(i for i, step in enumerate(steps) if "run" in step)
    assert checkout["uses"] == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    setup = next(step for step in steps if step.get("uses", "").startswith("actions/setup-python@"))
    assert setup["uses"] == "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
    commands = [step.get("run", "") for step in steps]
    assert any("--require-hashes" in command and "auditar-issue/requirements.lock.txt" in command
               for command in commands)
    gate_step = next(step for step in steps if "verify_solo_audit_attestation.py" in step.get("run", ""))
    assert "${{" not in gate_step["run"]
    assert "GITHUB_EVENT_PATH" in gate_step["run"]
    assert "github.head_ref" not in gate_step["run"]
    assert "pull_request.head.sha" not in gate_step["run"]
    assert all("checkout" not in step.get("run", "").lower() for step in steps)


def test_token_is_step_scoped_and_only_check_write_is_granted():
    config = workflow()
    permissions = config["permissions"]
    assert permissions == {
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
        "actions": "read",
        "checks": "write",
    }
    job = config["jobs"]["revalidate"]
    step = next(step for step in job["steps"] if "verify_solo_audit_attestation.py" in step.get("run", ""))
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert step["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    assert "GITHUB_TOKEN" not in job.get("env", {})
    assert "GH_TOKEN" not in job.get("env", {})
    assert job["name"] != CHECK_NAME  # The custom Check Run is created by the trusted verifier.


def test_concurrency_serializes_events_without_cancelling_newer_revocations():
    config = workflow()
    assert config["concurrency"]["cancel-in-progress"] == "false"
    assert config["concurrency"]["queue"] == "max"
    assert "github.repository" in config["concurrency"]["group"]


def test_only_same_repo_workflow_runs_and_pr_comments_are_routed():
    config = workflow()
    condition = config["jobs"]["revalidate"]["if"]
    assert "github.event_name != 'issue_comment' || github.event.issue.pull_request" in condition
    assert "github.event.workflow_run.event == 'pull_request'" in condition
    assert "github.event.workflow_run.head_repository.full_name == github.repository" in condition
    assert "pull_request_review" in condition


def test_new_check_is_not_conflated_with_native_or_session_checks():
    config = workflow()
    assert "independent-audit-gate.yml" not in (ROOT / WORKFLOW_PATH).read_text(encoding="utf-8")
    assert "session-review.yml" not in (ROOT / WORKFLOW_PATH).read_text(encoding="utf-8")
    script = (ROOT / "scripts/verify_solo_audit_attestation.py").read_text(encoding="utf-8")
    contract = (ROOT / "scripts/solo_audit_contract.py").read_text(encoding="utf-8")
    trusted_sources = (ROOT / "scripts/solo_audit_source.py").read_text(encoding="utf-8")
    assert CHECK_NAME in contract
    assert "independent human audit approved" not in script
    assert "no third-party human approval claimed" in contract
    assert ".github/workflows/solo-audit-attestation.yml" in trusted_sources
    assert "scripts/verify_independent_pr_audit.py" in trusted_sources
    assert "entregar-issue/scripts/validate_finding_completion.py" in trusted_sources
    assert "auditar-issue/requirements.lock.txt" in trusted_sources
