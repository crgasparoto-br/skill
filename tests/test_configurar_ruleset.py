"""Regression controls for the opt-in GitHub ruleset administrative utility."""
from __future__ import annotations

import base64
import copy
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "configurar_ruleset.py"
spec = importlib.util.spec_from_file_location("configurar_ruleset", SCRIPT)
assert spec and spec.loader
admin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admin)

REPO = "crgasparoto-br/skill"
CHECK = "collect / Require certified semantic handoff (exact SHA)"


def ruleset():
    return {
        "id": 24821474, "name": "Protect develop",
        "target": "branch", "enforcement": "active",
        "updated_at": "2026-10-23",
        "conditions": {"ref_name": {"include": ["refs/heads/develop"], "exclude": []}},
        "bypass_actors": [],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {"required_approving_review_count": 1}},
            {"type": "required_status_checks", "parameters": {
                "strict_required_status_checks_policy": True,
                "do_not_enforce_on_create": False,
                "required_status_checks": [],
            }},
        ],
    }


def test_preserves_rules_and_never_invents_bypass():
    before = ruleset()
    original = copy.deepcopy(before)
    change = admin.plan(before, "develop", 24821474, ["Structure and tests", CHECK], 15368)
    assert before == original
    assert change["rules"][:3] == original["rules"][:3]
    assert change["bypass_actors"] == []
    assert change["rules"][-1]["parameters"]["strict_required_status_checks_policy"] is True
    assert change["rules"][-1]["parameters"]["required_status_checks"][-1] == {
        "context": CHECK, "integration_id": 15368,
    }
    admin.verify(before, dict(before, rules=change["rules"]), change)


@pytest.mark.parametrize("mutation,reason", [
    (lambda r: r.pop("bypass_actors"), "bypass actor"),
    (lambda r: r["conditions"]["ref_name"]["include"].append("refs/heads/main"), "branch targeting"),
    (lambda r: r["rules"][-1]["parameters"].update(strict_required_status_checks_policy=False), "strict"),
])
def test_rejects_unsafe_ruleset_inputs(mutation, reason):
    sample = ruleset()
    mutation(sample)
    with pytest.raises(ValueError, match=reason):
        admin.plan(sample, "develop", 24821474, [CHECK], 15368)


def test_requires_real_check_with_exact_github_actions_app(monkeypatch):
    monkeypatch.setattr(admin, "gh", lambda *args, **kwargs: {
        "total_count": 1,
        "check_runs": [{"name": CHECK, "conclusion": "failure", "app": {"id": 15368}}],
    })
    assert admin.verified_checks(REPO, "a" * 40, [CHECK], 15368)[CHECK] == ["failure"]
    with pytest.raises(ValueError, match="missing GitHub Actions check"):
        admin.verified_checks(REPO, "a" * 40, ["invented-release-check"], 15368)
    with pytest.raises(ValueError, match="missing GitHub Actions check"):
        admin.verified_checks(REPO, "a" * 40, [CHECK], 999)


def test_dry_run_is_read_only_even_if_sample_check_failed(monkeypatch):
    calls = []
    before = ruleset()

    def fake_gh(endpoint, method="GET", payload=None):
        calls.append((method, endpoint))
        if "check-runs" in endpoint:
            return {"total_count": 1, "check_runs": [
                {"name": CHECK, "conclusion": "failure", "app": {"id": 15368}},
            ]}
        return before

    monkeypatch.setattr(admin, "gh", fake_gh)
    monkeypatch.setattr(sys, "argv", [
        "configurar_ruleset", "--repo", REPO, "--branch", "develop",
        "--ruleset-id", "24821474", "--sample-sha", "a" * 40,
        "--check", CHECK,
    ])
    admin.main()
    assert calls and all(method == "GET" for method, _ in calls)


def test_refuses_untrusted_main_context_before_any_git_access(monkeypatch):
    monkeypatch.setattr(admin, "gh", lambda *args, **kwargs: pytest.fail("unexpected GitHub access"))
    monkeypatch.setattr(sys, "argv", [
        "configurar_ruleset", "--repo", REPO, "--branch", "main",
        "--ruleset-id", "24821457", "--sample-sha", "a" * 40,
        "--check", "Structure and tests", "--apply",
    ])
    with pytest.raises(SystemExit, match="2"):
        admin.main()


def test_apply_refuses_stale_ruleset_before_any_write(monkeypatch):
    original = ruleset()
    changed = copy.deepcopy(original)
    changed["updated_at"] = "2026-10-24"
    reads = []
    writes = []

    def fake_gh(endpoint, method="GET", payload=None):
        if "check-runs" in endpoint:
            return {"total_count": 2, "check_runs": [
                {"name": CHECK, "conclusion": "success", "app": {"id": 15368}},
                {"name": "Verify independent audit (exact SHA)",
                 "conclusion": "success", "app": {"id": 15368}},
            ]}
        if "/contents/" in endpoint:
            return {"type": "file", "sha": "a" * 40}
        if method == "PUT":
            writes.append(payload)
            pytest.fail("write must not occur after a stale-ruleset preflight")
        reads.append(endpoint)
        return original if len(reads) == 1 else changed

    monkeypatch.setattr(admin, "gh", fake_gh)
    monkeypatch.setattr(sys, "argv", [
        "configurar_ruleset", "--repo", REPO, "--branch", "develop",
        "--ruleset-id", "24821474", "--sample-sha", "a" * 40,
        "--check", CHECK, "--check", "Verify independent audit (exact SHA)",
        "--apply",
    ])
    with pytest.raises(ValueError, match="ruleset changed after preview"):
        admin.main()
    assert len(reads) == 2
    assert writes == []


