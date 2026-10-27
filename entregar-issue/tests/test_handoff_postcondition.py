"""Official critical-targeted preparation, literal replay and final handoff integration."""
from __future__ import annotations

import copy
import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import prepare_actions_handoff as producer
import publish_actions_handoff as publisher
import pytest
import require_actions_handoff_certificate as certificate_gate
from audit_artifact_io import artifact_metadata
from certificate_postcondition_replay import parse_command, replay_view
from certificate_replay_io import digest, fresh_layout, json_bytes, run_gate
from handoff_postcondition import file_metadata, verify_finalization

delivery = importlib.import_module("entregar-issue.tests.test_handoff_certificate_contract")
history = importlib.import_module("entregar-issue.tests.test_audit_remediation_gate_replay")
publication = importlib.import_module("entregar-issue.tests.test_publish_actions_handoff")
literal = importlib.import_module("entregar-issue.tests.test_certificate_postcondition_replay")
ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


@pytest.fixture
def critical_case(tmp_path):
    case = literal.make_replay_case(tmp_path)
    out = tmp_path / "official-evidence"
    audit = out / publisher.PREFIX
    audit.mkdir(parents=True)
    files = delivery.build_valid_delivery(audit)
    rejection_args = publication.critical_reaudit_arguments(files, case)
    source = json.loads(case["audit"].read_bytes())
    event = {"repository": {"full_name": "owner/repo"}, "pull_request": {
        "number": 99, "title": "Issue #42: public contract", "body": "",
        "base": {"sha": case["base"], "ref": "develop"},
        "head": {"sha": case["head"], "repo": {"full_name": "owner/repo"}},
    }}
    old_event = copy.deepcopy(event)
    old_event["pull_request"]["head"]["sha"] = case["base"]
    argv = parse_command(case["command"])
    original_inputs = {Path(argv[1]): literal.LEGACY_BYTES, Path(argv[5]): json_bytes(old_event)}
    with fresh_layout(original_inputs, Path(argv[3]), Path(argv[0])):
        original_exit, original_log = run_gate(argv)
    assert original_exit == 2 and b"missing or unsafe certified artifact" in original_log
    source["findings"][0]["failed_gate"].update({
        "observed_exit_code": original_exit, "evidence_sha256": digest(original_log)})
    source_path = audit / "audit-source-result.json"
    write(source_path, source)
    ledger = history.ledger(source_path, case["base"], case["head"], case["command"])
    ledger["status"] = "blocked"
    item = ledger["items"][0]
    item["status"] = "implemented-unverified"
    item["original_failed_gate"].update({"name": source["findings"][0]["failed_gate"]["name"],
                                        "command": case["command"], "exit_code": original_exit,
                                        "evidence_sha256": digest(original_log)})
    item["revalidation"].update({"status": "not-passed", "exit_code": None, "evidence_sha256": None})
    write(audit / "audit-remediation.json", ledger)
    closure = json.loads((audit / "audit-escape-closure.json").read_bytes())
    closure["status"] = "blocked"
    escape = closure["escapes"][0]
    escape["status"] = "blocked"
    escape["literal_case"]["status"] = "not-passed"
    escape["source_audit"].update({"head_sha": case["base"], "audit_report_sha256": digest(source_path.read_bytes())})
    write(audit / "audit-escape-closure.json", closure)
    previous = copy.deepcopy(closure)
    previous["escapes"][0]["revalidated_head_sha"] = case["base"]
    write(audit / "previous-audit-escape-closure.json", previous)
    learning_path = audit / "learning-closure.json"
    learning = json.loads(learning_path.read_bytes())
    learning["source_event"].update({"audit_report_sha256": digest(source_path.read_bytes()),
                                     "audited_head_sha": case["base"]})
    write(learning_path, learning)
    event_path = tmp_path / "official-event.json"
    write(event_path, event)
    write(out / "handoff-preflight.json", {"identity": {
        "repository": "owner/repo", "issue_number": 42, "pull_request_number": 99,
        "material_head_sha": case["head"], "base_sha": case["base"]}})
    log = out / "pytest-exact-head.log"
    log.write_bytes(b"Synthetic upstream test execution for orchestration fixture.\n")
    (out / "pytest-exact-head.xml").write_bytes(b"<testsuite/>\n")
    write(out / "test-execution-facts.json", {"subject_sha": case["head"],
          "execution": {"exit_code": 0, "log_sha256": digest(log.read_bytes())}})
    write(out / "certification-inputs.json", {"subject_sha": case["head"], "evidence_profile": "critical",
        "work_item_start_sha": case["base"], "audit_history": "previous-rejection",
        "remediation_mode": "targeted-remediation", "base_ref": "develop", "head_ref": "feature/contract"})
    cert = audit / "handoff-ready.json"
    builder = ["--repository", "owner/repo", "--issue-number", "42", "--work-item-kind", "pr",
        "--work-item-number", "99", "--pull-request-number", "99", "--base-ref", "develop",
        "--head-ref", "feature/contract", "--work-item-start-sha", case["base"],
        "--issue-changed-path", "README.md", "--head-sha", case["head"], "--base-sha", case["base"],
        "--evidence-profile", "critical", "--specification-snapshot", str(files["snapshot"]),
        "--requirement-closure", str(files["closure"]), "--source-repository-root", str(case["repo"]),
        "--out", str(cert), *rejection_args]
    snapshot = json.loads(files["snapshot"].read_bytes())
    for entry in snapshot["sources"]:
        builder.extend(["--allow-result-path", publisher.PREFIX + entry["path"]])
    return {**case, "out": out, "audit_root": audit, "event": event_path, "certificate": cert,
            "source": source_path, "builder": builder,
            "args": SimpleNamespace(event=event_path, out=out, root=case["repo"], base_ref="develop"),
            "before": {name: (audit / name).read_bytes() for name in
                       ("audit-source-result.json", "audit-remediation.json", "audit-escape-closure.json")}}


