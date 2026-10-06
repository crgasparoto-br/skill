from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = [
    "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
    "temporal-consistency", "temporal-destination", "concurrency-atomicity",
    "idempotency", "rollback", "historical-immutability", "structural-contract", "documentation",
]
HEAD = "a" * 40
BASE = "b" * 40
MERGE = "c" * 40
EVIDENCE_SHA = hashlib.sha256(b"negative evidence").hexdigest()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(script: str, *args: str):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], text=True, stdout=subprocess.PIPE)


def build_valid_delivery(base: Path) -> dict[str, Path]:
    issue = base / "issue.md"
    issue.write_text("- Preserve the public output value.\n", encoding="utf-8")
    snapshot = base / "specification-snapshot.json"
    closure = base / "requirement-closure.json"
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "build_specification_snapshot.py"),
        "--repository", "owner/repo", "--issue", "42", "--primary-source-id", "SRC-ISSUE",
        "--source", f"issue-body:SRC-ISSUE:{issue}", "--out", str(snapshot),
    ], check=True, stdout=subprocess.PIPE, text=True)
    subprocess.run([
        sys.executable, str(ROOT / "scripts" / "init_requirement_closure.py"),
        "--specification-snapshot", str(snapshot), "--out", str(closure),
    ], check=True, stdout=subprocess.PIPE, text=True)
    data = json.loads(closure.read_text(encoding="utf-8"))
    ids = []
    for item in data["obligations"]:
        ids.append(item["id"])
        item["disposition"] = "covered"
        item["requirement_ids"] = ["REQ-001"]
        item["rationale"] = "Mapped to a behavioral requirement."
    data["read_model_closures"].update({"status": "not-applicable", "applicability_reason": "No read model contract in this synthetic fixture."})
    data["canonical_source_consistency"].update({"status": "not-applicable", "applicability_reason": "No canonical competing source in this synthetic fixture."})
    data["documentation_consistency"].update({"status": "not-applicable", "applicability_reason": "No documentation transition contract in this synthetic fixture."})
    data["scope_reduction_review"] = {"status": "passed", "matches": []}
    data["pass_c"] = {
        "status": "passed",
        "requirement_ids": ["REQ-001"],
        "obligation_ids": ids,
        "evidence": ["EV-001"],
        "rederived_without_pr_description": True,
        "reviewed_user_visible_semantics": True,
        "reviewed_producer_consumer_parity": True,
        "reviewed_all_specification_sources": True,
    }
    closure.write_text(json.dumps(data), encoding="utf-8")

    surface = "canonical-doc-surface"
    attack = base / "requirement-attack-matrix.json"
    attack.write_text(json.dumps({
        "schema_version": 1,
        "head_sha": HEAD,
        "requirements": [{
            "requirement_id": "REQ-001",
            "obligation_ids": ids,
            "risk_families": ["documentation"],
            "risk_surfaces": [{
                "risk_family": "documentation",
                "surface": surface,
                "reason": "The public contract is represented by a canonical documentation surface.",
            }],
            "plausible_wrong_implementation": "The implementation updates one visible path while leaving an equivalent path stale.",
            "positive_control": {"id": "POS-001", "status": "passed", "head_sha": HEAD, "evidence": "positive.log"},
            "negative_controls": [{
                "id": "NEG-001",
                "status": "passed",
                "head_sha": HEAD,
                "evidence_path": "negative.log",
                "evidence_sha256": EVIDENCE_SHA,
                "risk_family": "documentation",
                "surface": surface,
                "dimension": "stale-equivalent-claim",
                "failure_mode": "An equivalent canonical claim remains stale after the implementation changes.",
                "plausible_wrong_implementation": "Update only one documentation path and leave a competing current-state claim unchanged.",
                "control_type": "procedure",
                "procedure": "Search the canonical documentation surface for competing current-state claims.",
                "expected": "No contradictory current-state claim remains.",
                "observed": "The synthetic fixture contains no contradictory claim.",
                "sibling_cases": [{
                    "id": "S1", "surface": surface, "dimension": "alternate-current-claim", "status": "passed"
                }],
            }],
            "regression_controls": [{"id": "REG-001", "status": "passed", "head_sha": HEAD, "evidence": "regression.log"}],
        }],
        "uncovered_requirements": [],
    }), encoding="utf-8")
    risk = base / "risk-saturation.json"
    risk.write_text(json.dumps({
        "schema_version": 1,
        "head_sha": HEAD,
        "families": [{
            "family": family,
            "applicable": family == "documentation",
            "reason": "Behavioral fixture uses documentation family." if family == "documentation" else "Not applicable to this synthetic fixture.",
            "control_ids": ["NEG-001"] if family == "documentation" else [],
            "dimensions": [{
                "surface": surface,
                "reason": "The public contract is represented by a canonical documentation surface.",
                "control_ids": ["NEG-001"],
                "status": "passed",
            }] if family == "documentation" else [],
            "status": "passed" if family == "documentation" else "not-applicable",
        } for family in CANONICAL],
        "material_families_missing_controls": [],
    }), encoding="utf-8")
    inherited = base / "inherited-controls.json"
    inherited.write_text(json.dumps({
        "schema_version": 1, "head_sha": HEAD, "source_audits": [], "controls": [], "unresolved_controls": [],
    }), encoding="utf-8")
    return {"snapshot": snapshot, "closure": closure, "attack": attack, "risk": risk, "inherited": inherited}


