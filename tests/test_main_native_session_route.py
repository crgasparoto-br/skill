"""The protected main evidence route does not create review or release authority."""
from __future__ import annotations

import hashlib
import importlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "entregar-issue/scripts/resolve_trusted_audit_transport.py"
MAIN = "docs/audit/github-native-main-contract.json"
DEVELOP = "docs/audit/github-native-contract.json"
REPOSITORY = "crgasparoto-br/skill"

sys.path.insert(0, str(ROOT / "scripts"))
facts = importlib.import_module("session_review_github")
gate = importlib.import_module("verify_independent_pr_audit")
runner = importlib.import_module("verify_session_review")


def git(path, *command):
    return subprocess.check_output(["git", "-C", str(path), *command], text=True).strip()


def put(repo, path, data):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def commit(repo, description):
    git(repo, "add", ".")
    git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-m", description)
    return git(repo, "rev-parse", "HEAD")


def run_transport(repo, branch, base, head):
    return subprocess.run([sys.executable, str(TOOL), "--root", str(repo),
                           "--repository", REPOSITORY, "--base-ref", branch,
                           "--base-sha", base, "--head-sha", head],
                          check=False, capture_output=True, text=True)


def test_cli_requires_immutable_branch_specific_contract(tmp_path):
    repo = tmp_path
    git(repo, "init", "-q")
    put(repo, DEVELOP, (ROOT / DEVELOP).read_bytes())
    old_main = commit(repo, "base without distinct main policy")
    put(repo, MAIN, (ROOT / MAIN).read_bytes())
    new_main = commit(repo, "installed authorized main policy")
    observed = run_transport(repo, "main", old_main, new_main)
    assert observed.returncode == 2 and "trusted main native audit contract unavailable" in observed.stderr
    assert not observed.stdout
    main = run_transport(repo, "main", new_main, new_main)
    assert main.returncode == 0, main.stderr
    assert json.loads(main.stdout)["contract"]["path"] == MAIN
    develop = run_transport(repo, "develop", old_main, new_main)
    assert develop.returncode == 0, develop.stderr
    assert json.loads(develop.stdout)["contract"]["path"] == DEVELOP

    # Changing only a candidate's declaration cannot replace the installed policy.
    put(repo, MAIN, (ROOT / DEVELOP).read_bytes())
    changed = commit(repo, "candidate claims another branch's audit declaration")
    expected = {**json.loads(main.stdout), "material_head_sha": changed}
    assert json.loads(run_transport(repo, "main", new_main, changed).stdout) == expected
    # Once the wrong branch policy is used as base the CLI refuses it.
    assert "incomplete or foreign" in run_transport(repo, "main", changed, changed).stderr


@pytest.mark.parametrize("state", ["valid", "missing", "develop", "legacy", "wrong-hash"])
def test_session_reads_only_authenticated_base_main_policy(monkeypatch, state):
    refs = []
    data = json.loads((ROOT / MAIN).read_bytes())
    if state == "develop":
        data["base_ref"] = "develop"
    if state == "legacy":
        data["legacy_handoff_policy"] = "not-required"
    raw = json.dumps(data).encode()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False).hexdigest()

    def read(repo, path, ref):
        refs.append((repo, path, ref))
        if state == "missing":
            raise ValueError("no policy (HTTP 404)")
        return raw, "0" * 40 if state == "wrong-hash" else blob

    monkeypatch.setattr(runner, "content", read)
    identity = {"repository": REPOSITORY, "base_ref": "main", "base_sha": "b" * 40, "head_sha": "a" * 40}
    if state == "valid":
        assert runner.trusted_audit_transport(identity)["mode"] == "native-github-audit"
    else:
        with pytest.raises(ValueError):
            runner.trusted_audit_transport(identity)
    assert refs == [(REPOSITORY, MAIN, identity["base_sha"])]


@pytest.mark.parametrize("source", [gate.HANDOFF, gate.NATIVE_EVIDENCE, gate.MAIN_NATIVE_EVIDENCE])
def test_main_cannot_accept_legacy_or_develop_workflow_check(source):
    def check(name, index):
        return {"name": name, "id": index, "head_sha": "a" * 40, "status": "completed",
                "conclusion": "success", "app": {"id": gate.APP_ID}}
    checks = {"check_runs": [check(name, i) for i, name in enumerate((*gate.TECHNICAL, source), start=1)]}
    if source == gate.MAIN_NATIVE_EVIDENCE:
        gate.required_checks_green(checks, "a" * 40, "main", lambda *_: True,
                                   audit_transport="native-github-audit")
    else:
        with pytest.raises(gate.RequiredChecksNotReadyError, match="main native audit evidence"):
            gate.required_checks_green(checks, "a" * 40, "main", lambda *_: True,
                                       audit_transport="native-github-audit")
    if source == gate.NATIVE_EVIDENCE:
        gate.required_checks_green(checks, "a" * 40, "develop", lambda *_: True,
                                   audit_transport="native-github-audit")


