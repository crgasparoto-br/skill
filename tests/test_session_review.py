"""Discriminating controls for the explicit single-operator trust model."""
from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
gate = importlib.import_module("session_review")


def policy():
    return {"schema_version": 1, "mode": "enabled", "assurance": gate.ASSURANCE,
            "acknowledgement": gate.ACKNOWLEDGEMENT, "operators": [{"id": 123, "login": "owner"}]}


def fixtures():
    source = "def verify(value):\n    assert value == 'expected'\n"
    identity = {"repository": "owner/repo", "pull_request": 10, "issue": 9,
                "base_ref": "develop", "base_sha": "b" * 40, "head_sha": "a" * 40,
                "merge_preview_sha": "c" * 40, "issue_sha256": "d" * 64, "policy_sha256": "e" * 64}
    packet = {"identity": identity, "requirements": [{"candidate_key": "f" * 64}],
              "certified_at": "2026-10-26T10:00:00Z", "artifact_digest": "sha256:" + "a" * 64,
              "technical_check_ids": [11, 12, 13]}
    report = {"schema_version": 1, "identity": copy.deepcopy(identity), "assurance": gate.ASSURANCE,
              "acknowledgement": gate.ACKNOWLEDGEMENT,
              "sessions": {"implementation": "operator-supplied-implementation", "audit": "operator-supplied-review",
                           "separate_context_attested": True}, "conclusion": "approved", "blocking_findings": [],
              "limitations": [], "requirements": [{"candidate_key": "f" * 64,
              "analysis": "The required value is checked on the actual validation path, with discriminating negative evidence.",
              "sources": [{"path": "head/verify.py", "start_line": 1, "end_line": 2,
                           "sha256": gate.digest(source.rstrip('\n').encode())}],
              "controls": [{"kind": k, "test_case_id": "suite::" + k,
                            "rationale": "This real test exercises the required assertion and rejects the competing behavior."}
                           for k in ("positive", "negative", "regression")]}]}
    comment = {"id": 20, "user": {"id": 123, "login": "owner", "type": "User"},
               "created_at": "2026-10-26T11:00:00Z", "updated_at": "2026-10-26T11:00:00Z",
               "body": gate.PREFIX + json.dumps(report)}
    return packet, report, comment, {"head/verify.py": source}, {"suite::" + k for k in ("positive", "negative", "regression")}


def verify(change=None, *, selected_policy=None):
    packet, report, comment, files, tests = fixtures()
    if change:
        change(packet, report, comment, files, tests)
    comment["body"] = gate.PREFIX + json.dumps(report)
    return gate.verify_review(comment, packet, policy() if selected_policy is None else selected_policy, files, tests)


def test_single_account_can_submit_only_explicitly_limited_review():
    receipt = verify()
    assert receipt["assurance"] == gate.ASSURANCE
    assert receipt["third_party_identity_proven"] is False
    assert receipt["session_separation"] == "operator-declared"
    assert len(receipt["fingerprint"]) == 64
    assert receipt == verify()  # Stable input, stable fingerprint; no recursive audit.


@pytest.mark.parametrize("field,value", [
    ("mode", "disabled"), ("acknowledgement", "independent"), ("assurance", "third-party"),
    ("operators", []), ("schema_version", True), ("schema_version", 2),
])
def test_policy_cannot_silently_downgrade_existing_guarantee(field, value):
    selected = policy()
    selected[field] = value
    with pytest.raises(ValueError):
        verify(selected_policy=selected)


@pytest.mark.parametrize("field,value", [
    ("repository", "other/repo"), ("pull_request", 11), ("issue", 10), ("base_ref", "main"),
    ("base_sha", "f" * 40), ("head_sha", "f" * 40), ("merge_preview_sha", "f" * 40),
    ("issue_sha256", "f" * 64), ("policy_sha256", "f" * 64),
])
def test_stale_or_foreign_report_fails(field, value):
    with pytest.raises(ValueError, match="stale"):
        verify(lambda p, r, *_: r["identity"].update({field: value}))


@pytest.mark.parametrize("field,value", [("id", 999), ("login", "another"), ("type", "Bot")])
def test_operator_is_authenticated_by_account_id_and_login(field, value):
    with pytest.raises(ValueError, match="unauthorized"):
        verify(lambda p, r, c, *_: c["user"].update({field: value}))


@pytest.mark.parametrize("change", [
    lambda p, r, c, f, t: r.update(assurance="cryptographically-independent"),
    lambda p, r, c, f, t: r["sessions"].update(audit=r["sessions"]["implementation"]),
    lambda p, r, c, f, t: r["sessions"].update(separate_context_attested=False),
    lambda p, r, c, f, t: r.update(conclusion="rejected"),
    lambda p, r, c, f, t: r.update(blocking_findings=["unfixed"]),
    lambda p, r, c, f, t: r.update(limitations=["not executed"]),
    lambda p, r, c, f, t: r.update(requirements=[]),
    lambda p, r, c, f, t: r["requirements"][0].update(analysis="passed"),
    lambda p, r, c, f, t: r["requirements"][0].update(candidate_key="0" * 64),
    lambda p, r, c, f, t: r["requirements"][0]["sources"][0].update(sha256="0" * 64),
    lambda p, r, c, f, t: r["requirements"][0]["sources"][0].update(path="../secret"),
    lambda p, r, c, f, t: r["requirements"][0]["sources"][0].update(end_line=300),
    lambda p, r, c, f, t: r["requirements"][0]["controls"][1].update(test_case_id="suite::positive"),
    lambda p, r, c, f, t: r["requirements"][0]["controls"][1].update(rationale="yes"),
    lambda p, r, c, f, t: t.remove("suite::negative"),
    lambda p, r, c, f, t: c.update(updated_at="2026-10-26T12:00:00Z"),
    lambda p, r, c, f, t: p.update(certified_at="2026-10-26T12:00:00Z"),
])
def test_counterexamples_cannot_be_approved(change):
    with pytest.raises(ValueError):
        verify(change)


def test_no_fallback_after_rejection_edit_or_deletion():
    _, report, first, _, _ = fixtures()
    rejected = copy.deepcopy(first)
    rejected["id"] = 21
    report["conclusion"] = "rejected"
    rejected["body"] = gate.PREFIX + json.dumps(report)
    assert gate.latest_review([first, rejected], policy())["id"] == 21
    with pytest.raises(ValueError, match="deleted"):
        gate.latest_review([first], policy(), watermark=21)
    rejected["updated_at"] = "2026-10-26T12:00:00Z"
    with pytest.raises(ValueError, match="edited"):
        gate.latest_review([first, rejected], policy())


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '[]', 'null', '{"x":' + '"x"' * 60001 + '}'],
                         ids=["duplicate", "array", "null", "too-large"])
def test_ambiguous_or_oversized_json_rejected(text):
    with pytest.raises(ValueError):
        gate.strict_json(text)


def test_main_is_bound_to_same_exact_evidence_requirements():
    receipt = verify(lambda p, r, *_: (p["identity"].update(base_ref="main"), r["identity"].update(base_ref="main")))
    assert receipt["identity"]["base_ref"] == "main"
