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


def active_state(branch="develop"):
    old = baseline(branch)
    active = {**old, **plan.plan_m2(old, branch, 17)}
    return {
        "default_branch": "main",
        "target_ruleset": active,
        "rulesets": [active],
        "classic_protection": None,
    }


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


@pytest.mark.parametrize("branch", ["develop", "main"])
def test_live_readback_accepts_only_fully_active_session_ruleset(branch):
    result = plan.verify_effective_state(active_state(branch), branch, 17)
    assert result["status"] == "ACTIVE_RULESET_STRUCTURE_VERIFIED_NOT_M2_APPROVAL"
    assert result["session_review_or_negative_controls_verified"] is False
    assert result["effective_sources_verified"] is True
    assert result["active_competing_rulesets"] == []
    assert result["classic_protection_checked"] is True
    assert {item["context"] for item in result["required_checks"]} == set(plan.REQUIRED[branch])


@pytest.mark.parametrize("mutation,match", [
    (lambda r: r.update(enforcement="disabled"), "not enforced"),
    (lambda r: r["rules"][2]["parameters"].update(required_approving_review_count=1), "legacy audit gate"),
    (lambda r: r["rules"][3]["parameters"]["required_status_checks"].pop(), "rules"),
    (lambda r: r["bypass_actors"].append({"actor_id": 1}), "nonempty bypass"),
])
def test_live_readback_rejects_incomplete_or_unsafe_target_ruleset(mutation, match):
    state = active_state()
    mutation(state["target_ruleset"])
    with pytest.raises(ValueError, match=match):
        plan.verify_effective_state(state, "develop", 17)


def test_effective_readback_rejects_second_active_applicable_ruleset():
    state = active_state()
    competing = copy.deepcopy(state["target_ruleset"])
    competing["id"] = 99
    competing["name"] = "Inherited temporary exception"
    competing["conditions"] = {"ref_name": {"include": ["refs/heads/*"], "exclude": []}}
    state["rulesets"].append(competing)
    with pytest.raises(ValueError, match="additional active ruleset"):
        plan.verify_effective_state(state, "develop", 17)


def test_effective_readback_ignores_disabled_or_nonmatching_ruleset():
    state = active_state()
    disabled = copy.deepcopy(state["target_ruleset"])
    disabled.update(id=98, enforcement="disabled")
    other = copy.deepcopy(state["target_ruleset"])
    other.update(id=99, name="Other branch")
    other["conditions"] = {"ref_name": {"include": ["refs/heads/release"], "exclude": []}}
    state["rulesets"].extend([disabled, other])
    assert plan.verify_effective_state(state, "develop", 17)["effective_sources_verified"] is True


def test_effective_readback_rejects_classic_human_review_or_legacy_gate():
    state = active_state()
    state["classic_protection"] = {
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
            "require_code_owner_reviews": False,
            "require_last_push_approval": False,
            "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []},
        },
        "required_status_checks": {"strict": True, "contexts": [], "checks": []},
    }
    with pytest.raises(ValueError, match="still requires human review"):
        plan.verify_effective_state(state, "develop", 17)

    state["classic_protection"]["required_pull_request_reviews"]["required_approving_review_count"] = 0
    state["classic_protection"]["required_status_checks"]["contexts"] = [plan.LEGACY]
    with pytest.raises(ValueError, match="legacy audit gate"):
        plan.verify_effective_state(state, "develop", 17)


def test_effective_readback_accepts_compatible_classic_protection():
    state = active_state()
    state["classic_protection"] = {
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_pull_request_reviews": {
            "required_approving_review_count": 0,
            "require_code_owner_reviews": False,
            "require_last_push_approval": False,
            "bypass_pull_request_allowances": {"users": [], "teams": [], "apps": []},
        },
        "required_status_checks": {
            "strict": True,
            "contexts": ["Structure and tests"],
            "checks": [{"context": "Structure and tests", "app_id": 15368}],
        },
    }
    assert plan.verify_effective_state(state, "develop", 17)["classic_protection_checked"] is True


def test_read_effective_state_requires_bypass_visibility_for_every_ruleset(monkeypatch):
    responses = {
        "/repos/crgasparoto-br/skill": {"default_branch": "main"},
        "/repos/crgasparoto-br/skill/rulesets?includes_parents=true": [
            {"id": 17}, {"id": 99}
        ],
        "/repos/crgasparoto-br/skill/rulesets/17": {**baseline(), "bypass_actors": []},
        "/repos/crgasparoto-br/skill/rulesets/99": {
            "id": 99, "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~ALL"], "exclude": []}},
            "rules": [],
        },
    }
    monkeypatch.setattr(plan, "gh_api", lambda _repo, path: responses[path])
    monkeypatch.setattr(
        plan, "read_all_rulesets",
        lambda _repo: responses["/repos/crgasparoto-br/skill/rulesets?includes_parents=true"],
    )
    monkeypatch.setattr(
        plan, "read_classic_protection", lambda _repo, _branch, **_kwargs: None
    )
    with pytest.raises(ValueError, match="bypass actors are not visible"):
        plan.read_effective_state("crgasparoto-br/skill", "develop", 17)