def test_main_rejects_direct_legacy_certificate_before_reading_zip(tmp_path, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "offline-fixture-only")
    identity = {"repository": REPOSITORY, "base_ref": "main", "pull_request": 19,
                "head_sha": "a" * 40, "base_sha": "b" * 40}

    def no_io(*_, **__):
        pytest.fail("legacy policy cannot trigger any authenticated artifact read")

    with pytest.raises(ValueError, match="main requires authenticated native audit transport"):
        facts.certified_evidence(identity, {}, tmp_path, api=no_io, unpack=no_io,
                                 authenticated_certificate_event=no_io,
                                 authenticated_preview_reconciliation=no_io, root=ROOT)


def test_main_workflow_isolated_and_never_a_release_or_review_issuer():
    def load(path):
        return yaml.load((ROOT / ".github/workflows" / path).read_text(), Loader=yaml.BaseLoader)

    current = load("main-native-evidence.yml")
    assert current["on"]["pull_request"]["branches"] == ["main"]
    assert set(current["on"]) == {"pull_request"}
    assert current["permissions"] and set(current["permissions"].values()) == {"read"}
    verify = current["jobs"]["verify"]
    assert verify["name"] == gate.MAIN_NATIVE_EVIDENCE
    assert verify["needs"] == "collect"
    assert all("python -m pytest" not in step.get("run", "") for step in verify["steps"])
    assert any("--verify --head" in step.get("run", "") for step in verify["steps"])
    for key, prefix in (("verify", "trusted-main-validator"), ("collect", "trusted-main-tooling")):
        steps = current["jobs"][key]["steps"]
        trusted = next(step["with"] for step in steps if step.get("with", {}).get("path") == prefix)
        assert "pull_request.base.sha" in trusted["ref"]
        assert trusted["persist-credentials"] == "false"
    for workflow in ("session-review.yml", "prepare-neutral-audit-packet.yml"):
        assert current["name"] in load(workflow)["on"]["workflow_run"]["workflows"]
    assert current["name"] not in load("publish-handoff.yml")["on"]["workflow_run"]["workflows"]
    assert load("handoff-evidence.yml")["on"]["pull_request"]["branches"] == ["develop"]


@pytest.mark.parametrize("field", [None, "base_ref", "legacy_handoff_required", "contract.path"])
def test_main_revalidates_artifact_policy_independently(tmp_path, monkeypatch, field):
    sys.path.insert(0, str(TOOL.parent))
    candidate_index = importlib.import_module("build_test_candidate_index")
    base, head, preview, issue_hash, contract_hash = ("b" * 40, "a" * 40, "c" * 40, "d" * 64, "e" * 64)
    identity = {"repository": REPOSITORY, "base_ref": "main", "base_sha": base, "head_sha": head,
                "merge_preview_sha": preview, "pull_request": 19, "issue": 17, "issue_sha256": issue_hash}
    record = {"mode": "native-github-audit", "repository": REPOSITORY, "base_ref": "main",
              "legacy_handoff_required": False, "trusted_anchor_sha": base,
              "material_head_sha": head, "contract": {
                  "source_sha256": contract_hash, "path": MAIN,
                  "observed_at_sha": base, "legacy_handoff_policy": "forbidden"}}
    if field == "contract.path":
        record["contract"]["path"] = DEVELOP
    elif field:
        record[field] = "develop"
    event = {"repository": {"full_name": REPOSITORY},
             "pull_request": {"merge_commit_sha": preview}}
    log = b"one control passed"
    junit = tmp_path / "pytest-exact-head.xml"
    junit.write_bytes(b'<testsuite><testcase classname="module" name="test_control"/></testsuite>')
    (tmp_path / "pytest-exact-head.log").write_bytes(log)
    isolation = importlib.import_module("run_main_evidence_tests")
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, "w") as package:
        payload = {
            "audit-transport.json": record, "certification-event.json": event,
            "handoff-preflight.json": {
                "identity": {"merge_preview_sha": preview, "issue_number": 17, "base_sha": base},
                "source": {"issue_body_sha256": issue_hash}},
            "test-execution-facts.json": {
                "subject_sha": head, "verification": "passed",
                "execution": {"exit_code": 0, "log_sha256": hashlib.sha256(log).hexdigest()}},
            "test-candidate-index.json": candidate_index.collect(junit, head),
            "main-test-containment.json": isolation.receipt(tmp_path, head),
        }
        for name, data in payload.items():
            package.writestr(name, json.dumps(data, sort_keys=True))
        package.writestr("pytest-exact-head.log", log)
        package.writestr("pytest-exact-head.xml", junit.read_bytes())
    raw = blob.getvalue()
    artifact = {"name": f"handoff-evidence-19-{head}", "id": 71,
                "expired": False, "digest": "sha256:" + hashlib.sha256(raw).hexdigest()}
    checks = {"check_runs": [
        {"id": i, "name": name, "head_sha": head, "status": "completed", "conclusion": "success",
         "app": {"id": gate.APP_ID}, "details_url": f"https://github.com/{REPOSITORY}/actions/runs/25/job/64",
         "completed_at": "2026-11-25T00:00:00Z"}
        for i, name in enumerate((*gate.TECHNICAL, gate.MAIN_NATIVE_EVIDENCE), start=1)]}

    def api(path, *, binary=False):
        if path == f"/repos/{REPOSITORY}/actions/artifacts/71/zip" and binary:
            return raw
        assert path == f"/repos/{REPOSITORY}/actions/runs/25/artifacts?per_page=100"
        return {"artifacts": [artifact], "total_count": 1}

    monkeypatch.setenv("GH_TOKEN", "offline-fixture")
    monkeypatch.setattr(gate, "trusted_workflow_check", lambda *_: True)

    def verify():
        return facts.certified_evidence(
            identity, checks, tmp_path, api=api, unpack=runner.unpack,
            authenticated_certificate_event=lambda _: event,
            authenticated_preview_reconciliation=lambda *_: {"certified_sha": preview},
            root=ROOT, audit_transport={"mode": "native-github-audit", "contract_sha256": contract_hash})

    if field:
        with pytest.raises(ValueError, match="does not bind its protected main policy"):
            verify()
    else:
        metadata, tests = verify()
        assert metadata["artifact_id"] == 71
        assert metadata["audit_transport"] == "native-github-audit"
        assert len(tests) == 1