def test_readback_rejects_bypass_drift():
    before = ruleset()
    planned = admin.plan(before, "develop", 24821474, [CHECK], 15368)
    observed = dict(before, rules=planned["rules"],
                    bypass_actors=[{"actor_id": 1, "bypass_mode": "always"}])
    with pytest.raises(ValueError, match="bypass_actors"):
        admin.verify(before, observed, planned)


def test_existing_required_checks_remain_mandatory():
    current = ruleset()
    current["rules"][-1]["parameters"]["required_status_checks"] = [
        {"context": "Legacy integration gate", "integration_id": 5678},
    ]
    planned = admin.plan(current, "develop", 24821474, [CHECK], 15368)
    assert planned["rules"][-1]["parameters"]["required_status_checks"] == [
        {"context": "Legacy integration gate", "integration_id": 5678},
        {"context": CHECK, "integration_id": 15368},
    ]
    assert current["rules"][-1]["parameters"]["required_status_checks"] == [
        {"context": "Legacy integration gate", "integration_id": 5678},
    ]
    with pytest.raises(ValueError, match="origin differs"):
        admin.plan(current, "develop", 24821474, ["Legacy integration gate"], 15368)


def test_admin_apply_requires_independent_review_check(monkeypatch):
    monkeypatch.setattr(admin, "gh", lambda *args, **kwargs: pytest.fail("unexpected GitHub access"))
    monkeypatch.setattr(sys, "argv", [
        "configurar_ruleset", "--repo", REPO, "--branch", "develop",
        "--ruleset-id", "24821474", "--sample-sha", "a" * 40,
        "--check", CHECK, "--apply",
    ])
    with pytest.raises(SystemExit, match="2"):
        admin.main()


def test_admin_dry_run_cannot_drop_existing_check(monkeypatch):
    current = ruleset()
    current["rules"][-1]["parameters"]["required_status_checks"] = [
        {"context": "Pre-existing", "integration_id": 4321},
    ]
    def fake_gh(endpoint, method="GET", payload=None):
        if "check-runs" in endpoint:
            return {"total_count": 1, "check_runs": [
                {"name": CHECK, "app": {"id": 15368}, "conclusion": "failure"},
            ]}
        assert method == "GET"
        return current
    monkeypatch.setattr(admin, "gh", fake_gh)
    monkeypatch.setattr(sys, "argv", [
        "configurar_ruleset", "--repo", REPO, "--branch", "develop",
        "--ruleset-id", "24821474", "--sample-sha", "a" * 40,
        "--check", CHECK,
    ])
    admin.main()
    assert current["rules"][-1]["parameters"]["required_status_checks"][0]["context"] == "Pre-existing"


def test_ruleset_raises_zero_review_approval_to_one_and_preserves_stronger_policy():
    current = ruleset()
    current["rules"][2]["parameters"]["required_approving_review_count"] = 0
    assert admin.plan(current, "develop", 24821474, [CHECK], 15368)["rules"][2]["parameters"][
        "required_approving_review_count"
    ] == 1
    current["rules"][2]["parameters"]["required_approving_review_count"] = 2
    assert admin.plan(current, "develop", 24821474, [CHECK], 15368)["rules"][2]["parameters"][
        "required_approving_review_count"
    ] == 2
    assert current["rules"][2]["parameters"]["required_approving_review_count"] == 2


def test_admin_apply_blocks_when_policy_absent_from_trusted_base(monkeypatch):
    writes = []
    def fake_gh(endpoint, method="GET", payload=None):
        if method != "GET":
            writes.append(endpoint)
            pytest.fail("unexpected administrative write")
        if "check-runs" in endpoint:
            return {"total_count": 2, "check_runs": [
                {"name": CHECK, "conclusion": "success", "app": {"id": 15368}},
                {"name": "Verify independent audit (exact SHA)",
                 "conclusion": "success", "app": {"id": 15368}},
            ]}
        if "/contents/" in endpoint:
            return {"type": "dir"}
        pytest.fail("unexpected ruleset read")
    monkeypatch.setattr(admin, "gh", fake_gh)
    monkeypatch.setattr(sys, "argv", [
        "configurar_ruleset", "--repo", REPO, "--branch", "develop",
        "--ruleset-id", "24821474", "--sample-sha", "a" * 40,
        "--check", CHECK, "--check", "Verify independent audit (exact SHA)", "--apply",
    ])
    with pytest.raises(ValueError, match="trusted branch does not publish"):
        admin.main()
    assert not writes


