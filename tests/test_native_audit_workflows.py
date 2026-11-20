"""Native audit bootstrap preserves distinct technical and human approval gates."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HANDOFF = ROOT / ".github/workflows/reusable-handoff.yml"
CALLER = ROOT / ".github/workflows/handoff-evidence.yml"
PUBLISHER = ROOT / ".github/workflows/publish-handoff.yml"
SESSION = ROOT / ".github/workflows/session-review.yml"


def workflow(path: Path) -> dict:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_native_and_legacy_routes_have_separate_real_validation_jobs():
    jobs = workflow(HANDOFF)["jobs"]
    collector, legacy, native = (jobs[key] for key in ("evidence", "certification", "native_audit_evidence"))
    assert collector["outputs"]["audit_transport"] == "${{ steps.transport.outputs.mode }}"
    assert legacy["needs"] == native["needs"] == "evidence"
    assert "needs.evidence.outputs.audit_transport == 'certified-handoff'" in legacy["if"]
    assert "needs.evidence.outputs.audit_transport == 'native-github-audit'" in native["if"]
    assert legacy["name"] != native["name"]
    assert not any("require_actions_handoff_certificate.py" in step.get("run", "")
                   for step in native["steps"])
    assert any("validate_native_actions_evidence.py" in step.get("run", "")
               for step in native["steps"])
    assert any("require_actions_handoff_certificate.py" in step.get("run", "")
               for step in legacy["steps"])


def test_native_verifier_runs_trusted_base_tooling_with_live_merge_authentication():
    steps = workflow(HANDOFF)["jobs"]["native_audit_evidence"]["steps"]
    validator = next(s for s in steps if "validate_native_actions_evidence.py" in s.get("run", ""))
    checkout = next(s for s in steps if s.get("name") == "Checkout trusted official native evidence validator")
    assert "github.event.pull_request.base.sha" in checkout["with"]["ref"]
    assert "github.event.pull_request.head.sha" not in checkout["with"]["ref"]
    assert checkout["with"]["persist-credentials"] == "false"
    assert validator["env"]["SOLVERIT_REQUIRE_LIVE_MERGE_PREVIEW"] == "1"
    assert validator["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    assert "--event \"$GITHUB_EVENT_PATH\"" in validator["run"]


def test_collector_does_not_replace_junit_with_certificate_or_candidate_test_claims():
    steps = workflow(HANDOFF)["jobs"]["evidence"]["steps"]
    transport = next(s for s in steps if s.get("id") == "transport")
    assert "resolve_trusted_audit_transport.py" in transport["run"]
    assert "--base-sha" in transport["run"] and "--head-sha" in transport["run"]
    assert transport["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    tests = next(s for s in steps if s.get("id") == "exact_tests")
    assert 'exit "$code"' in tests["run"]
    assert "pytest-exact-head.log" in tests["run"]
    assert any("build_test_candidate_index.py" in s.get("run", "") for s in steps)
    assert any(s.get("name") == "Upload evidence and blocking diagnostics"
               and s.get("if") == "always()" for s in steps)
    assert "certified-handoff" in next(
        s for s in steps if s.get("name") == "Validate evidence and build handoff certificate, fail closed"
    )["if"]


def test_trusted_publish_and_review_hooks_cannot_use_skipped_check_as_success():
    publisher = workflow(PUBLISHER)["jobs"]["publish"]
    assert "conclusion == 'success'" in publisher["if"]
    assert "--skip-native-publication" in " ".join(s.get("run", "") for s in publisher["steps"])
    caller = workflow(CALLER)
    assert caller["jobs"]["collect"]["uses"] == "./.github/workflows/reusable-handoff.yml"
    assert "branches: [develop]" in CALLER.read_text(encoding="utf-8")
    policy = workflow(SESSION)
    assert "Collect and certify exact-SHA handoff" in policy["on"]["workflow_run"]["workflows"]
    assert "checks: write" in SESSION.read_text(encoding="utf-8")
