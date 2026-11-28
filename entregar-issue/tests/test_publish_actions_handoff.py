"""Trusted post-certification publisher: only exact, allowlisted GitHub evidence."""
from __future__ import annotations

import base64
import hashlib
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.error import HTTPError

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
        if endpoint == f"contents/.github/session-review-policy.json?ref={self.base}":
            raise HTTPError(endpoint, 404, "absent", None, None)
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
        "audit-escape-closure": {"schema_version": 1,
                                 "subject": {"repository": "owner/repo", "issue_number": 42,
                                             "pull_request_number": 99,
                                             "material_head_sha": candidate["head"]},
                                 "escapes": [escape]},
        "previous-audit-escape-closure": {"schema_version": 1,
                                          "subject": {"repository": "owner/repo", "issue_number": 42,
                                                      "pull_request_number": 99,
                                                      "material_head_sha": candidate["base"]},
                                          "escapes": [previous]},
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
    grounding.git(candidate["repo"], "checkout", "--detach", candidate["base"])
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
    assert len(harness.terminal_proofs) == 2
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


def test_default_publisher_selects_main_from_trusted_api(monkeypatch):
    event = {"repository": {"full_name": "team/skill"}, "workflow_run": {
        "status": "completed", "conclusion": "success", "event": "pull_request",
        "path": ".github/workflows/handoff-evidence.yml", "head_sha": HEAD,
        "pull_requests": [{"number": 113, "base": {"ref": "develop"}}]}}
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "state": "open", "head": {"sha": HEAD, "ref": "feat/127",
                                 "repo": {"full_name": "team/skill"}},
        "base": {"sha": BASE, "ref": "main"}})
    selected = publisher.trusted_default_base_ref(event, ".github/workflows/handoff-evidence.yml")
    assert selected == "main"  # The spoofed event says develop, but the API is authoritative.
    assert publisher.target_from_event(event, selected) == ("team/skill", 113, HEAD, BASE)


def test_default_publisher_rejects_unsupported_base_before_publication(monkeypatch):
    event = {"repository": {"full_name": "team/skill"}, "workflow_run": {
        "status": "completed", "conclusion": "success", "event": "pull_request",
        "path": ".github/workflows/handoff-evidence.yml", "head_sha": HEAD,
        "pull_requests": [{"number": 113}]}}
    monkeypatch.setattr(publisher, "api_get", lambda *_: {
        "base": {"sha": BASE, "ref": "integration"}})
    with pytest.raises(ValueError, match="must be develop or main"):
        publisher.trusted_default_base_ref(event, ".github/workflows/handoff-evidence.yml")


def test_default_publisher_rejects_untrusted_run_without_api_access(monkeypatch):
    event = {"repository": {"full_name": "team/skill"}, "workflow_run": {
        "status": "completed", "conclusion": "failure", "event": "pull_request",
        "path": ".github/workflows/handoff-evidence.yml", "head_sha": HEAD,
        "pull_requests": [{"number": 113}]}}
    monkeypatch.setattr(publisher, "api_get", lambda *_: pytest.fail("must not access API"))
    with pytest.raises(ValueError, match="authenticated successful PR"):
        publisher.trusted_default_base_ref(event, ".github/workflows/handoff-evidence.yml")


def test_trusted_publisher_can_stage_gitignored_certified_results(certified_publisher):
    harness = certified_publisher
    exclude = harness.repo / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text(encoding="utf-8") + "\n.audit/\n", encoding="utf-8")
    published = publisher.publish(harness.event)
    assert harness.pushed == published
    git = importlib.import_module("entregar-issue.tests.test_codebase_grounding").git
    cert = json.loads((harness.bundle / publisher.CERTIFICATE).read_text(encoding="utf-8"))
    changed = set(git(harness.repo, "diff", "--name-only", harness.head, published).splitlines())
    assert changed == set(publisher.allowed_paths(cert))
    assert all(path.startswith(publisher.PREFIX) for path in changed)