def test_specification_coverage_detects_dropped_canonical_candidate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        issue = base / "issue.md"
        issue.write_text("- Preserve alpha.\n- Preserve beta.\n", encoding="utf-8")
        snapshot = base / "specification-snapshot.json"
        closure = base / "requirement-closure.json"
        subprocess.run([
            sys.executable, str(ROOT / "scripts" / "build_specification_snapshot.py"),
            "--repository", "owner/repo", "--issue", "42", "--primary-source-id", "SRC-ISSUE",
            "--source", f"issue-body:SRC-ISSUE:{issue}", "--out", str(snapshot),
        ], check=True, stdout=subprocess.PIPE, text=True)
        subprocess.run([
            sys.executable, str(ROOT / "scripts" / "init_requirement_closure.py"),
            "--specification-snapshot", str(snapshot), "--out", str(closure),
        ], check=True, stdout=subprocess.PIPE, text=True)
        data = json.loads(closure.read_text(encoding="utf-8"))
        data["obligations"] = data["obligations"][:1]
        closure.write_text(json.dumps(data), encoding="utf-8")
        proc = run("validate_specification_coverage.py", "--specification-snapshot", str(snapshot), "--requirement-closure", str(closure))
        assert proc.returncode == 2
        assert "missing from closure" in proc.stdout


