"""Positive, negative and regression controls for read-only M2 ruleset plans."""
import copy
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "plan_session_ruleset_m2.py"
spec = importlib.util.spec_from_file_location("plan_session_ruleset_m2", SCRIPT)
assert spec and spec.loader
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)


def baseline(branch="develop"):
    checks = [{"context": "Structure and tests", "integration_id": 15368},
              {"context": "Verify independent audit (exact SHA)", "integration_id": 15368}]
    if branch == "develop":
        checks.extend([
            {"context": "Offline authorization tests", "integration_id": 15368},
            {"context": "collect / Require certified semantic handoff (exact SHA)", "integration_id": 15368}])
    return {"id": 17, "name": "Protect " + branch, "target": "branch",
            "enforcement": "disabled", "bypass_actors": [],
            "conditions": {"ref_name": {"include": ["refs/heads/"+branch], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                      {"type": "pull_request", "parameters": {
                          "required_approving_review_count": 1,
                          "required_reviewers": [], "require_code_owner_review": False,
                          "require_last_push_approval": False,
                          "require_extra_approval_for_unattributed_changes": True}},
                      {"type": "required_status_checks", "parameters": {
                          "strict_required_status_checks_policy": True,
                          "do_not_enforce_on_create": False,
                          "required_status_checks": checks}}]}


@pytest.mark.parametrize("branch", ["develop", "main"])
def test_exact_branch_plan_preserves_all_protections_and_upgrades_to_session(branch):
    old = baseline(branch)
    snapshot = copy.deepcopy(old)
    proposed = plan.plan_m2(old, branch, 17)
    assert old == snapshot
    assert proposed["enforcement"] == "active"
    assert proposed["bypass_actors"] == []
    assert proposed["rules"][:2] == old["rules"][:2]
    assert proposed["rules"][2]["parameters"]["required_approving_review_count"] == 0
    assert proposed["rules"][2]["parameters"]["require_extra_approval_for_unattributed_changes"] is True
    checks = proposed["rules"][3]["parameters"]["required_status_checks"]
    assert {item["context"] for item in checks} == set(plan.REQUIRED[branch])
    assert all(item["integration_id"] == 15368 for item in checks)
    assert proposed["rules"][3]["parameters"]["strict_required_status_checks_policy"] is True
    assert proposed == plan.plan_m2(dict(old, enforcement="active"), branch, 17)


@pytest.mark.parametrize("mutation,match", [
    (lambda r: r.pop("bypass_actors"), "bypass actors"),
    (lambda r: r["bypass_actors"].append({"actor_type": "User", "actor_id": 1, "bypass_mode": "always"}), "nonempty bypass"),
    (lambda r: r["conditions"]["ref_name"]["include"].append("refs/heads/main"), "does not target"),
    (lambda r: r["rules"].pop(0), "deletion"),
    (lambda r: r["rules"].pop(1), "non_fast_forward"),
    (lambda r: r["rules"][2]["parameters"].update(require_code_owner_review=True), "code-owner"),
    (lambda r: r["rules"][2]["parameters"].update(require_last_push_approval=True), "last-push"),
    (lambda r: r["rules"][3]["parameters"].update(strict_required_status_checks_policy=False), "strict"),
    (lambda r: r["rules"][3]["parameters"].update(do_not_enforce_on_create=True), "branch creation"),
    (lambda r: r.update(enforcement="evaluate"), "enforcement"),
])
def test_rejects_unsafe_proposals(mutation, match):
    item = baseline()
    mutation(item)
    with pytest.raises(ValueError, match=match):
        plan.plan_m2(item, "develop", 17)


def test_preserves_nonlegacy_custom_checks_without_changing_app_origin():
    item = baseline()
    item["rules"][3]["parameters"]["required_status_checks"].append(
        {"context": "Additional security review", "integration_id": 9123})
    result = plan.plan_m2(item, "develop", 17)
    checks = result["rules"][3]["parameters"]["required_status_checks"]
    assert {c["context"]: c["integration_id"] for c in checks}["Additional security review"] == 9123
    assert "Verify independent audit (exact SHA)" not in {c["context"] for c in checks}


def test_rejects_unexpected_origin_or_duplicate_check():
    item = baseline()
    item["rules"][3]["parameters"]["required_status_checks"][0]["integration_id"] = 9
    with pytest.raises(ValueError, match="unexpected app origin"):
        plan.plan_m2(item, "develop", 17)
    item = baseline()
    item["rules"][3]["parameters"]["required_status_checks"].append(
        {"context": "Structure and tests", "integration_id": 15368})
    with pytest.raises(ValueError, match="duplicate required check"):
        plan.plan_m2(item, "develop", 17)


def test_rejects_migration_when_legacy_gate_is_missing_or_untrusted():
    item = baseline()
    item["rules"][3]["parameters"]["required_status_checks"][1]["integration_id"] = 9
    with pytest.raises(ValueError, match="legacy check has unexpected app origin"):
        plan.plan_m2(item, "develop", 17)
    item = baseline()
    item["rules"][3]["parameters"]["required_status_checks"].pop(1)
    with pytest.raises(ValueError, match="legacy audit gate absent"):
        plan.plan_m2(item, "develop", 17)


def test_plan_does_not_perform_remote_mutation(monkeypatch, capsys):
    import sys
    monkeypatch.setattr(plan, "read_ruleset", lambda repo, ruleset_id: baseline())
    monkeypatch.setattr(sys, "argv", [
        "plan_session_ruleset_m2", "--repo", "crgasparoto-br/skill",
        "--branch", "develop", "--ruleset-id", "17"])
    plan.main()
    output = capsys.readouterr().out
    assert '"status": "READ_ONLY_PROPOSAL_NOT_M2_APPROVAL"' in output
    assert '"requires_prior_real_positive_and_negative_M2_acceptance": true' in output
