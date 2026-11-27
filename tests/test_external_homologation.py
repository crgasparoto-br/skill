"""Synthetic M1 contract controls; not evidence of real provider operation."""
from __future__ import annotations

import copy
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
gate = importlib.import_module("external_homologation")


def make_case(assurance=gate.SOLO):
    owner = {"id": 11, "login": "owner"}
    reviewer = owner if assurance == gate.SOLO else {"id": 12, "login": "reviewer"}
    policy = gate.canonical({"schema_version": 1, "mode": "enabled", "repository": "org/repo",
                             "assurance": assurance, "owner": owner, "reviewer": reviewer,
                             "scenarios": {"play": {"origin": "https://preview.example", "controls": ["start", "progress"],
                                                    "technical_checks": {"Technical validation": 123}}}})
    identity = {"repository": "org/repo", "pull_request": 2, "issue": 1, "base_ref": "develop",
                "base_sha": "b" * 40, "head_sha": "a" * 40, "merge_preview_sha": "c" * 40,
                "issue_sha256": "d" * 64, "policy_sha256": gate.digest(policy)}
    facts = {"environment": {"origin": "https://preview.example", "head_sha": "a" * 40,
                             "deployment_id": "deploy-42", "tls_verified": True},
             "external_attempt": {"head_sha": "a" * 40, "run_id": 3, "run_attempt": 1,
                                  "result": "blocked-external", "diagnostic_sha256": "e" * 64},
             "technical_checks": {"Technical validation": {"id": 4, "app_id": 123, "head_sha": "a" * 40,
                                                           "run_id": 5, "run_attempt": 1, "conclusion": "success"}}}
    files = {"before.png": b"fixture before", "after.png": b"fixture after"}
    manifest = gate.canonical({"schema_version": 1, "identity": identity, "scenario": "play",
                               "kind": "human-observed-external", "simulated": False,
                               "facts_sha256": gate.digest(gate.canonical(facts)),
                               "files": {k: gate.digest(v) for k, v in files.items()},
                               "observations": {"start": {"result": "observed-pass", "files": ["before.png"]},
                                                "progress": {"result": "observed-pass", "files": ["after.png"]}}})
    statement = {"identity": identity, "manifest_sha256": gate.digest(manifest), "decision": "observed-pass"}

    def comment(number, actor, prefix, payload):
        return {"id": number, "user": {**actor, "type": "User"}, "body": prefix + gate.canonical(payload).decode(),
                "created_at": "2026-11-27T11:00:00Z", "updated_at": "2026-11-27T11:00:00Z",
                "issue_url": "https://api.github.com/repos/org/repo/issues/2",
                "url": f"https://api.github.com/repos/org/repo/issues/comments/{number}"}

    first = comment(21, owner, gate.OWNER_PREFIX, statement)
    review = {**statement, "decision": "approved", "owner_comment_id": 21,
              "owner_comment_sha256": gate.digest(first["body"].encode()), "assurance": assurance,
              "separate_context_attested": True}
    return {"default_policy": policy, "base_policy": policy, "identity": identity, "facts": facts,
            "manifest_raw": manifest, "files": files, "comments": [first, comment(22, reviewer, gate.REVIEW_PREFIX, review)],
            "watermarks": {"owner": 21, "reviewer": 22}}


@pytest.mark.parametrize("assurance", [gate.SOLO, gate.THIRD_PARTY])
def test_valid_contract_never_releases_or_claims_automated_pass(assurance):
    result = gate.validate_external_homologation(**make_case(assurance))
    assert result == {"result": "contract-valid", "assurance": assurance, "automated_live_pass": False,
                      "source_authentication_performed": False, "release_gate_satisfied": False}


def edit_json(case, key, change):
    value = gate.parse(case[key])
    change(value)
    case[key] = gate.canonical(value)