def test_build_and_validate_handoff_certificate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        files = build_valid_delivery(base)
        cert = base / "handoff-ready.json"
        proc = run(
            "build_handoff_certificate.py",
            "--specification-snapshot", str(files["snapshot"]),
            "--repository", "owner/repo", "--work-item-kind", "issue", "--work-item-number", "42",
            "--pull-request", "99", "--base-ref", "develop", "--head-ref", "feature/test",
            "--requirement-closure", str(files["closure"]),
            "--attack-matrix", str(files["attack"]),
            "--risk-saturation", str(files["risk"]),
            "--inherited-controls", str(files["inherited"]),
            "--head-sha", HEAD, "--base-sha", BASE, "--merge-preview-sha", MERGE,
            "--contract-version", "2026-08-20.3", "--out", str(cert),
        )
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(cert.read_text(encoding="utf-8"))
        assert payload["schema_version"] == 2
        assert payload["subject"] == {
            "repository": "owner/repo",
            "issue_number": 42,
            "pull_request_number": 99,
            "work_item_kind": "issue",
            "work_item_number": 42,
            "pull_request": 99,
            "base_ref": "develop",
            "head_ref": "feature/test",
        }
        assert payload["identity"]["material_head_sha"] == HEAD
        assert payload["certificate_commit_policy"]["mode"] == "result-only-child"
        assert ".audit/entregar-issue/handoff-ready.json" in payload["certificate_commit_policy"]["allowed_paths"]

        # The certificate may be validated out-of-band against the material head.
        proc = run(
            "validate_handoff_certificate.py",
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--head-sha", HEAD, "--base-sha", BASE, "--merge-preview-sha", MERGE,
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 0, proc.stdout

        # Once committed, the published head is a direct child that changes only allow-listed result paths.
        child = "d" * 40
        proc = run(
            "validate_handoff_certificate.py",
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--head-sha", child, "--base-sha", BASE, "--merge-preview-sha", "e" * 40,
            "--candidate-parent-sha", HEAD,
            "--candidate-changed-path", ".audit/entregar-issue/handoff-ready.json",
            "--candidate-changed-path", ".audit/entregar-issue/requirement-attack-matrix.json",
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 0, proc.stdout
        assert "result-only handoff child" in proc.stdout

        proc = run(
            "validate_handoff_certificate.py",
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--head-sha", child, "--base-sha", BASE,
            "--candidate-parent-sha", HEAD,
            "--candidate-changed-path", "server/product.ts",
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "non-handoff paths" in proc.stdout

        files["risk"].write_text(files["risk"].read_text(encoding="utf-8") + "\n", encoding="utf-8")
        proc = run(
            "validate_handoff_certificate.py",
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--head-sha", HEAD, "--base-sha", BASE, "--merge-preview-sha", MERGE,
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "hash mismatch" in proc.stdout


def write_grounding(base: Path, subject_sha: str = HEAD) -> Path:
    path = base / "codebase-grounding.json"
    path.write_text(json.dumps({
        "schema_version": 1, "subject_sha": subject_sha, "base_sha": BASE,
        "creations": [], "references": [], "replacements": [],
    }), encoding="utf-8")
    return path


def write_growth(base: Path, status: str = "passed", subject_sha: str = HEAD) -> Path:
    path = base / "code-growth.json"
    path.write_text(json.dumps({
        "schema_version": 1, "control_id": "CODE-GROWTH-001", "status": status, "subject_sha": subject_sha,
        "base_sha": BASE, "policy": {"source": "default"}, "files": [],
        "blocking_files": [] if status == "passed" else [{"path": "server/issue-42.ts", "reason": "too large"}],
    }), encoding="utf-8")
    return path


def code_evidence(base: Path) -> tuple[str, ...]:
    return ("--codebase-grounding", str(write_grounding(base)), "--code-growth", str(write_growth(base)))


def build_scoped_certificate(base: Path, changed_path: str, *extra: str):
    files = build_valid_delivery(base)
    cert = base / "handoff-ready.json"
    proc = run(
        "build_handoff_certificate.py",
        "--specification-snapshot", str(files["snapshot"]),
        "--repository", "owner/repo", "--work-item-kind", "issue", "--work-item-number", "42",
        "--work-item-start-sha", BASE, "--issue-changed-path", changed_path,
        "--requirement-closure", str(files["closure"]),
        "--attack-matrix", str(files["attack"]),
        "--risk-saturation", str(files["risk"]),
        "--inherited-controls", str(files["inherited"]),
        "--head-sha", HEAD, "--base-sha", BASE,
        "--contract-version", "2026-08-20.3", "--out", str(cert), *extra,
    )
    return proc, cert


def validate_certificate(cert: Path, base: Path):
    return run(
        "validate_handoff_certificate.py",
        "--certificate", str(cert), "--artifacts-dir", str(base),
        "--head-sha", HEAD, "--base-sha", BASE, "--contract-version", "2026-08-20.3",
    )


def test_code_scope_requires_codebase_grounding_in_certificate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        proc, _ = build_scoped_certificate(base, "server/issue-42.ts")
        assert proc.returncode == 2
        assert "requires --codebase-grounding" in proc.stdout
        proc, _ = build_scoped_certificate(base, "server/issue-42.ts", "--codebase-grounding", str(write_grounding(base)))
        assert proc.returncode == 2
        assert "requires --code-growth" in proc.stdout


def test_blocked_or_stale_code_growth_cannot_be_certified() -> None:
    for status, subject, message in (("blocked", HEAD, "CODE-GROWTH-001 did not pass"), ("passed", BASE, "code growth is stale")):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            proc, _ = build_scoped_certificate(
                base, "server/issue-42.ts",
                "--codebase-grounding", str(write_grounding(base)), "--code-growth", str(write_growth(base, status, subject)),
            )
            assert proc.returncode == 2
            assert message in proc.stdout


def test_stale_codebase_grounding_cannot_be_certified() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        proc, _ = build_scoped_certificate(base, "server/issue-42.ts", "--codebase-grounding", str(write_grounding(base, BASE)))
        assert proc.returncode == 2
        assert "stale for material head" in proc.stdout


def test_certified_codebase_grounding_resists_downgrade_and_staleness() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        proc, cert = build_scoped_certificate(base, "server/issue-42.ts", *code_evidence(base))
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(cert.read_text(encoding="utf-8"))
        assert payload["controls"] == {"codebase_grounding": {"applicable": True}, "code_growth": {"applicable": True}}
        assert validate_certificate(cert, base).returncode == 0

        for key in ("codebase_grounding", "code_growth"):
            assert key in payload["artifacts"]
            downgraded = dict(payload, controls={**payload["controls"], key: {"applicable": False}})
            cert.write_text(json.dumps(downgraded), encoding="utf-8")
            proc = validate_certificate(cert, base)
            assert proc.returncode == 2
            assert f"omits {key} control" in proc.stdout

            removed = dict(payload, artifacts={k: v for k, v in payload["artifacts"].items() if k != key})
            cert.write_text(json.dumps(removed), encoding="utf-8")
            proc = validate_certificate(cert, base)
            assert proc.returncode == 2
            assert f"certificate lacks artifact {key}" in proc.stdout


def test_documentation_only_scope_does_not_require_codebase_grounding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        proc, cert = build_scoped_certificate(base, "docs/guide.md")
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(cert.read_text(encoding="utf-8"))
        assert payload["controls"] == {"codebase_grounding": {"applicable": False}, "code_growth": {"applicable": False}}
        assert not {"codebase_grounding", "code_growth"} & set(payload["artifacts"])
        assert validate_certificate(cert, base).returncode == 0


def test_code_suffixes_have_a_single_definition() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import plan_execution
    import validate_handoff_certificate
    assert validate_handoff_certificate.CODE_SUFFIXES == plan_execution.CODE_SUFFIXES


def test_build_handoff_certificate_keeps_pr_and_issue_identity_separate() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        files = build_valid_delivery(base)
        cert = base / "handoff-ready.json"
        proc = run(
            "build_handoff_certificate.py",
            "--specification-snapshot", str(files["snapshot"]),
            "--repository", "owner/repo", "--work-item-kind", "pr", "--work-item-number", "43",
            "--issue-number", "42", "--pull-request-number", "43",
            "--work-item-start-sha", BASE, "--issue-changed-path", "server/issue-42.ts",
            *code_evidence(base),
            "--requirement-closure", str(files["closure"]),
            "--attack-matrix", str(files["attack"]),
            "--risk-saturation", str(files["risk"]),
            "--inherited-controls", str(files["inherited"]),
            "--head-sha", HEAD, "--base-sha", BASE,
            "--contract-version", "2026-08-20.3", "--out", str(cert),
        )
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(cert.read_text(encoding="utf-8"))
        assert payload["subject"]["issue_number"] == 42
        assert payload["subject"]["pull_request_number"] == 43
        assert payload["subject"]["work_item_number"] == 43
        assert payload["scope"]["work_item_start_sha"] == BASE
        assert payload["scope"]["issue_changed_paths"] == ["server/issue-42.ts"]


def test_build_handoff_certificate_rejects_snapshot_from_another_issue() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        files = build_valid_delivery(base)
        cert = base / "handoff-ready.json"
        proc = run(
            "build_handoff_certificate.py",
            "--specification-snapshot", str(files["snapshot"]),
            "--repository", "owner/repo", "--work-item-kind", "pr", "--work-item-number", "43",
            "--issue-number", "41", "--pull-request-number", "43",
            "--requirement-closure", str(files["closure"]),
            "--attack-matrix", str(files["attack"]),
            "--risk-saturation", str(files["risk"]),
            "--inherited-controls", str(files["inherited"]),
            "--head-sha", HEAD, "--base-sha", BASE,
            "--contract-version", "2026-08-20.3", "--out", str(cert),
        )
        assert proc.returncode == 2
        assert "snapshot issue differs from handoff subject" in proc.stdout
        assert not cert.exists()




def test_build_standard_profile_certificate_without_critical_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        files = build_valid_delivery(base)
        standard = base / "standard-evidence.json"
        standard.write_text(json.dumps({
            "schema_version": 1,
            "contract_version": "2026-08-20.3",
            "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-001",
                "positive_evidence": ["focused test passed on exact head"],
                "primary_negative_control": {
                    "id": "NEG-STD-1",
                    "status": "passed",
                    "procedure": "Exercise the opposite observable state through the same public boundary.",
                    "expected": "The opposite state is rejected or represented without violating the requirement.",
                    "observed": "The focused exact-head test observed the expected opposite-state behavior.",
                },
                "regression_evidence": ["regression suite passed on exact head"],
            }],
        }), encoding="utf-8")
        cert = base / "handoff-ready.json"
        proc = run(
            "build_handoff_certificate.py",
            "--specification-snapshot", str(files["snapshot"]),
            "--repository", "owner/repo", "--work-item-kind", "issue", "--work-item-number", "42",
            "--requirement-closure", str(files["closure"]),
            "--evidence-profile", "standard",
            "--standard-evidence", str(standard),
            "--head-sha", HEAD, "--base-sha", BASE,
            "--contract-version", "2026-08-20.3", "--out", str(cert),
        )
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(cert.read_text(encoding="utf-8"))
        assert payload["evidence_profile"] == "standard"
        assert set(payload["artifacts"]) >= {"specification_snapshot", "requirement_closure", "standard_evidence"}
        assert "requirement_attack_matrix" not in payload["artifacts"]
        proc = run(
            "validate_handoff_certificate.py",
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--head-sha", HEAD, "--base-sha", BASE,
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 0, proc.stdout


def test_standard_profile_rejects_critical_obligation_flags() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        files = build_valid_delivery(base)
        closure = json.loads(files["closure"].read_text(encoding="utf-8"))
        closure["obligations"][0]["flags"] = ["isolation"]
        files["closure"].write_text(json.dumps(closure), encoding="utf-8")
        standard = base / "standard-evidence.json"
        standard.write_text(json.dumps({
            "schema_version": 1, "contract_version": "2026-08-20.3", "head_sha": HEAD,
            "requirements": [{
                "requirement_id": "REQ-001",
                "positive_evidence": ["positive"],
                "primary_negative_control": {
                    "id": "N", "status": "passed", "procedure": "Exercise isolated sibling scope.",
                    "expected": "No cross-scope effect.", "observed": "No cross-scope effect observed."
                },
                "regression_evidence": ["regression"],
            }]
        }), encoding="utf-8")
        proc = run(
            "validate_standard_evidence.py",
            "--requirement-closure", str(files["closure"]),
            "--standard-evidence", str(standard),
            "--head-sha", HEAD, "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "critical obligations" in proc.stdout


def test_handoff_certificate_supports_sharded_large_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        files = build_valid_delivery(base)
        original_closure = files["closure"].read_bytes()
        original_attack = files["attack"].read_bytes()

        for path in (files["closure"], files["attack"]):
            proc = run(
                "pack_large_audit_artifact.py", str(path),
                "--force", "--shard-bytes", "128",
            )
            assert proc.returncode == 0, proc.stdout

        cert = base / "handoff-ready.json"
        proc = run(
            "build_handoff_certificate.py",
            "--specification-snapshot", str(files["snapshot"]),
            "--repository", "owner/repo", "--work-item-kind", "issue", "--work-item-number", "42",
            "--pull-request", "99", "--base-ref", "develop", "--head-ref", "feature/test",
            "--requirement-closure", str(files["closure"]),
            "--attack-matrix", str(files["attack"]),
            "--risk-saturation", str(files["risk"]),
            "--inherited-controls", str(files["inherited"]),
            "--head-sha", HEAD, "--base-sha", BASE, "--merge-preview-sha", MERGE,
            "--contract-version", "2026-08-20.3", "--out", str(cert),
        )
        assert proc.returncode == 0, proc.stdout
        payload = json.loads(cert.read_text(encoding="utf-8"))

        closure_meta = payload["artifacts"]["requirement_closure"]
        attack_meta = payload["artifacts"]["requirement_attack_matrix"]
        assert closure_meta["logical_sha256"] == hashlib.sha256(original_closure).hexdigest()
        assert attack_meta["logical_sha256"] == hashlib.sha256(original_attack).hexdigest()
        assert closure_meta["artifact_transport"]["format"] == "base64-shards-v1"
        assert attack_meta["artifact_transport"]["format"] == "base64-shards-v1"

        allowed = set(payload["certificate_commit_policy"]["allowed_paths"])
        assert any(path.startswith(".audit/entregar-issue/requirement-closure.parts/") for path in allowed)
        assert any(path.startswith(".audit/entregar-issue/requirement-attack-matrix.parts/") for path in allowed)

        proc = run(
            "validate_handoff_certificate.py",
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--head-sha", HEAD, "--base-sha", BASE, "--merge-preview-sha", MERGE,
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 0, proc.stdout

        first_part = base / closure_meta["artifact_transport"]["parts"][0]["path"]
        first_part.write_bytes(first_part.read_bytes() + b"A")
        proc = run(
            "validate_handoff_certificate.py",
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--head-sha", HEAD, "--base-sha", BASE, "--merge-preview-sha", MERGE,
            "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "transport validation failed" in proc.stdout