def test_readback_cli_uses_complete_effective_state(monkeypatch, capsys):
    import sys
    monkeypatch.setattr(plan, "read_effective_state", lambda _repo, _branch, _id: active_state())
    monkeypatch.setattr(plan, "read_ruleset",
                        lambda *_args: pytest.fail("single-ruleset read must not drive --readback"))
    monkeypatch.setattr(sys, "argv", [
        "plan_session_ruleset_m2", "--repo", "crgasparoto-br/skill",
        "--branch", "develop", "--ruleset-id", "17", "--readback"])
    plan.main()
    output = capsys.readouterr().out
    assert "ACTIVE_RULESET_STRUCTURE_VERIFIED_NOT_M2_APPROVAL" in output
    assert '"effective_sources_verified": true' in output


def test_read_all_rulesets_slurps_every_page(monkeypatch):
    import json
    from types import SimpleNamespace

    calls = []

    def fake_run(args, **_kwargs):
        calls.append(args)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([[{"id": 17}], [{"id": 99}]]),
            stderr="",
        )

    monkeypatch.setattr(plan.subprocess, "run", fake_run)
    assert plan.read_all_rulesets("crgasparoto-br/skill") == [{"id": 17}, {"id": 99}]
    assert calls == [[
        "gh", "api", "--paginate", "--slurp",
        "/repos/crgasparoto-br/skill/rulesets?includes_parents=true&per_page=100",
    ]]


@pytest.mark.parametrize("pages", [
    [{"id": 17}],
    {"rulesets": [{"id": 17}]},
    [[{"id": 17}], {"id": 99}],
])
def test_read_all_rulesets_rejects_non_paginated_or_malformed_shapes(monkeypatch, pages):
    import json
    from types import SimpleNamespace

    monkeypatch.setattr(
        plan.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=json.dumps(pages), stderr=""
        ),
    )
    with pytest.raises(ValueError, match="paginated ruleset inventory"):
        plan.read_all_rulesets("crgasparoto-br/skill")


def test_second_page_competing_ruleset_blocks_effective_readback(monkeypatch):
    import json
    from types import SimpleNamespace

    target = active_state()["target_ruleset"]
    competitor = copy.deepcopy(target)
    competitor.update(id=99, name="Inherited branch-wide rule")
    competitor["conditions"]["ref_name"]["include"] = ["refs/heads/*"]

    def fake_run(_args, **_kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([
                [{"id": 17, "target": "branch", "enforcement": "active"}],
                [{"id": 99, "target": "branch", "enforcement": "active"}],
            ]),
            stderr="",
        )

    responses = {
        "/repos/crgasparoto-br/skill": {
            "default_branch": "main", "permissions": {"admin": True},
        },
        "/repos/crgasparoto-br/skill/rulesets/17": target,
        "/repos/crgasparoto-br/skill/rulesets/99": competitor,
    }
    monkeypatch.setattr(plan.subprocess, "run", fake_run)
    monkeypatch.setattr(plan, "gh_api", lambda _repo, path: responses[path])
    monkeypatch.setattr(
        plan, "read_classic_protection", lambda _repo, _branch, **_kw: None
    )
    state = plan.read_effective_state("crgasparoto-br/skill", "develop", 17)
    assert len(state["rulesets"]) == 2
    with pytest.raises(ValueError, match="additional active ruleset"):
        plan.verify_effective_state(state, "develop", 17)


@pytest.mark.parametrize("bypass", [
    None,
    {},
    {"users": [], "teams": []},
    {"users": [], "teams": [], "apps": None},
    {"users": [], "teams": [], "apps": [{"id": 3}]},
])
def test_classic_review_bypass_inventory_must_be_explicit(bypass):
    state = active_state()
    reviews = {
        "required_approving_review_count": 0,
        "require_code_owner_reviews": False,
        "require_last_push_approval": False,
    }
    if bypass is not None:
        reviews["bypass_pull_request_allowances"] = bypass
    state["classic_protection"] = {
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_pull_request_reviews": reviews,
    }
    with pytest.raises(ValueError, match="bypass"):
        plan.verify_effective_state(state, "develop", 17)


def test_classic_checks_cannot_hide_legacy_gate_outside_contexts():
    state = active_state()
    state["classic_protection"] = {
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
        "required_status_checks": {
            "strict": True, "contexts": [],
            "checks": [{"context": plan.LEGACY, "app_id": 15368}],
        },
    }
    with pytest.raises(ValueError, match="legacy audit gate"):
        plan.verify_effective_state(state, "develop", 17)


def test_effective_readback_rejects_duplicate_ruleset_ids():
    state = active_state()
    state["rulesets"].append(copy.deepcopy(state["target_ruleset"]))
    with pytest.raises(ValueError, match="duplicate ruleset id"):
        plan.verify_effective_state(state, "develop", 17)


def test_classic_404_without_verified_admin_rights_is_not_absence(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        plan.subprocess, "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="gh: Not Found (HTTP 404)"
        ),
    )
    with pytest.raises(ValueError, match="ambiguous without authenticated admin"):
        plan.read_classic_protection("crgasparoto-br/skill", "develop")
    assert plan.read_classic_protection(
        "crgasparoto-br/skill", "develop", admin_confirmed=True
    ) is None