def validation_args(case: dict) -> list[str]:
    return ["--certificate", str(case["certificate"]), "--artifacts-dir", str(case["audit_root"]),
            "--head-sha", case["head"], "--base-sha", case["base"], "--repository", "owner/repo",
            "--issue-number", "42", "--work-item-kind", "pr", "--work-item-number", "99",
            "--pull-request-number", "99", "--base-ref", "develop", "--head-ref", "feature/contract",
            "--source-repository-root", str(case["repo"]), "--contract-version", "2026-08-20.3"]


def test_official_critical_postcondition_replays_historical_gate_before_final_handoff(critical_case):
    case = critical_case
    blocked = delivery.run("build_handoff_certificate.py", *case["builder"])
    assert blocked.returncode == 2 and "gate replay must exit 0" in blocked.stdout
    assert not case["certificate"].exists()
    producer.certify(case["args"])
    cert = json.loads(case["certificate"].read_bytes())
    chain = case["audit_root"] / "postcondition"
    prepared = json.loads((chain / "preparation.json").read_bytes())
    assert prepared["phase"] == "preparation" and prepared["status"] == "prepared"
    assert "artifacts" not in prepared and prepared["certificate_commit_policy"]["allowed_paths"] == []
    for name, raw in case["before"].items():
        assert (chain / "prepared" / name).read_bytes() == raw
    assert case["source"].read_bytes() == case["before"]["audit-source-result.json"]
    assert cert["phase"] == "final" and cert["postcondition_proof"]["name"] == "postcondition/proof.json"
    receipt = json.loads((chain / "replay/000/receipt.json").read_bytes())
    assert receipt["command"] == case["command"] and receipt["execution"]["exit_code"] == 0
    assert not case["literal"].exists()
    certificate_gate.verify(case["out"], case["event"], "develop")
    verify_finalization(cert, case["audit_root"], case["repo"], expected_base=case["base"], require_repository=True)
    assert publisher.allowed_paths(cert) == cert["certificate_commit_policy"]["allowed_paths"]
    checked = delivery.run("validate_handoff_certificate.py", *validation_args(case))
    assert checked.returncode == 0, checked.stdout
    aggregator = ROOT.parent / "auditar-issue/scripts/check_delivery_preflight.py"
    checked = subprocess.run([sys.executable, str(aggregator), *validation_args(case)],
                             capture_output=True, text=True, check=False)
    assert checked.returncode == 0, checked.stdout + checked.stderr


@pytest.fixture
def finalized_case(critical_case):
    producer.certify(critical_case["args"])
    return critical_case


@pytest.mark.parametrize("mutation", [
    "missing-proof", "raw-log", "missing-snapshot", "unlisted-snapshot", "snapshot-bytes",
    "rehashed-record", "rehashed-receipt", "allowlist", "wrong-repository", "missing-git",
])
def test_final_certificate_rejects_tampered_postcondition_chain(finalized_case, mutation):
    case = finalized_case
    audit = case["audit_root"]
    cert = json.loads(case["certificate"].read_bytes())
    proof_path = audit / "postcondition/proof.json"
    proof = json.loads(proof_path.read_bytes())
    repo = case["repo"]
    if mutation == "missing-proof":
        cert.pop("postcondition_proof")
    elif mutation == "raw-log":
        path = audit / "postcondition/replay/000/raw.log"
        path.chmod(0o600)
        path.write_bytes(b"forged successful execution\n")
    elif mutation == "missing-snapshot":
        (audit / "postcondition/prepared/requirement-closure.json").unlink()
    elif mutation == "unlisted-snapshot":
        write(audit / "postcondition/prepared/unlisted.json", {})
    elif mutation == "snapshot-bytes":
        path = audit / "postcondition/prepared/requirement-closure.json"
        path.write_bytes(path.read_bytes() + b"\n")
    elif mutation == "rehashed-record":
        path = audit / "audit-remediation.json"
        value = json.loads(path.read_bytes())
        value["items"][0]["changed_files"].append("unrelated/material.py")
        write(path, value)
        cert["artifacts"]["audit_remediation"] = artifact_metadata(path)
    elif mutation == "rehashed-receipt":
        path = audit / proof["receipts"][0]["name"]
        value = json.loads(path.read_bytes())
        value["execution"]["exit_code"] = False
        path.chmod(0o600)
        write(path, value)
        proof["receipts"][0].update(file_metadata(path, audit))
        write(proof_path, proof)
        cert["postcondition_proof"] = file_metadata(proof_path, audit)
    elif mutation == "allowlist":
        cert["certificate_commit_policy"]["allowed_paths"].append(publisher.PREFIX + "unreviewed.json")
    elif mutation == "wrong-repository":
        path = audit / proof["preparation"]["name"]
        value = json.loads(path.read_bytes())
        value["subject"]["repository"] = cert["subject"]["repository"] = "another/repository"
        write(path, value)
        proof["preparation"] = file_metadata(path, audit)
        write(proof_path, proof)
        cert["postcondition_proof"] = file_metadata(proof_path, audit)
    else:
        repo = None
    with pytest.raises((ValueError, OSError)):
        verify_finalization(cert, audit, repo, expected_base=case["base"], require_repository=True)