@pytest.mark.parametrize("change", [
    lambda x: x.update(default_policy=None),
    lambda x: x.update(base_policy=x["base_policy"] + b" "),
    lambda x: x.update(default_policy=b'{"mode":"disabled"}', base_policy=b'{"mode":"disabled"}'),
    lambda x: x.update(manifest_raw=b'{"schema_version":1,"schema_version":1}'),
    lambda x: x["identity"].update(head_sha="f" * 40),
    lambda x: x["identity"].update(base_sha="f" * 40),
    lambda x: x["identity"].update(merge_preview_sha="f" * 40),
    lambda x: x["identity"].update(issue_sha256="f" * 64),
    lambda x: x["identity"].update(pull_request=3),
    lambda x: edit_json(x, "manifest_raw", lambda m: m.update(simulated=True)),
    lambda x: edit_json(x, "manifest_raw", lambda m: m["observations"].pop("progress")),
    lambda x: edit_json(x, "manifest_raw", lambda m: m["observations"]["progress"].update(result="blocked-external")),
    lambda x: x["facts"]["environment"].update(origin="http://preview.example"),
    lambda x: x["facts"]["environment"].update(tls_verified=False),
    lambda x: x["facts"]["environment"].update(head_sha="f" * 40),
    lambda x: x["facts"]["external_attempt"].update(result="FAIL_OR_UNAVAILABLE"),
    lambda x: x["facts"]["technical_checks"]["Technical validation"].update(conclusion="failure"),
    lambda x: x["facts"]["technical_checks"]["Technical validation"].update(app_id=999),
    lambda x: x["facts"]["technical_checks"]["Technical validation"].update(head_sha="f" * 40),
    lambda x: x["facts"]["technical_checks"].clear(),
    lambda x: x["files"].pop("after.png"),
    lambda x: x["files"].update({"after.png": b"changed"}),
    lambda x: x["files"].update({"extra.png": b"unlisted"}),
    lambda x: x["comments"][0]["user"].update(id=99),
    lambda x: x["comments"][0]["user"].update(type="Bot"),
    lambda x: x["comments"][1].update(issue_url="https://api.github.com/repos/org/repo/issues/3"),
    lambda x: x["comments"][1].update(updated_at="2026-11-27T12:00:00Z"),
    lambda x: x["comments"].pop(),
    lambda x: x["watermarks"].update(reviewer=23),
])
def test_refuses_incomplete_or_divergent_contract(change):
    case = make_case()
    change(case)
    with pytest.raises(ValueError):
        gate.validate_external_homologation(**case)


def test_new_rejection_does_not_fall_back_to_old_approval():
    case = make_case()
    latest = copy.deepcopy(case["comments"][1])
    latest.update(id=23, url="https://api.github.com/repos/org/repo/issues/comments/23")
    latest["body"] = latest["body"].replace('"decision":"approved"', '"decision":"rejected"')
    case["comments"].append(latest)
    with pytest.raises(ValueError, match="review statement mismatch"):
        gate.validate_external_homologation(**case)


def reseal(case, *, policy=None, manifest_change=None):
    """Recompute every downstream claim; isolate the semantic refusal under test."""
    if policy is not None:
        raw = gate.canonical(policy)
        case.update(default_policy=raw, base_policy=raw)
        case["identity"]["policy_sha256"] = gate.digest(raw)
    manifest = gate.parse(case["manifest_raw"])
    manifest["identity"] = case["identity"]
    manifest["facts_sha256"] = gate.digest(gate.canonical(case["facts"]))
    manifest["files"] = {name: gate.digest(raw) for name, raw in case["files"].items()}
    if manifest_change:
        manifest_change(manifest)
    case["manifest_raw"] = gate.canonical(manifest)
    owner = {"identity": case["identity"], "manifest_sha256": gate.digest(case["manifest_raw"]), "decision": "observed-pass"}
    case["comments"][0]["body"] = gate.OWNER_PREFIX + gate.canonical(owner).decode()
    review = {**owner, "decision": "approved", "owner_comment_id": case["comments"][0]["id"],
              "owner_comment_sha256": gate.digest(case["comments"][0]["body"].encode()),
              "assurance": gate.parse(case["default_policy"])["assurance"], "separate_context_attested": True}
    case["comments"][1]["body"] = gate.REVIEW_PREFIX + gate.canonical(review).decode()