def test_publication_retries_only_stale_pr_readback(certified_publisher, monkeypatch):
    harness = certified_publisher
    original = publisher.api_get
    stale = []
    delays = []

    def api(repository, endpoint):
        result = original(repository, endpoint)
        if endpoint == "pulls/99" and harness.pushed and not stale:
            stale.append(True)
            return {**result, "head": {**result["head"], "sha": harness.head}}
        return result

    monkeypatch.setattr(publisher, "api_get", api)
    monkeypatch.setattr(publisher.time, "sleep", delays.append)
    published = publisher.publish(harness.event)
    assert published == harness.pushed
    assert stale == [True] and delays == [0.5]
    assert len(harness.terminal_proofs) == 2


@pytest.mark.parametrize("mutation", ["unexpected-head", "changed-base", "permanent-stale"])
def test_publication_readback_fails_closed_on_foreign_or_unverified_target(
    certified_publisher, monkeypatch, mutation,
):
    harness = certified_publisher
    original = publisher.api_get
    sleeps = []

    def api(repository, endpoint):
        result = original(repository, endpoint)
        if endpoint != "pulls/99" or not harness.pushed:
            return result
        result = dict(result)
        result["head"] = dict(result["head"])
        result["base"] = dict(result["base"])
        if mutation == "changed-base":
            result["base"]["sha"] = "f" * 40
        else:
            result["head"]["sha"] = "f" * 40 if mutation == "unexpected-head" else harness.head
        return result

    monkeypatch.setattr(publisher, "api_get", api)
    monkeypatch.setattr(publisher.time, "sleep", sleeps.append)
    with pytest.raises(ValueError, match=r"postpublication PR changed|fresh postpublication GitHub read"):
        publisher.publish(harness.event)
    assert harness.pushed is not None
    assert len(harness.terminal_proofs) == 1  # Prepublication guard, no false post-write approval.
    if mutation == "permanent-stale":
        assert len(sleeps) == 5
    else:
        assert sleeps == []


@pytest.mark.parametrize("change", ["add", "edit", "remove"])
def test_trusted_historical_audit_files_are_immutable(tmp_path, change):
    repo = tmp_path / "source"
    repo.mkdir()
    git = importlib.import_module("entregar-issue.tests.test_codebase_grounding").git
    git(repo, "init", "-q")
    historical = repo / ".audit" / "entregar-issue" / "prior.json"
    historical.parent.mkdir(parents=True)
    historical.write_text('{"version":1}', encoding="utf-8")
    git(repo, "add", "-f", "--", ".audit/entregar-issue/prior.json")
    git(repo, "commit", "-q", "-m", "existing certified history")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("new candidate", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-q", "-m", "new candidate")
    material = git(repo, "rev-parse", "HEAD")
    publisher.ensure_historical_audit_unchanged(repo, base, material, [publisher.CERTIFICATE])

    if change == "add":
        novel = historical.parent / "extra.json"
        novel.write_text('{"version":2}', encoding="utf-8")
        git(repo, "add", "-f", "--", ".audit/entregar-issue/extra.json")
    elif change == "edit":
        historical.write_text('{"version":2}', encoding="utf-8")
        git(repo, "add", "-f", "--", ".audit/entregar-issue/prior.json")
    else:
        historical.unlink()
        git(repo, "add", "-u", "--", ".audit/entregar-issue/prior.json")
    git(repo, "commit", "-q", "-m", "change historical evidence")
    changed = git(repo, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="outside certificate scope"):
        publisher.ensure_historical_audit_unchanged(repo, base, changed, [publisher.CERTIFICATE])


def test_enabled_session_mode_preserves_material_sha_without_result_child(certified_publisher, monkeypatch):
    harness = certified_publisher
    monkeypatch.setattr(publisher, "session_mode_active", lambda repo, base, trusted: True)
    assert publisher.publish(harness.event) is None
    assert harness.pushed is None
    assert harness.validators == ["validate_handoff_certificate.py", "validate_codebase_grounding.py",
                                  "check_code_growth.py"]


def session_policy_bytes(mode):
    from scripts.session_review import ACKNOWLEDGEMENT, ASSURANCE

    return json.dumps({
        "schema_version": 1, "mode": mode, "assurance": ASSURANCE,
        "acknowledgement": ACKNOWLEDGEMENT,
        "operators": [{"id": 123, "login": "synthetic-operator"}] if mode == "enabled" else [],
    }).encode("utf-8")


def policy_checkout(tmp_path, base_raw, default_raw):
    repo = tmp_path / "consumer"
    repo.mkdir()
    git = importlib.import_module("entregar-issue.tests.test_codebase_grounding").git
    git(repo, "init", "-q")
    path = repo / ".github/session-review-policy.json"
    path.parent.mkdir()
    for index, raw in enumerate((base_raw, default_raw)):
        if path.exists() or path.is_symlink():
            path.unlink()
        if raw == b"symlink":
            path.symlink_to("../README.md")
        elif raw is not None:
            path.write_bytes(raw)
        git(repo, "add", "-A")
        git(repo, "commit", "--allow-empty", "-q", "-m", "trusted policy snapshot")
        if index == 0:
            base = git(repo, "rev-parse", "HEAD")
    return repo, base


def policy_response(raw):
    return {"type": "file", "encoding": "base64", "content": base64.b64encode(raw).decode("ascii")}


def install_policy_helpers(tooling):
    source = publisher.SCRIPT_ROOT.parents[1]
    for relative in ("entregar-issue/scripts/git_tree_snapshot.py", "scripts/session_review.py"):
        target = tooling / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)


