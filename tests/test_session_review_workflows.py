"""Trust-boundary and real shell controls for web-only review entrypoints."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

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