@pytest.mark.parametrize(("change", "reason"), [
    (lambda x: x["facts"]["environment"].update(tls_verified=False), "unverified HTTPS"),
    (lambda x: x["facts"]["environment"].update(origin="http://preview.example"), "unverified HTTPS"),
    (lambda x: x["facts"]["environment"].update(head_sha="f" * 40), "unverified HTTPS"),
    (lambda x: x["facts"]["external_attempt"].update(result="failed-product"), "external block not established"),
    (lambda x: x["facts"]["technical_checks"]["Technical validation"].update(conclusion="failure"), "technical gate not successful"),
    (lambda x: x["facts"]["technical_checks"]["Technical validation"].update(app_id=999), "technical gate not successful"),
    (lambda x: x["facts"]["technical_checks"]["Technical validation"].update(head_sha="f" * 40), "technical gate not successful"),
    (lambda x: x["files"].pop("after.png"), "required observation missing"),
])
def test_resealed_facts_cannot_override_required_semantics(change, reason):
    case = make_case()
    change(case)
    reseal(case)
    with pytest.raises(ValueError, match=reason):
        gate.validate_external_homologation(**case)


@pytest.mark.parametrize(("change", "reason"), [
    (lambda m: m.update(simulated=True), "wrong evidence identity or kind"),
    (lambda m: m.update(kind="automated-test"), "wrong evidence identity or kind"),
    (lambda m: m["observations"].pop("progress"), "unexpected or missing fields"),
    (lambda m: m["observations"]["progress"].update(result="blocked-external"), "required observation missing"),
    (lambda m: m["observations"]["progress"].update(files=[]), "required observation missing"),
])
def test_resealed_manifest_cannot_claim_false_execution(change, reason):
    case = make_case()
    reseal(case, manifest_change=change)
    with pytest.raises(ValueError, match=reason):
        gate.validate_external_homologation(**case)


@pytest.mark.parametrize(("change", "reason"), [
    (lambda p: p.update(mode="disabled"), "policy disabled"),
    (lambda p: p.update(repository="other/repo"), "policy scope"),
    (lambda p: p.update(assurance=gate.THIRD_PARTY), "assurance/principal mismatch"),
    (lambda p: p["scenarios"]["play"].update(origin="http://preview.example"), "HTTPS origin required"),
    (lambda p: p["scenarios"]["play"].update(origin="https://preview.example/path"), "HTTPS origin required"),
    (lambda p: p["scenarios"]["play"].update(technical_checks={}), "technical checks required"),
])
def test_resealed_policy_still_has_to_meet_invariants(change, reason):
    case = make_case()
    policy = gate.parse(case["default_policy"])
    change(policy)
    reseal(case, policy=policy)
    with pytest.raises(ValueError, match=reason):
        gate.validate_external_homologation(**case)


def test_review_cannot_precede_owner_statement():
    case = make_case()
    case["comments"][1].update(created_at="2026-11-27T10:00:00Z", updated_at="2026-11-27T10:00:00Z")
    with pytest.raises(ValueError, match="review statement mismatch"):
        gate.validate_external_homologation(**case)


def test_edited_prefix_cannot_revive_earlier_review():
    case = make_case()
    prior = copy.deepcopy(case["comments"][1])
    prior.update(id=20, url="https://api.github.com/repos/org/repo/issues/comments/20")
    case["comments"].append(prior)
    case["comments"][1]["body"] = "revoked"
    with pytest.raises(ValueError, match="edited, deleted or superseded"):
        gate.validate_external_homologation(**case)
