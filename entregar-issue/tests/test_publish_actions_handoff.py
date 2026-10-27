"""Trusted post-certification publisher: only exact, allowlisted GitHub evidence."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / "scripts" / "publish_actions_handoff.py"
spec = importlib.util.spec_from_file_location("publish_actions_handoff", PATH)
assert spec and spec.loader
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
HEAD = "a" * 40
BASE = "b" * 40


def test_allowlist_blocks_material_paths_and_unexpected_names():
    with pytest.raises(ValueError, match="non-audit"):
        publisher.allowed_paths({"certificate_commit_policy": {
            "mode": "result-only-child", "allowed_paths": [publisher.CERTIFICATE, "src/app.py"]}})
    with pytest.raises(ValueError, match="unsafe"):
        publisher.allowed_paths({"certificate_commit_policy": {
            "mode": "result-only-child",
            "allowed_paths": [publisher.CERTIFICATE, ".audit/entregar-issue/../escape.json"]}})
    assert publisher.allowed_paths({"certificate_commit_policy": {
        "mode": "result-only-child",
        "allowed_paths": [publisher.CERTIFICATE, ".audit/entregar-issue/requirement-closure.json"],
    }})[0].startswith(publisher.PREFIX)


def test_bundle_paths_reject_symlink_and_absence(tmp_path):
    p = tmp_path / publisher.CERTIFICATE
    p.parent.mkdir(parents=True)
    p.write_text("{}")
    assert publisher.safe_bundle_path(tmp_path, publisher.CERTIFICATE) == p
    with pytest.raises(ValueError, match="missing or unsafe"):
        publisher.safe_bundle_path(tmp_path, ".audit/entregar-issue/nonexistent.json")
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}")
    alias = tmp_path / ".audit" / "entregar-issue" / "alias.json"
    alias.symlink_to(outside)
    with pytest.raises(ValueError, match="missing or unsafe"):
        publisher.safe_bundle_path(tmp_path, ".audit/entregar-issue/alias.json")


def test_reject_invalid_workflow_event_before_api(monkeypatch):
    monkeypatch.setattr(publisher, "api_get", lambda *_: pytest.fail("network must not be reached"))
    event = {"repository": {"full_name": "team/skill"}, "workflow_run": {
        "status": "completed", "conclusion": "failure", "event": "pull_request",
        "head_sha": HEAD, "pull_requests": [{"number": 113}],
    }}
    with pytest.raises(ValueError, match="only one completed"):
        publisher.target_from_event(event)


def test_reject_live_pr_sha_drift(monkeypatch):
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "state": "open", "head": {"sha": BASE, "ref": "feat/112",
        "repo": {"full_name": "team/skill"}},
        "base": {"sha": BASE, "ref": "develop"},
    })
    event = {"repository": {"full_name": "team/skill"}, "workflow_run": {
        "status": "completed", "conclusion": "success", "event": "pull_request",
        "path": ".github/workflows/handoff-evidence.yml",
        "head_sha": HEAD, "pull_requests": [{"number": 113}],
    }}
    with pytest.raises(ValueError, match="changed identity"):
        publisher.target_from_event(event)


def test_material_ci_requires_every_required_check_green(monkeypatch):
    def response(status):
        return {"total_count": 3, "workflow_runs": [
            {"workflow_id": index, "name": name, "head_sha": HEAD,
             "event": "pull_request", "pull_requests": [{"number": 113}],
             "run_number": 1, "status": "completed", "conclusion": status if index == 3 else "success"}
            for index, name in enumerate((
                "Validate skills", "Validate GitHub Audit MCP",
                "Collect and certify exact-SHA handoff"), 1)
        ]}
    monkeypatch.setattr(publisher, "api_get", lambda *_: response("failure"))
    with pytest.raises(ValueError, match="not terminal success"):
        publisher.check_material_ci("team/skill", HEAD, 113)
    monkeypatch.setattr(publisher, "api_get", lambda *_: response("success"))
    publisher.check_material_ci("team/skill", HEAD, 113)

def test_material_ci_ignores_unrelated_red_audit_workflow(monkeypatch):
    required = (
        "Validate skills", "Validate GitHub Audit MCP",
        "Collect and certify exact-SHA handoff",
    )
    workflows = [
        {"workflow_id": index, "name": name, "head_sha": HEAD,
         "event": "pull_request", "pull_requests": [{"number": 113}],
         "run_number": 1, "status": "completed", "conclusion": "success"}
        for index, name in enumerate(required, 1)
    ]
    workflows.append({
        "workflow_id": 99, "name": "Independent audit (exact SHA)", "head_sha": HEAD,
        "event": "pull_request", "pull_requests": [{"number": 113}],
        "run_number": 1, "status": "completed", "conclusion": "failure",
    })
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "total_count": len(workflows), "workflow_runs": workflows,
    })
    publisher.check_material_ci("team/skill", HEAD, 113)


def test_parent_control_snapshots_are_immutable(tmp_path):
    source = tmp_path / "source"
    audit = source / ".audit" / "entregar-issue"
    audit.mkdir(parents=True)
    (audit / "inherited-controls.json").write_bytes(b'{"v":"material"}')
    git = importlib.import_module("entregar-issue.tests.test_codebase_grounding").git
    git(source, "init", "-q")
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "material controls")
    head = git(source, "rev-parse", "HEAD")
    destination = publisher.material_parent_snapshots(source, tmp_path, head)
    assert (destination / "inherited-controls.json").read_bytes() == b'{"v":"material"}'
    (audit / "inherited-controls.json").write_bytes(b'{"v":"new"}')
    assert (destination / "inherited-controls.json").read_bytes() == b'{"v":"material"}'

def test_trusted_publisher_accepts_configured_producer_and_base(monkeypatch):
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "state": "open",
        "head": {"sha": HEAD, "ref": "feat/112", "repo": {"full_name": "team/skill"}},
        "base": {"sha": BASE, "ref": "integration"},
    })
    event = {"repository": {"full_name": "team/skill"}, "workflow_run": {
        "status": "completed", "conclusion": "success", "event": "pull_request",
        "path": ".github/workflows/caller.yml",
        "head_sha": HEAD, "pull_requests": [{"number": 113}],
    }}
    with pytest.raises(ValueError, match="only one completed"):
        publisher.target_from_event(event)
    assert publisher.target_from_event(event, "integration", ".github/workflows/caller.yml") == (
        "team/skill", 113, HEAD, BASE
    )
    with pytest.raises(ValueError, match="producer workflow path"):
        publisher.target_from_event(event, "integration", "../caller.yml")


def test_consumer_required_check_names_are_enforced(monkeypatch):
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "total_count": 1,
        "workflow_runs": [{
            "workflow_id": 3, "name": "My custom quality check",
            "head_sha": HEAD, "event": "pull_request", "pull_requests": [{"number": 113}],
            "run_number": 1, "status": "completed", "conclusion": "success",
        }],
    })
    publisher.check_material_ci("team/skill", HEAD, 113, {"My custom quality check"})
    with pytest.raises(ValueError, match="not present"):
        publisher.check_material_ci("team/skill", HEAD, 113, {"Other required check"})


class PublicationHarness:
    """Real Git and trusted validators; only remote transport is simulated."""

    proof_path = publisher.PREFIX + "execution/ground-tests-proof.log"
    branch = "feat/42-publication"

    def __init__(self, candidate, bundle, event):
        self.candidate, self.bundle, self.event = candidate, bundle, event
        self.head, self.base = candidate["head"], candidate["base"]
        self.repo = candidate["repo"]
        self.real_command = publisher.command
        self.pushed = None
        self.staged = False
        self.proof_absent_at_checkout = False
        self.conflicting_material = False
        self.validators = []
        self.grounding_bytes = None
        self.terminal_proofs = []
        self.omit_parent_repository = False

    def command(self, *values, cwd=None):
        if values[:3] == ("gh", "run", "download"):
            shutil.copytree(self.bundle, values[-1], dirs_exist_ok=True, symlinks=True)
            return ""
        if values[:2] == ("git", "fetch"):
            return ""  # The exact material commit already exists in the fixture repository.
        if values[:2] == ("git", "push"):
            self.pushed = values[-1].split(":", 1)[0]
            return ""
        if values[:2] == ("git", "add"):
            self.staged = True
        if values[0] == "python":
            script = Path(values[1])
            assert script.parent == publisher.SCRIPT_ROOT
            self.validators.append(script.name)
            if script.name == "validate_codebase_grounding.py":
                source = Path(values[values.index("--repo") + 1])
                self.grounding_bytes = (source / self.proof_path).read_bytes()
            if script.name == "validate_terminal_handoff.py":
                values = list(values)
                source = Path(values[values.index("--material-parent-repository") + 1])
                assert self.real_command("git", "rev-parse", "HEAD", cwd=source) != self.head
                if self.omit_parent_repository:
                    index = values.index("--material-parent-repository")
                    del values[index:index + 2]
                values.extend(["--proof-out", str(source.parent / "terminal-proof.json")])
            values = (sys.executable, *values[1:])
        result = self.real_command(*values, cwd=cwd)
        if "--proof-out" in values:
            self.terminal_proofs.append(json.loads(Path(values[-1]).read_text(encoding="utf-8")))
        if values[:3] == ("git", "worktree", "add"):
            destination = Path(values[-2]) / self.proof_path
            self.proof_absent_at_checkout = not destination.exists()
            if self.conflicting_material:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"preexisting conflicting material")
        return result

    def api_get(self, repository, endpoint):
        assert repository == "owner/repo"
        if endpoint == "pulls/99":
            return {"state": "open", "head": {
                "sha": self.pushed or self.head, "ref": self.branch,
                "repo": {"full_name": repository}},
                "base": {"sha": self.base, "ref": "develop"}}
        if endpoint.startswith("actions/runs/7/artifacts"):
            return {"artifacts": [{"name": f"handoff-evidence-99-{self.head}", "expired": False}]}
        if endpoint.startswith("actions/runs?head_sha="):
            return {"total_count": 3, "workflow_runs": [
                {"workflow_id": index, "name": name, "head_sha": self.head,
                 "event": "pull_request", "pull_requests": [{"number": 99}],
                 "run_number": 1, "status": "completed", "conclusion": "success"}
                for index, name in enumerate(("Validate skills", "Validate GitHub Audit MCP",
                                             "Collect and certify exact-SHA handoff"))]}
        if endpoint == f"commits/{self.pushed}" and self.pushed:
            paths = self.real_command("git", "diff", "--name-only", self.head, self.pushed, cwd=self.repo)
            parent = self.real_command("git", "rev-parse", self.pushed + "^", cwd=self.repo)
            return {"parents": [{"sha": parent}], "files": [{"filename": name} for name in paths.splitlines()]}
        pytest.fail(f"unexpected API request: {endpoint}")

    def refresh_grounding_hash(self, report):
        from audit_artifact_io import artifact_metadata

        path = self.bundle / publisher.PREFIX / "codebase-grounding.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        certificate = self.bundle / publisher.CERTIFICATE
        cert = json.loads(certificate.read_text(encoding="utf-8"))
        cert["artifacts"]["codebase_grounding"] = artifact_metadata(path)
        certificate.write_text(json.dumps(cert), encoding="utf-8")


def critical_reaudit_arguments(files, candidate):
    """Compose existing synthetic rejection fixtures; no production audit is changed."""
    rejection = importlib.import_module("entregar-issue.tests.test_independent_rejection_closure")
    replay = importlib.import_module("entregar-issue.tests.test_audit_remediation_gate_replay")
    audit = files["snapshot"].parent
    for name in ("attack", "risk", "inherited"):
        raw = files[name].read_text(encoding="utf-8")
        files[name].write_text(raw.replace(json.dumps(HEAD), json.dumps(candidate["head"])), encoding="utf-8")
    source = audit / "audit-source-result.json"
    replay.write(source, replay.audit(candidate["base"]))
    rid = replay.audit(candidate["base"])["rejection_id"]
    escape = rejection.escape(rid, "F-GATE-001")
    escape["revalidated_head_sha"] = candidate["head"]
    escape["required_risk_families"] = ["documentation"]
    escape["required_attack_dimensions"] = [
        {"risk_family": "documentation", "surface": "canonical-doc-surface", "dimension": dimension}
        for dimension in ("stale-equivalent-claim", "alternate-current-claim")]
    previous = dict(escape, status="blocked", revalidated_head_sha=candidate["base"])
    learning = rejection.learning(rejection_id=rid)
    learning["source_event"]["finding_ids"] = ["F-GATE-001"]
    values = {
        "audit-remediation": replay.ledger(source, candidate["base"], candidate["head"], "npm run format:check"),
        "audit-escape-closure": {"schema_version": 1, "escapes": [escape]},
        "previous-audit-escape-closure": {"schema_version": 1, "escapes": [previous]},
        "learning-closure": learning,
    }
    args = ["--previous-independent-rejection", "--remediation-mode", "targeted-remediation",
            "--attack-matrix", str(files["attack"]), "--risk-saturation", str(files["risk"]),
            "--inherited-controls", str(files["inherited"]), "--audit-source-result", str(source),
            "--allow-result-path", publisher.PREFIX + "previous-audit-escape-closure.json"]
    for name, value in values.items():
        path = audit / (name + ".json")
        rejection.write(path, value)
        args.extend(["--" + name, str(path)])
    return args


@pytest.fixture()
def certified_publisher(tmp_path, monkeypatch, request):
    grounding = importlib.import_module("entregar-issue.tests.test_codebase_grounding")
    delivery = importlib.import_module("entregar-issue.tests.test_handoff_certificate_contract")
    candidate = grounding.candidate.__wrapped__(tmp_path)
    bundle = tmp_path / "certified-artifact"
    audit = bundle / publisher.PREFIX
    audit.mkdir(parents=True)
    files = delivery.build_valid_delivery(audit)
    proof = bundle / PublicationHarness.proof_path
    proof.parent.mkdir()
    shutil.move(str(candidate["repo"] / "verification.log"), proof)
    report = candidate["report"]
    report["test_decisions"][0]["verification"]["evidence_path"] = PublicationHarness.proof_path
    grounded = audit / "codebase-grounding.json"
    grounded.write_text(json.dumps(report), encoding="utf-8")
    growth = audit / "code-growth.json"
    result = delivery.run("check_code_growth.py", "--repo", str(candidate["repo"]),
                          "--base-sha", candidate["base"], "--head-sha", candidate["head"], "--out", str(growth))
    assert result.returncode == 0, result.stdout
    paths = grounding.git(candidate["repo"], "diff", "--name-only", "--no-renames",
                          candidate["base"], candidate["head"]).splitlines()
    args = []
    profile = "light"
    if getattr(request, "param", None) == "critical-targeted":
        profile = "critical"
        args.extend(critical_reaudit_arguments(files, candidate))
    for path in paths:
        args.extend(["--issue-changed-path", path])
    snapshot = json.loads(files["snapshot"].read_text(encoding="utf-8"))
    for source in snapshot["sources"]:
        args.extend(["--allow-result-path", publisher.PREFIX + source["path"]])
    result = delivery.run(
        "build_handoff_certificate.py", "--repository", "owner/repo", "--issue-number", "42",
        "--work-item-kind", "pr", "--work-item-number", "99", "--pull-request-number", "99",
        "--base-ref", "develop", "--head-ref", PublicationHarness.branch,
        "--work-item-start-sha", candidate["base"], "--head-sha", candidate["head"],
        "--base-sha", candidate["base"], "--evidence-profile", profile,
        "--specification-snapshot", str(files["snapshot"]), "--requirement-closure", str(files["closure"]),
        "--codebase-grounding", str(grounded), "--code-growth", str(growth),
        "--source-repository-root", str(candidate["repo"]),
        "--allow-result-path", PublicationHarness.proof_path, "--out", str(bundle / publisher.CERTIFICATE), *args,
    )
    assert result.returncode == 0, result.stdout
    (bundle / "handoff-certification-status.json").write_text(json.dumps({
        "status": "certificate-generated", "material_head_sha": candidate["head"],
        "terminal_ready": False, "certificate_published": False}), encoding="utf-8")
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"repository": {"full_name": "owner/repo"}, "workflow_run": {
        "id": 7, "status": "completed", "conclusion": "success", "event": "pull_request",
        "path": ".github/workflows/handoff-evidence.yml", "head_sha": candidate["head"],
        "pull_requests": [{"number": 99}]}}), encoding="utf-8")
    harness = PublicationHarness(candidate, bundle, event)
    monkeypatch.chdir(candidate["repo"])
    monkeypatch.setattr(publisher, "command", harness.command)
    monkeypatch.setattr(publisher, "api_get", harness.api_get)
    return harness


def test_publisher_materializes_certified_execution_before_grounding(certified_publisher):
    harness = certified_publisher
    expected = (harness.bundle / harness.proof_path).read_bytes()
    published = publisher.publish(harness.event)
    assert harness.proof_absent_at_checkout
    assert harness.grounding_bytes == expected
    assert harness.pushed == published
    assert harness.validators == ["validate_handoff_certificate.py", "validate_codebase_grounding.py",
                                  "check_code_growth.py", "validate_terminal_handoff.py", "validate_terminal_handoff.py"]
    git = importlib.import_module("entregar-issue.tests.test_codebase_grounding").git
    assert git(harness.repo, "rev-parse", published + "^") == harness.head
    assert git(harness.repo, "show", f"{published}:{harness.proof_path}") == expected.decode().strip()
    changed = set(git(harness.repo, "diff", "--name-only", harness.head, published).splitlines())
    cert = json.loads((harness.bundle / publisher.CERTIFICATE).read_text(encoding="utf-8"))
    assert changed == set(publisher.allowed_paths(cert))


@pytest.mark.parametrize("certified_publisher", ["critical-targeted"], indirect=True)
def test_first_critical_reaudit_handoff_proves_material_parent_absence(certified_publisher):
    harness = certified_publisher
    git = importlib.import_module("entregar-issue.tests.test_codebase_grounding").git
    assert git(harness.repo, "ls-tree", "-r", "--name-only", harness.head, "--", publisher.PREFIX) == ""
    published = publisher.publish(harness.event)
    assert harness.pushed == published and harness.proof_absent_at_checkout
    assert len(harness.terminal_proofs) == 2
    for proof in harness.terminal_proofs:
        assert proof["material_head_sha"] == harness.head
        assert proof["material_parent_absent_paths"] == [publisher.PREFIX + name for name in (
            "audit-escape-closure.json", "inherited-controls.json")]
    cert = json.loads((harness.bundle / publisher.CERTIFICATE).read_text(encoding="utf-8"))
    assert cert["evidence_profile"] == "critical" and cert["previous_independent_rejection"]
    assert cert["remediation_mode"] == "targeted-remediation"


@pytest.mark.parametrize("certified_publisher", ["critical-targeted"], indirect=True)
def test_first_critical_reaudit_rejects_unproved_parent_absence(certified_publisher):
    harness = certified_publisher
    harness.omit_parent_repository = True
    with pytest.raises(subprocess.CalledProcessError) as caught:
        publisher.publish(harness.event)
    assert "without material-parent snapshot" in caught.value.stdout
    assert harness.pushed is None


@pytest.mark.parametrize("mutation,reason", [
    ("proof-hash", "evidence hash mismatch"),
    ("missing-allowlist", "explicitly authorized"),
    ("report-hash", "hash"),
    ("wrong-identity", "subject"),
    ("parent-symlink", "symlink"),
    ("missing-proof", "missing or unsafe"),
    ("oversized-proof", "size bound"),
    ("proof-markers", "raw evidence missing"),
    ("conflicting-material", "conflicting material"),
], ids=["proof-hash", "missing-allowlist", "report-hash", "wrong-identity", "parent-symlink",
        "missing-proof", "oversized-proof", "proof-markers", "conflicting-material"])
def test_publisher_rejects_untrusted_execution_before_publication(certified_publisher, mutation, reason):
    harness = certified_publisher
    proof = harness.bundle / harness.proof_path
    report = harness.candidate["report"]
    certificate = harness.bundle / publisher.CERTIFICATE
    cert = json.loads(certificate.read_text(encoding="utf-8"))
    if mutation == "proof-hash":
        proof.write_bytes(proof.read_bytes() + b"tampered")
    elif mutation == "missing-allowlist":
        cert["certificate_commit_policy"]["allowed_paths"].remove(harness.proof_path)
    elif mutation == "report-hash":
        report["test_decisions"][0]["scenario"] = "changed after certification"
        (harness.bundle / publisher.PREFIX / "codebase-grounding.json").write_text(json.dumps(report), encoding="utf-8")
    elif mutation == "wrong-identity":
        cert["identity"]["material_head_sha"] = "c" * 40
    elif mutation == "parent-symlink":
        alias = proof.parent.with_name("execution-alias")
        proof.parent.rename(alias)
        proof.parent.symlink_to(alias.name, target_is_directory=True)
    elif mutation == "missing-proof":
        proof.unlink()
    elif mutation == "oversized-proof":
        proof.write_bytes(proof.read_bytes() + b"x" * publisher.MAX_EXECUTION_PROOF_BYTES)
    elif mutation == "proof-markers":
        proof.write_bytes(proof.read_bytes().replace(b"REACHED:", b"NOT_REACHED:"))
    elif mutation == "conflicting-material":
        harness.conflicting_material = True
    certificate.write_text(json.dumps(cert), encoding="utf-8")
    if mutation in {"oversized-proof", "proof-markers"}:
        report["test_decisions"][0]["verification"]["evidence_sha256"] = hashlib.sha256(proof.read_bytes()).hexdigest()
        harness.refresh_grounding_hash(report)
    with pytest.raises((ValueError, subprocess.CalledProcessError)) as caught:
        publisher.publish(harness.event)
    error = caught.value
    details = str(error) + str(getattr(error, "stdout", "")) + str(getattr(error, "stderr", ""))
    assert reason.lower() in details.lower(), details
    assert not harness.staged and harness.pushed is None
    assert "validate_codebase_grounding.py" not in harness.validators