def test_consumer_legacy_ignores_enabled_tooling_and_untracked_policy(tmp_path, monkeypatch):
    repo, base = policy_checkout(tmp_path, None, None)
    tooling = tmp_path / "tooling"
    (tooling / ".github").mkdir(parents=True)
    (tooling / ".github/session-review-policy.json").write_bytes(session_policy_bytes("enabled"))
    install_policy_helpers(tooling)
    monkeypatch.setattr(publisher, "SCRIPT_ROOT", tooling / "entregar-issue/scripts")
    # An uncommitted file is not trusted default-branch policy either.
    (repo / ".github/session-review-policy.json").write_bytes(session_policy_bytes("enabled"))

    def absent(repository, endpoint):
        assert repository == "owner/repo"
        assert endpoint == f"contents/.github/session-review-policy.json?ref={base}"
        raise HTTPError(endpoint, 404, "absent", None, None)

    monkeypatch.setattr(publisher, "api_get", absent)
    assert publisher.session_mode_active("owner/repo", base, repo) is False


@pytest.mark.parametrize("mode,expected", [("enabled", True), ("disabled", False)])
def test_consumer_policy_not_tooling_selects_session_mode(tmp_path, monkeypatch, mode, expected):
    raw = session_policy_bytes(mode)
    repo, base = policy_checkout(tmp_path, raw, raw)
    monkeypatch.setattr(publisher, "api_get", lambda *_: policy_response(raw))
    assert publisher.session_mode_active("owner/repo", base, repo) is expected


_POLICY_FAILURE_CASES = [
    "base-only", "default-only", "different-bytes", "different-api-bytes",
    "contradictory-404", "403", "500", "unproved-base", "invalid-schema",
    "duplicate-json", "symlink", "api-only", "malformed-api",
]


def declined_policy_fixture(tmp_path, case):
    enabled = session_policy_bytes("enabled")
    disabled = session_policy_bytes("disabled")
    invalid = b'{"schema_version":true,"mode":"disabled"}'
    duplicate = b'{"mode":"enabled","mode":"disabled"}'
    base_raw, default_raw = {
        "base-only": (enabled, None),
        "default-only": (None, enabled),
        "different-bytes": (enabled, disabled),
        "invalid-schema": (invalid, invalid),
        "duplicate-json": (duplicate, duplicate),
        "symlink": (b"symlink", b"symlink"),
        "api-only": (None, None),
    }.get(case, (enabled, enabled))
    if case in {"403", "500", "unproved-base"}:
        base_raw = default_raw = None
    repo, base = policy_checkout(tmp_path, base_raw, default_raw)
    if case == "unproved-base":
        base = "f" * 40

    def api(repository, endpoint):
        if case in {"403", "500"}:
            raise HTTPError(endpoint, int(case), "unavailable", None, None)
        if case in {"default-only", "contradictory-404"}:
            raise HTTPError(endpoint, 404, "absent", None, None)
        if case == "malformed-api":
            return {"type": "symlink", "encoding": "base64", "content": ""}
        return policy_response(disabled if case == "different-api-bytes" else base_raw or enabled)

    return repo, base, api