def test_admin_apply_requires_failed_gate_without_bypassing_it(monkeypatch):
    current = ruleset()
    written = []

    def fake_gh(endpoint, method="GET", payload=None):
        if "check-runs" in endpoint:
            return {"total_count": 2, "check_runs": [
                {"name": CHECK, "conclusion": "failure", "app": {"id": 15368}},
                {"name": "Verify independent audit (exact SHA)",
                 "conclusion": "failure", "app": {"id": 15368}},
            ]}
        if "session-review-policy.json" in endpoint:
            return trusted_session_policy_blob("disabled")
        if "/contents/" in endpoint:
            return {"type": "file", "sha": "a" * 40}
        if method == "PUT":
            written.append(copy.deepcopy(payload))
            return {"updated": True}
        if written:
            return dict(current, **written[0])
        return current

    monkeypatch.setattr(admin, "gh", fake_gh)
    monkeypatch.setattr(sys, "argv", [
        "configurar_ruleset", "--repo", REPO, "--branch", "develop",
        "--ruleset-id", "24821474", "--sample-sha", "a" * 40,
        "--check", CHECK, "--check", "Verify independent audit (exact SHA)",
        "--apply",
    ])
    admin.main()
    assert len(written) == 1
    protected = written[0]["rules"][-1]["parameters"]["required_status_checks"]
    assert {entry["context"] for entry in protected} == {
        CHECK, "Verify independent audit (exact SHA)",
    }
    assert written[0]["rules"][2]["parameters"]["required_approving_review_count"] == 1
    assert written[0]["rules"][-1]["parameters"]["strict_required_status_checks_policy"] is True


@pytest.mark.parametrize("unacceptable", [None, "skipped", "cancelled", "timed_out"])
def test_admin_apply_blocks_unusable_sample_even_with_trusted_emitter(monkeypatch, unacceptable):
    writes = []

    def fake_gh(endpoint, method="GET", payload=None):
        if method != "GET":
            writes.append(endpoint)
            pytest.fail("unexpected administrative write")
        if "check-runs" in endpoint:
            return {"total_count": 2, "check_runs": [
                {"name": CHECK, "conclusion": unacceptable, "app": {"id": 15368}},
                {"name": "Verify independent audit (exact SHA)",
                 "conclusion": "failure", "app": {"id": 15368}},
            ]}
        if "/contents/" in endpoint:
            return {"type": "file", "sha": "a" * 40}
        pytest.fail("unexpected ruleset read")

    monkeypatch.setattr(admin, "gh", fake_gh)
    monkeypatch.setattr(sys, "argv", [
        "configurar_ruleset", "--repo", REPO, "--branch", "develop",
        "--ruleset-id", "24821474", "--sample-sha", "a" * 40,
        "--check", CHECK, "--check", "Verify independent audit (exact SHA)",
        "--apply",
    ])
    with pytest.raises(ValueError, match="sample check not terminal"):
        admin.main()
    assert writes == []


def trusted_session_policy_blob(mode: str) -> dict:
    policy = {
        "schema_version": 1,
        "mode": mode,
        "assurance": "operator-attested-session-review",
        "acknowledgement": "separate-context-declared-not-cryptographically-proven",
        "operators": [{"id": 255721831, "login": "crgasparoto-br"}],
    }
    raw = (json.dumps(policy, sort_keys=True) + "\n").encode("utf-8")
    sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    return {"type": "file", "encoding": "base64", "sha": sha,
            "content": base64.b64encode(raw).decode("ascii")}


def test_legacy_apply_rejects_single_operator_policy_without_mutation(monkeypatch):
    writes = []

    def fake_gh(endpoint, method="GET", payload=None):
        if method != "GET":
            writes.append(endpoint)
            pytest.fail("single-operator policy cannot authorize legacy ruleset mutation")
        return trusted_session_policy_blob("enabled")

    monkeypatch.setattr(admin, "gh", fake_gh)
    with pytest.raises(ValueError, match="legacy human-audit ruleset apply forbidden"):
        admin.refuse_legacy_apply_in_single_operator_mode(REPO, "develop")
    assert writes == []


@pytest.mark.parametrize("mutation", ["invalid-sha", "missing-content", "invalid-mode"])
def test_legacy_apply_rejects_untrusted_or_unknown_policy(monkeypatch, mutation):
    policy = trusted_session_policy_blob("disabled")
    if mutation == "invalid-sha":
        policy["sha"] = "0" * 40
    elif mutation == "missing-content":
        policy.pop("content")
    else:
        policy = trusted_session_policy_blob("unexpected")
    monkeypatch.setattr(admin, "gh", lambda *args, **kwargs: policy)
    with pytest.raises(ValueError, match="policy"):
        admin.refuse_legacy_apply_in_single_operator_mode(REPO, "develop")


def test_explicit_disabled_policy_keeps_human_audit_capability(monkeypatch):
    monkeypatch.setattr(admin, "gh",
                        lambda *args, **kwargs: trusted_session_policy_blob("disabled"))
    admin.refuse_legacy_apply_in_single_operator_mode(REPO, "develop")
