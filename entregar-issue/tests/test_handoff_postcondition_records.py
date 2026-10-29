"""Record transition controls, reusing the existing audit and escape fixtures."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
import sys
from pathlib import Path

import handoff_postcondition_records as records
import pytest
from validate_audit_remediation import validate_ledger

replay_fixture = importlib.import_module("entregar-issue.tests.test_audit_remediation_gate_replay")
escape_fixture = importlib.import_module("entregar-issue.tests.test_independent_rejection_closure")
literal_fixture = importlib.import_module("entregar-issue.tests.test_certificate_postcondition_replay")
delivery_fixture = importlib.import_module("entregar-issue.tests.test_handoff_certificate_contract")
HEAD = "2" * 40
BASE = "1" * 40


@pytest.fixture
def prepared_records(tmp_path):
    """Synthetic receipt facts below exercise the pure oracle, never authenticity."""
    source = replay_fixture.audit(BASE)
    command = "/usr/bin/python /review/entregar-issue/scripts/require_actions_handoff_certificate.py --evidence-dir /review/evidence --event /review/event.json --base-ref develop"
    source["findings"][0]["failed_gate"]["command"] = command
    source_path = tmp_path / "audit.json"
    replay_fixture.write(source_path, source)
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    ledger = replay_fixture.ledger(source_path, BASE, HEAD, command)
    ledger["status"] = "blocked"
    item = ledger["items"][0]
    item["original_failed_gate"]["command"] = command
    item["status"] = "implemented-unverified"
    item["history"] = {"observed": "Original failure is retained; no successful replay exists yet."}
    item["revalidation"].update({"status": "not-passed", "exit_code": None, "evidence_sha256": None})
    escape = escape_fixture.escape(source["rejection_id"], "F-GATE-001")
    escape["status"] = "blocked"
    escape["literal_case"]["status"] = "not-passed"
    escape["literal_case"]["observed"] = "The literal original gate has not passed."
    escape["source_audit"].update({"head_sha": BASE, "audit_report_sha256": source_sha})
    escape["revalidated_head_sha"] = HEAD
    closure = {"schema_version": 1, "status": "blocked", "escapes": [escape]}
    plan = {
        "schema_version": 1, "type": records.PLAN_TYPE, "material_head_sha": HEAD,
        "base_sha": BASE, "audit_report_sha256": source_sha, "rejection_id": source["rejection_id"],
        "trusted_anchor_sha": BASE, "repository": "owner/repo", "items": [{
            "source_kind": "finding", "source_id": "F-GATE-001", "command": command,
            "argv": command.split(), "gate_path": "entregar-issue/scripts/require_actions_handoff_certificate.py",
            "gate_source_sha256": "c" * 64, "gate_blob_sha": "d" * 40,
            "original_subject_sha": BASE, "original_exit_code": 1,
        }],
    }
    receipt = {
        "schema_version": 1, "kind": records.REPLAY_KIND, "source_kind": "finding", "source_id": "F-GATE-001",
        "command": command, "argv": command.split(), "equivalence": "exact-command-replay",
        "identity": {"material_head_sha": HEAD, "base_sha": BASE, "repository": "owner/repo"},
        "trusted_source": {"anchor": BASE, "path": plan["items"][0]["gate_path"], "sha256": "c" * 64, "git_blob": "d" * 40},
        "preparation_sha256": "e" * 64, "receipt_sha256": "f" * 64,
        "execution": {"exit_code": 0, "raw_log_path": "raw.log", "raw_log_sha256": "9" * 64},
    }
    return {"source": source, "source_path": source_path, "source_sha": source_sha,
            "ledger": ledger, "closure": closure, "plan": plan,
            "receipts": {("finding", "F-GATE-001"): receipt}}


def validate_prepared(case):
    records.validate_preparation_records(
        ledger=case["ledger"], escape_closure=case["closure"], plan=case["plan"],
        audit_report=case["source"], audit_report_sha256=case["source_sha"], head_sha=HEAD,
    )


def test_postcondition_records_preserve_history_and_close_only_verified_fields(prepared_records):
    case = prepared_records
    before = copy.deepcopy(case)
    validate_prepared(case)
    final = records.expected_final_records(case["ledger"], case["closure"], case["plan"], case["receipts"])
    assert case == before
    assert not validate_ledger(final["audit_remediation"], case["source"], case["source_sha"], HEAD)
    assert records.finalization_projection(case["ledger"], case["closure"], case["plan"]) == records.finalization_projection(
        final["audit_remediation"], final["audit_escape_closure"], case["plan"])
    item = final["audit_remediation"]["items"][0]
    literal = final["audit_escape_closure"]["escapes"][0]["literal_case"]
    assert item["status"] == "fixed" and literal["status"] == "passed"
    assert item["revalidation"]["evidence_sha256"] == "9" * 64
    assert item["revalidation"]["replay_evidence"] == literal["replay_evidence"]
    assert literal["observed"] == before["closure"]["escapes"][0]["literal_case"]["observed"]
    assert item["history"] == before["ledger"]["items"][0]["history"]


@pytest.mark.parametrize("mutation", ["exit-null", "exit-failed", "exit-boolean", "wrong-id", "wrong-command", "wrong-head", "wrong-base", "wrong-anchor", "wrong-source", "missing-log", "missing-receipt"])
def test_postcondition_transition_rejects_substituted_replay_facts(prepared_records, mutation):
    case = prepared_records
    receipt = next(iter(case["receipts"].values()))
    if mutation.startswith("exit-"):
        receipt["execution"]["exit_code"] = {"exit-null": None, "exit-failed": 2, "exit-boolean": False}[mutation]
    elif mutation == "wrong-id":
        receipt["source_id"] = "F-OTHER"
    elif mutation == "wrong-command":
        receipt["command"] += " --skip-check"
    elif mutation == "wrong-head":
        receipt["identity"]["material_head_sha"] = BASE
    elif mutation == "wrong-base":
        receipt["identity"]["base_sha"] = HEAD
    elif mutation == "wrong-anchor":
        receipt["trusted_source"]["anchor"] = HEAD
    elif mutation == "wrong-source":
        receipt["trusted_source"]["sha256"] = "0" * 64
    elif mutation == "missing-log":
        receipt["execution"]["raw_log_sha256"] = None
    else:
        case["receipts"].clear()
    with pytest.raises(ValueError):
        records.expected_final_records(case["ledger"], case["closure"], case["plan"], case["receipts"])


@pytest.mark.parametrize("mutation", ["claimed-pass", "claimed-hash", "changed-source-command", "changed-failure", "stale-head", "missing-validation", "changed-mode"])
def test_preparation_accepts_only_exact_blocked_postconditions(prepared_records, mutation):
    case = prepared_records
    item = case["ledger"]["items"][0]
    if mutation == "claimed-pass":
        item["revalidation"]["exit_code"] = 0
    elif mutation == "claimed-hash":
        item["revalidation"]["evidence_sha256"] = "b" * 64
    elif mutation == "changed-source-command":
        item["original_failed_gate"]["command"] += " "
    elif mutation == "changed-failure":
        item["original_failed_gate"]["evidence_sha256"] = "0" * 64
    elif mutation == "stale-head":
        item["revalidation"]["subject_sha"] = BASE
    elif mutation == "missing-validation":
        item["validations"] = []
    else:
        item["remediation_mode"] = "systemic-remediation"
    with pytest.raises(ValueError):
        validate_prepared(case)


def test_preparation_keeps_unrelated_failed_gate_strict(prepared_records):
    case = prepared_records
    source = replay_fixture.audit(BASE)["findings"][0]
    source["id"] = "F-UNRELATED"
    case["source"]["findings"].append(source)
    replay_fixture.write(case["source_path"], case["source"])
    case["source_sha"] = hashlib.sha256(case["source_path"].read_bytes()).hexdigest()
    case["plan"]["audit_report_sha256"] = case["source_sha"]
    case["ledger"]["source"]["audit_report_sha256"] = case["source_sha"]
    case["closure"]["escapes"][0]["source_audit"]["audit_report_sha256"] = case["source_sha"]
    other = replay_fixture.ledger(case["source_path"], BASE, HEAD, "npm run format:check")["items"][0]
    other["source_id"] = "F-UNRELATED"
    case["ledger"]["items"].append(other)
    validate_prepared(case)
    other["revalidation"]["exit_code"] = None
    with pytest.raises(ValueError, match="gate replay must exit 0"):
        validate_prepared(case)
    other["status"] = "implemented-unverified"
    with pytest.raises(ValueError, match="unselected audit item"):
        validate_prepared(case)


@pytest.mark.parametrize("mutation", ["other-report", "other-rejection", "other-original-head", "mixed-finding", "duplicate", "claimed-pass", "sibling-failed"])
def test_pending_escape_is_bound_to_exact_original_finding(prepared_records, mutation):
    case = prepared_records
    escape = case["closure"]["escapes"][0]
    if mutation == "other-report":
        escape["source_audit"]["audit_report_sha256"] = "0" * 64
    elif mutation == "other-rejection":
        escape["source_audit"]["rejection_id"] = "audit-rejection:another-001"
    elif mutation == "other-original-head":
        escape["source_audit"]["head_sha"] = HEAD
    elif mutation == "mixed-finding":
        escape["source_audit"]["finding_ids"] = ["F-OTHER"]
    elif mutation == "duplicate":
        case["closure"]["escapes"].append(copy.deepcopy(escape))
    elif mutation == "claimed-pass":
        escape["literal_case"]["status"] = "passed"
    else:
        escape["sibling_cases"][0]["status"] = "not-passed"
    with pytest.raises(ValueError):
        validate_prepared(case)


def test_preparation_plan_is_not_accepted_as_final_authority(tmp_path):
    with pytest.raises(ValueError, match="final validation cannot use"):
        records.phase_plan("final", tmp_path / "plan.json", None, None, None, None)
    with pytest.raises(ValueError, match="authenticated base"):
        records.phase_plan("preparation", tmp_path / "plan.json", Path("audit.json"), Path("repo"), HEAD, None)


def test_default_remediation_validation_rejects_blocked_preparation(prepared_records):
    case = prepared_records
    errors = validate_ledger(case["ledger"], case["source"], case["source_sha"], HEAD)
    assert any("ledger is not closed" in error for error in errors)
    assert any("gate replay must exit 0" in error for error in errors)
    assert any("evidence_sha256" in error for error in errors)


@pytest.fixture
def authenticated_records(tmp_path):
    """Reuse real frozen-gate/Git and complete critical evidence fixtures."""
    case = literal_fixture.make_replay_case(tmp_path)
    source = json.loads(case["audit"].read_bytes())
    ledger = replay_fixture.ledger(case["audit"], case["base"], case["head"], case["command"])
    ledger["status"] = "blocked"
    item = ledger["items"][0]
    item["status"] = "implemented-unverified"
    item["original_failed_gate"].update({key: source["findings"][0]["failed_gate"][key] for key in ("name", "command")})
    item["revalidation"].update({"status": "not-passed", "exit_code": None, "evidence_sha256": None})
    escape = escape_fixture.escape(source["rejection_id"], case["source_id"])
    escape.update({"status": "blocked", "revalidated_head_sha": case["head"]})
    escape["literal_case"]["status"] = "not-passed"
    escape["source_audit"].update({"head_sha": case["base"], "audit_report_sha256": ledger["source"]["audit_report_sha256"]})
    target = json.loads(case["preparation"].read_bytes())["subject"]
    case["escape_subject"] = target
    closure = {"schema_version": 1, "status": "blocked",
               "subject": {"repository": target["repository"], "issue_number": target["issue_number"],
                           "pull_request_number": target["pull_request_number"],
                           "material_head_sha": case["head"]},
               "escapes": [escape]}
    learning = escape_fixture.learning(rejection_id=source["rejection_id"])
    learning["source_event"].update({"finding_ids": [case["source_id"]], "audit_report_sha256": ledger["source"]["audit_report_sha256"]})
    for name, value in (("ledger", ledger), ("escape", closure), ("learning", learning), ("previous", {"schema_version": 1, "escapes": []})):
        case[name] = tmp_path / (name + ".json")
        literal_fixture.write_json(case[name], value)
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    case["delivery"] = delivery_fixture.build_valid_delivery(delivery)
    for path in case["delivery"].values():
        path.write_text(path.read_text().replace(json.dumps(delivery_fixture.HEAD), json.dumps(case["head"])))
    from audit_artifact_io import artifact_metadata
    prepared = json.loads(case["preparation"].read_bytes())
    for role, path in (("audit_remediation", case["ledger"]), ("audit_escape_closure", case["escape"])):
        target = case["preparation"].parent / "prepared" / path.name
        target.write_bytes(path.read_bytes())
        meta = {**artifact_metadata(target), "name": "prepared/" + path.name}
        prepared["prepared_artifacts"][role] = meta
        prepared["prepared_files"].append({key: meta[key] for key in ("name", "sha256")})
    literal_fixture.write_json(case["preparation"], prepared)
    return case


def preparation_command(case, role):
    scripts = {"remediation": "validate_audit_remediation", "lineage": "validate_audit_escape_lineage",
               "rejection": "validate_independent_rejection_closure", "readiness": "validate_handoff_readiness"}
    command = [sys.executable, str(replay_fixture.ROOT / "scripts" / (scripts[role] + ".py")),
               "--repository", str(case["repo"]), "--head-sha", case["head"], "--base-sha", case["base"],
               "--audit-result", str(case["audit"])]
    if role == "remediation":
        return [*command, "--ledger", str(case["ledger"])]
    command += ["--audit-remediation", str(case["ledger"])]
    if role == "readiness":
        target = case["escape_subject"]
        return [*command, "--requirement-closure", str(case["delivery"]["closure"]),
                          "--target-repository", target["repository"],
                          "--issue-number", str(target["issue_number"]),
                          "--pull-request-number", str(target["pull_request_number"]),
                          "--previous-independent-rejection",
                          "--audit-escape-closure", str(case["escape"]), "--learning-closure", str(case["learning"]),
                          "--previous-audit-escape-closure", str(case["previous"])]
    command += ["--closure", str(case["escape"])]
    if role == "lineage":
        return [*command, "--require-previous", "--previous-closure", str(case["previous"])]
    return [*command, "--learning-closure", str(case["learning"])]


@pytest.mark.parametrize("role", ["remediation", "lineage", "rejection", "readiness"])
def test_preparation_validators_authenticate_plan_and_keep_final_blocked(authenticated_records, role):
    case = authenticated_records
    originals = {name: case[name].read_bytes() for name in ("audit", "ledger", "escape", "learning")}
    command = preparation_command(case, role)
    prep = [*command, "--phase", "preparation", "--postcondition-plan", str(case["plan"])]
    result = subprocess.run(prep, check=False, capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.startswith("PREPARED:"), result.stdout + result.stderr
    assert "READY:" not in result.stdout
    final = subprocess.run(command, check=False, capture_output=True, text=True)
    assert final.returncode == 2 and "BLOCK:" in final.stdout
    changed = json.loads(case["plan"].read_bytes())
    changed["items"][0]["source_id"] = "F-SUBSTITUTED"
    literal_fixture.write_json(case["plan"], changed)
    rejected = subprocess.run(prep, check=False, capture_output=True, text=True)
    assert rejected.returncode == 2 and "plan differs" in rejected.stdout
    assert {name: case[name].read_bytes() for name in originals} == originals


@pytest.mark.parametrize("role", ["rejection", "readiness"])
def test_preparation_rejects_learning_from_another_audit(authenticated_records, role):
    case = authenticated_records
    learning = json.loads(case["learning"].read_bytes())
    learning["source_event"]["audit_report_sha256"] = "0" * 64
    literal_fixture.write_json(case["learning"], learning)
    command = [*preparation_command(case, role), "--phase", "preparation", "--postcondition-plan", str(case["plan"])]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    assert result.returncode == 2 and "learning event differs" in result.stdout


def finalized(case, ledger=None, receipt_path=None):
    return records.finalize_records(
        ledger=json.loads(case["ledger"].read_bytes()) if ledger is None else ledger,
        escape_closure=json.loads(case["escape"].read_bytes()), audit_result=case["audit"], plan_path=case["plan"],
        preparation=case["preparation"], event=case["event"],
        receipts={(case["source_kind"], case["source_id"]): receipt_path or case["output"] / "receipt.json"},
        repository=case["repo"], head_sha=case["head"], expected_base=case["base"],
    )


def test_finalization_requires_real_replay_and_exact_prepared_records(authenticated_records):
    case = authenticated_records
    before = {name: case[name].read_bytes() for name in ("audit", "ledger", "escape", "preparation")}
    with pytest.raises(FileNotFoundError):
        finalized(case)
    literal_fixture.execute(case)
    result = finalized(case)
    assert result["audit_remediation"]["status"] == "closed"
    assert result["audit_escape_closure"]["escapes"][0]["literal_case"]["status"] == "passed"
    raw = (case["output"] / "raw.log").read_bytes()
    assert result["audit_remediation"]["items"][0]["revalidation"]["evidence_sha256"] == hashlib.sha256(raw).hexdigest()
    swapped = json.loads(case["ledger"].read_bytes())
    swapped["items"][0]["validations"].append("a different semantic check")
    with pytest.raises(ValueError, match="differs from authenticated preparation"):
        finalized(case, ledger=swapped)
    receipt_path = case["output"] / "receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["execution"]["exit_code"] = None
    receipt_path.chmod(0o600)
    literal_fixture.write_json(receipt_path, receipt)
    receipt_path.chmod(0o400)
    with pytest.raises(ValueError, match="successful authenticated execution"):
        finalized(case, receipt_path=receipt_path)
    assert {name: case[name].read_bytes() for name in before} == before