@pytest.mark.parametrize("option,bad_value", [
    ("--base-sha", "f" * 40), ("--head-sha", "e" * 40), ("--repository", "another/repository"),
], ids=["base", "head", "repository"])
def test_certificate_identity_rejection_precedes_postcondition_execution(finalized_case, monkeypatch, option, bad_value):
    import handoff_postcondition
    import validate_handoff_certificate as validator

    case = finalized_case
    calls = []
    actual = handoff_postcondition.verify_finalization

    def observed(*args, **kwargs):
        calls.append(args[0]["identity"]["material_head_sha"])
        return actual(*args, **kwargs)

    monkeypatch.setattr(handoff_postcondition, "verify_finalization", observed)
    argv = validation_args(case)
    monkeypatch.setattr(sys, "argv", ["validate_handoff_certificate.py", *argv])
    assert validator.main() == 0 and calls == [case["head"]]
    calls.clear()
    argv[argv.index(option) + 1] = bad_value
    monkeypatch.setattr(sys, "argv", ["validate_handoff_certificate.py", *argv])
    assert validator.main() == 2
    assert calls == []


@pytest.mark.parametrize("marker", ["intact", "phase-removed", "map-removed"])
def test_preparation_cannot_authorize_current_handoff_consumers(finalized_case, tmp_path, marker):
    case = finalized_case
    path = case["audit_root"] / "postcondition/preparation.json"
    prepared = json.loads(path.read_bytes())
    view = tmp_path / "compatibility-view"
    for relative, raw in replay_view(prepared, digest(path.read_bytes())).items():
        destination = view / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    certificate = view / publisher.CERTIFICATE
    payload = json.loads(certificate.read_bytes())
    if marker != "intact":
        payload.pop("phase")
    if marker == "map-removed":
        payload.pop("prepared_artifacts")
    write(certificate, payload)
    with pytest.raises(ValueError, match="preparation"):
        certificate_gate.verify(view, case["event"], "develop")
    with pytest.raises(ValueError, match="preparation"):
        publisher.allowed_paths(payload)
    arguments = validation_args(case)
    arguments[arguments.index("--certificate") + 1] = str(certificate)
    checked = delivery.run("validate_handoff_certificate.py", *arguments)
    assert checked.returncode == 2 and "preparation" in checked.stdout
    child = "d" * 40
    checked = delivery.run("validate_terminal_handoff.py", "--certificate", str(certificate),
        "--repository", "owner/repo", "--issue-number", "42", "--work-item-kind", "pr",
        "--work-item-number", "99", "--pull-request-number", "99", "--base-sha", case["base"],
        "--artifacts-dir", str(case["audit_root"]), "--material-head-sha", case["head"],
        "--published-head-sha", child, "--published-parent-sha", case["head"],
        "--published-changed-path", publisher.CERTIFICATE, "--current-head-sha", child,
        "--current-parent-sha", case["head"], "--current-changed-path", publisher.CERTIFICATE)
    assert checked.returncode == 2 and "preparation" in checked.stdout


def test_preparation_without_markers_still_lacks_legacy_artifact_authority(finalized_case, tmp_path):
    case = finalized_case
    path = case["audit_root"] / "postcondition/preparation.json"
    payload = json.loads(path.read_bytes())
    for field in ("phase", "prepared_artifacts", "prepared_files", "postcondition_plan", "release_authority"):
        payload.pop(field)
    payload["status"] = "ready"
    stripped = tmp_path / "stripped.json"
    write(stripped, payload)
    args = validation_args(case)
    args[args.index("--certificate") + 1] = str(stripped)
    checked = delivery.run("validate_handoff_certificate.py", *args)
    assert checked.returncode == 2 and "lacks artifact" in checked.stdout