@pytest.mark.parametrize("case", _POLICY_FAILURE_CASES)
def test_consumer_session_policy_fails_closed(tmp_path, monkeypatch, case):
    repo, base, api = declined_policy_fixture(tmp_path, case)
    monkeypatch.setattr(publisher, "api_get", api)
    with pytest.raises((ValueError, subprocess.CalledProcessError)):
        publisher.session_mode_active("owner/repo", base, repo)


@pytest.mark.parametrize("case", _POLICY_FAILURE_CASES)
def test_publisher_policy_matrix_stops_before_stage_commit_push(
    certified_publisher, monkeypatch, tmp_path, case,
):
    """Real publisher and resolver; policy Git snapshots and HTTP remain synthetic."""
    harness = certified_publisher
    repo, base, policy_response_fixture = declined_policy_fixture(tmp_path, case)
    resolve = publisher.session_mode_active
    state = []

    def command(*args, cwd=None):
        if args[0] == "git" and (args[1] in {"add", "push"} or "commit" in args[1:]):
            state.append(args)
        return harness.command(*args, cwd=cwd)

    def api(repository, endpoint):
        if endpoint.startswith("contents/.github/session-review-policy.json?"):
            assert endpoint == f"contents/.github/session-review-policy.json?ref={base}"
            return policy_response_fixture(repository, endpoint)
        return harness.api_get(repository, endpoint)

    def resolve_fixture(repository, live_base, live_default):
        assert (repository, live_base, live_default) == ("owner/repo", harness.base, harness.repo)
        state.append("policy-resolver-reached")
        return resolve(repository, base, repo)

    monkeypatch.setattr(publisher, "command", command)
    monkeypatch.setattr(publisher, "api_get", api)
    monkeypatch.setattr(publisher, "session_mode_active", resolve_fixture)
    reason = {
        "base-only": "missing or malformed", "default-only": "policy unavailable",
        "different-bytes": "policy differs", "different-api-bytes": "policy differs",
        "contradictory-404": "policy unavailable", "403": "policy unavailable",
        "500": "policy unavailable", "unproved-base": "cat-file",
        "invalid-schema": "unexpected policy fields", "duplicate-json": "duplicate JSON key",
        "symlink": "unsafe Git type or symlink", "api-only": "missing or malformed",
        "malformed-api": "missing or malformed",
    }[case]
    with pytest.raises((ValueError, subprocess.CalledProcessError), match=reason):
        publisher.publish(harness.event)
    assert state == ["policy-resolver-reached"]
    assert not harness.staged and harness.pushed is None and not harness.terminal_proofs


def test_publisher_policy_api_failure_prevents_any_stage_or_push(certified_publisher, monkeypatch):
    harness = certified_publisher
    original = publisher.api_get

    def api(repository, endpoint):
        if endpoint.startswith("contents/.github/session-review-policy.json?"):
            raise HTTPError(endpoint, 403, "unavailable", None, None)
        return original(repository, endpoint)

    monkeypatch.setattr(publisher, "api_get", api)
    with pytest.raises(ValueError, match="protected-base session policy unavailable"):
        publisher.publish(harness.event)
    assert not harness.staged and harness.pushed is None
    assert not harness.terminal_proofs


