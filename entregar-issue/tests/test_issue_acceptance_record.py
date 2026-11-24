"""Positive, negative, adversarial and CLI tests for issue acceptance evidence records."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("record_issue_acceptance", SCRIPTS / "record_issue_acceptance.py")
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)

SHA = "a" * 40
BODY = "## Critérios de aceite\n\n- [ ] Um\n- [x] Dois\n- [ ] Terceiro\n"


def audit(statuses=("verified", "failed", "unknown"), body=BODY):
    items = mod.analyze_body(body)[1]
    return {
        "subject_sha": SHA, "validity": "independent",
        "audit_url": "https://github.com/sample/repo/pull/5#pullrequestreview-123",
        "criteria": [
            {"ordinal": item["ordinal"], "text": item["text"],
             "original_checked": item["checked"], "status": status,
             "evidence": ["test:negative; sha=" + SHA]
             if status in ("verified", "failed", "partial", "not-applicable") else []}
            for item, status in zip(items, statuses, strict=True)
        ],
    }


def record(body=BODY, data=None):
    return mod.render_record(body, body, data or audit(body=body), "sample/repo", 7, 5, SHA)


def test_records_every_criterion_and_does_not_claim_approval_or_issue_write():
    payload = mod.parse_record(record())
    assert payload["issue_number"] == 7
    assert payload["material_sha"] == SHA
    assert payload["issue_body_modified"] is False
    assert payload["approval_granted"] is False
    assert payload["audit_authenticated"] == "CONTROLLER_MUST_VERIFY"
    assert [(item["verified"], item["observed_checked"]) for item in payload["criteria"]] == [
        (True, False), (False, True), (False, False),
    ]
    assert record() == record()


def test_idempotency_and_conflict_detection_without_overwriting():
    expected = record()
    assert mod.publication_decision(expected, []) == "publish"
    assert mod.publication_decision(expected, [{"body": "ordinary comment"}]) == "publish"
    assert mod.publication_decision(expected, [{"body": expected}, {"body": expected}]) == "already-recorded"
    different = record(data=audit(("verified", "verified", "unknown")))
    with pytest.raises(ValueError, match="Conflicting"):
        mod.publication_decision(expected, [{"body": different}])


def test_other_material_sha_is_never_reused():
    wanted = record()
    previous = mod.parse_record(wanted)
    previous["material_sha"] = "b" * 40
    other = mod.MARKER + json.dumps(previous, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert mod.publication_decision(wanted, [{"body": other}]) == "publish"


@pytest.mark.parametrize("bad", [
    "prefix " + mod.MARKER + "{}",
    mod.MARKER + "{}",
    mod.MARKER + "{bad-json}",
    mod.MARKER + '{"schema_version":2}',
])
def test_malformed_or_forged_records_fail_closed(bad):
    with pytest.raises(ValueError):
        mod.parse_record(bad)


def test_false_approval_in_comment_is_rejected():
    payload = mod.parse_record(record())
    payload["approval_granted"] = True
    with pytest.raises(ValueError, match="approval"):
        mod.parse_record(mod.MARKER + json.dumps(payload))


def test_not_applicable_requires_locatable_evidence_in_record():
    data = audit(("not-applicable", "unknown", "unknown"))
    data["criteria"][0]["evidence"] = []
    with pytest.raises(ValueError, match="not-applicable decisions require locatable evidence"):
        record(data=data)

    accepted = mod.parse_record(record(data=audit(("not-applicable", "unknown", "unknown"))))
    assert accepted["criteria"][0]["status"] == "not-applicable"
    assert accepted["criteria"][0]["evidence"]


def test_pre_audit_or_stale_sha_and_missing_decisions_rejected():
    data = audit()
    data["validity"] = "pre-audit"
    with pytest.raises(ValueError, match="review/attestation"):
        record(data=data)
    data = audit()
    data["subject_sha"] = "b" * 40
    with pytest.raises(ValueError, match="SHA"):
        record(data=data)
    data = audit()
    data["criteria"].pop()
    with pytest.raises(ValueError, match="Every criterion"):
        record(data=data)


def test_drift_and_multiline_identity_ambiguity_are_rejected():
    with pytest.raises(ValueError, match="changed"):
        mod.render_record(BODY, BODY.replace("Terceiro", "Quarto"), audit(),
                          "sample/repo", 7, 5, SHA)
    body = "## Critérios de aceite\n- [ ] Proteger\n  também outro tenant\n"
    data = audit(("verified",), body)
    data["criteria"][0]["text"] = "Proteger"
    with pytest.raises(ValueError, match="identity"):
        record(body, data)


def test_readback_rejects_comment_race_issue_change_and_head_drift():
    expected = record()
    result = mod.check_comment_readback(expected, expected, BODY, SHA, SHA, 123)
    assert result["comment_match"] is True
    assert result["approval"] == "NOT_ASSERTED"
    with pytest.raises(ValueError, match="comment read-back"):
        mod.check_comment_readback(expected, expected + "\n", BODY, SHA, SHA, 123)
    with pytest.raises(ValueError, match="issue-body drift"):
        mod.check_comment_readback(expected, expected, BODY + "extra", SHA, SHA, 123)
    with pytest.raises(ValueError, match="material SHA"):
        mod.check_comment_readback(expected, expected, BODY, SHA, "b" * 40, 123)
    with pytest.raises(ValueError, match="comment ID"):
        mod.check_comment_readback(expected, expected, BODY, SHA, SHA, 0)


def test_cli_renders_and_checks_offline_readback(tmp_path, monkeypatch, capsys):
    body_file = tmp_path / "issue.md"
    body_file.write_text(BODY, encoding="utf-8")
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(json.dumps(audit()), encoding="utf-8")
    result_file = tmp_path / "record.md"
    base = [
        "record_issue_acceptance.py", "--audited-body", str(body_file),
        "--current-body", str(body_file), "--audit", str(audit_file),
        "--repository", "sample/repo", "--issue-number", "7", "--pull-request-number", "5",
        "--material-sha", SHA, "--output", str(result_file),
    ]
    monkeypatch.setattr(sys, "argv", base)
    assert mod.main() == 0
    rendered = result_file.read_text(encoding="utf-8")
    assert rendered == record()
    assert json.loads(capsys.readouterr().out)["remote_write"] is False
    observed = tmp_path / "observed.md"
    observed.write_text(rendered, encoding="utf-8")
    options = [
        *base, "--readback-comment", str(observed), "--readback-issue-body", str(body_file),
        "--observed-material-sha", SHA, "--observed-comment-id", "123",
    ]
    monkeypatch.setattr(sys, "argv", options)
    assert mod.main() == 0
    assert json.loads(capsys.readouterr().out)["readback"]["comment_match"] is True
    monkeypatch.setattr(sys, "argv", options[:-2])
    with pytest.raises(ValueError, match="All read-back arguments"):
        mod.main()


def test_invalid_target_identity_is_rejected():
    with pytest.raises(ValueError, match="owner/repository"):
        mod.render_record(BODY, BODY, audit(), "wrong", 7, 5, SHA)
    with pytest.raises(ValueError, match="positive integers"):
        mod.render_record(BODY, BODY, audit(), "sample/repo", True, 5, SHA)