@pytest.mark.parametrize("base,linear", [("main", True), ("main", False), ("develop", False)])
def test_neutral_packet_keeps_fallback_optional_on_main_without_granting_it(monkeypatch, base, linear):
    policy = {"implementation_provenance": {"mode": "enabled", "type": runner.PROVENANCE_TYPE}}
    packet = {"identity": {"base_ref": base}}

    def provenance(identity, metadata):
        assert identity is packet["identity"] and metadata is packet
        if not linear:
            raise ValueError("GitHub PR commits are not an authenticated linear material chain from base")
        return {"fixture": "material linear Git history verified"}

    monkeypatch.setattr(runner, "authenticated_implementation_provenance", provenance)
    if base == "develop" and not linear:
        with pytest.raises(ValueError, match="linear material chain"):
            runner.enrich_neutral_packet(packet, policy)
    else:
        runner.enrich_neutral_packet(packet, policy)
        assert ("implementation_provenance" in packet) is linear


@pytest.mark.parametrize("base", ["main", "develop"])
def test_final_recheck_authenticates_the_artifact_producer_of_its_own_base(monkeypatch, base):
    head, base_sha = "a" * 40, "b" * 40
    producer = gate.MAIN_NATIVE_EVIDENCE if base == "main" else gate.NATIVE_EVIDENCE
    transport = {"mode": "native-github-audit", "contract_sha256": "e" * 64}
    identity = {"repository": REPOSITORY, "base_ref": base, "head_sha": head,
                "base_sha": base_sha, "pull_request": 19, "issue": 17}
    packet = {"identity": identity, "audit_transport": transport["mode"],
              "native_contract_sha256": transport["contract_sha256"],
              "technical_check_ids": [1, 2, 3], "artifact_id": 71, "artifact_digest": "sha256:" + "e" * 64}
    checks = {"check_runs": [
        {"id": i, "name": name, "head_sha": head, "status": "completed", "conclusion": "success",
         "app": {"id": gate.APP_ID}}
        for i, name in enumerate((*gate.TECHNICAL, producer), start=1)]}
    monkeypatch.setattr(runner, "trusted_audit_transport", lambda _: transport)
    monkeypatch.setattr(runner, "target", lambda *_: (identity, {}))
    monkeypatch.setattr(gate, "trusted_workflow_check", lambda *_: True)

    def read(path):
        if path.endswith("check-runs?per_page=100"):
            return checks
        assert path.endswith("/actions/artifacts/71")
        return {"digest": packet["artifact_digest"], "expired": False}

    monkeypatch.setattr(runner, "api", read)
    runner.recheck_inputs(packet)
    checks["check_runs"][-1]["name"] = gate.NATIVE_EVIDENCE if base == "main" else gate.MAIN_NATIVE_EVIDENCE
    with pytest.raises(gate.RequiredChecksNotReadyError):
        runner.recheck_inputs(packet)