def test_legacy_publication_with_enabled_tooling_and_bilateral_policy_absence(certified_publisher, monkeypatch, tmp_path):
    harness = certified_publisher
    policy = ".github/session-review-policy.json"
    tooling = tmp_path / "tooling-only"
    (tooling / ".github").mkdir(parents=True)
    (tooling / policy).write_bytes(session_policy_bytes("enabled"))
    assert json.loads((tooling / policy).read_bytes())["mode"] == "enabled"
    shutil.copytree(publisher.SCRIPT_ROOT.parent, tooling / "entregar-issue",
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    install_policy_helpers(tooling)
    monkeypatch.setattr(publisher, "SCRIPT_ROOT", tooling / "entregar-issue/scripts")
    git = harness.real_command
    assert git("git", "rev-parse", "HEAD", cwd=harness.repo) == harness.base
    (harness.repo / "default-marker.txt").write_text("distinct trusted default tree\n", encoding="utf-8")
    git("git", "add", "default-marker.txt", cwd=harness.repo)
    git("git", "-c", "user.name=synthetic", "-c", "user.email=fixture@example.invalid",
        "commit", "-m", "distinct trusted default fixture", cwd=harness.repo)
    default = git("git", "rev-parse", "HEAD", cwd=harness.repo)
    assert default != harness.base
    assert git("git", "rev-parse", default + "^{tree}", cwd=harness.repo) != git(
        "git", "rev-parse", harness.base + "^{tree}", cwd=harness.repo)
    for sha in (default, harness.base):
        assert not git("git", "ls-tree", sha, "--", policy, cwd=harness.repo)
    assert not (harness.repo / policy).exists()
    trace = []

    def api(repository, endpoint):
        if endpoint.startswith("contents/"):
            assert endpoint == f"contents/{policy}?ref={harness.base}"
            assert not harness.staged and harness.pushed is None
            try:
                return harness.api_get(repository, endpoint)
            except HTTPError as exc:
                assert exc.code == 404
                trace.append("protected-policy-404")
                raise
        result = harness.api_get(repository, endpoint)
        if harness.pushed and endpoint == "pulls/99":
            assert result["head"]["sha"] == harness.pushed and result["base"]["sha"] == harness.base
            trace.append("readback-pr-exact")
        if harness.pushed and endpoint == f"commits/{harness.pushed}":
            assert result["parents"] == [{"sha": harness.head}]
            assert result["files"]
            trace.append("readback-child-exact")
        return result

    def command(*args, cwd=None):
        if args[:2] == ("git", "push"):
            # Existing harness intercepts push; this is an assertion on simulated transport.
            trace.append("push-simulated")
        result = harness.command(*args, cwd=cwd)
        if args[0] == "python" and Path(args[1]).name == "validate_terminal_handoff.py":
            trace.append("terminal-post" if harness.pushed else "terminal-pre")
        return result

    monkeypatch.setattr(publisher, "api_get", api)
    monkeypatch.setattr(publisher, "command", command)
    result = publisher.publish(harness.event)
    assert result == harness.pushed and result != harness.head and harness.staged
    assert len(harness.terminal_proofs) == 2
    assert all(p["material_head_sha"] == harness.head for p in harness.terminal_proofs)
    assert trace == ["protected-policy-404", "terminal-pre", "push-simulated",
                     "readback-pr-exact", "readback-child-exact", "terminal-post"]


@pytest.mark.parametrize("mode", ["enabled", "disabled", "absent", "invalid"])
def test_policy_import_origins_are_pinned_to_official_tooling(tmp_path, monkeypatch, mode):
    """Observe actual imports, not just the path of validator subprocesses."""
    root = publisher.SCRIPT_ROOT.parents[1].resolve()
    raw = (None if mode == "absent" else b'{"schema_version":true,"mode":"disabled"}'
           if mode == "invalid" else session_policy_bytes(mode))
    consumer, base = policy_checkout(tmp_path, raw, raw)
    candidate = tmp_path / "candidate-data"
    candidate.mkdir()
    (candidate / "notes.txt").write_text("untrusted checkout used as data", encoding="utf-8")
    monkeypatch.chdir(candidate)
    load = publisher.load_policy_helper
    search_path = tuple(sys.path)
    origins = {}

    def record(name):
        module = load(name)
        origins[name] = Path(module.__file__).resolve()
        return module

    def api(repository, endpoint):
        assert repository == "owner/repo" and endpoint.endswith(f"?ref={base}")
        if raw is None:
            raise HTTPError(endpoint, 404, "absent", None, None)
        return policy_response(raw)

    monkeypatch.setattr(publisher, "load_policy_helper", record)
    monkeypatch.setattr(publisher, "api_get", api)
    if mode == "invalid":
        with pytest.raises(ValueError):
            publisher.session_mode_active("owner/repo", base, consumer)
    else:
        assert publisher.session_mode_active("owner/repo", base, consumer) is (mode == "enabled")
    expected = {"git_tree_snapshot": (publisher.SCRIPT_ROOT / "git_tree_snapshot.py").resolve()}
    if mode != "absent":
        expected["session_review"] = root / "scripts/session_review.py"
    assert origins == expected
    assert tuple(sys.path) == search_path
    assert all(not origin.is_relative_to(consumer) and not origin.is_relative_to(candidate)
               for origin in origins.values())


@pytest.mark.parametrize("relative", [
    "entregar-issue/scripts/git_tree_snapshot.py", "scripts/session_review.py",
])
def test_missing_pinned_policy_source_blocks_routing(tmp_path, monkeypatch, relative):
    raw = session_policy_bytes("enabled")
    consumer, base = policy_checkout(tmp_path, raw, raw)
    tooling = tmp_path / "tooling"
    install_policy_helpers(tooling)
    (tooling / relative).unlink()
    monkeypatch.setattr(publisher, "SCRIPT_ROOT", tooling / "entregar-issue/scripts")
    monkeypatch.setattr(publisher, "api_get", lambda *_: policy_response(raw))
    with pytest.raises(ValueError, match="trusted policy helper source is unavailable"):
        publisher.session_mode_active("owner/repo", base, consumer)


def public_handoff_fixture_literal_classes(text):
    """Bounded regression for literal sources, not a general secret scanner."""
    import re

    return {
        "hosts": set(re.findall(r"https?://([A-Za-z0-9.-]+)", text)),
        "emails": set(re.findall(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)),
        "credential_literals": set(re.findall(
            r"""(?im)^\s*(?:[A-Za-z0-9_]+_TOKEN|[A-Za-z0-9_]+_PASSWORD|[A-Za-z0-9_]+_SECRET)\s*=\s*["']([^"']+)["']""",
            text,
        )),
        "repo_literals": set(re.findall(
            r'(?i)repos(?:itory)?[\s=:"]+([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)', text
        )),
    }


@pytest.mark.parametrize("kind,allowed", [
    ("hosts", {"example.invalid", "avatars.example", "example.org", "github.com", "other.example"}),
    ("emails", {"fixture@example.invalid"}),
    ("repo_literals", {"owner/repo", "owner/repository"}),
    ("credential_literals", set()),
])
def test_handoff_changed_sources_use_only_generic_fixture_literals(kind, allowed):
    root = Path(__file__).resolve().parents[2]
    paths = (
        "entregar-issue/references/github-actions-evidence.md",
        "entregar-issue/scripts/publish_actions_handoff.py",
        "entregar-issue/tests/test_publish_actions_handoff.py",
        "tests/test_session_review_runner.py",
        "tests/test_session_review_workflows.py",
    )
    observed = set()
    for path in paths:
        observed.update(public_handoff_fixture_literal_classes((root / path).read_text(encoding="utf-8"))[kind])
    assert observed == allowed


@pytest.mark.parametrize("kind,synthetic_parts", [
    ("hosts", ("https:", "//outside.", "invalid/")),
    ("emails", ("not-a-person", "@", "outside.invalid")),
    ("repo_literals", ('repo', 'sitory="outside/fixture"')),
    ("credential_literals", ('PROBE_', 'SECRET="synthetic-marker-not-a-credential"')),
])
def test_generic_fixture_literal_evidence_detects_out_of_scope_markers(kind, synthetic_parts):
    # Strings are inert and use the reserved .invalid namespace.
    assert public_handoff_fixture_literal_classes("".join(synthetic_parts))[kind]
