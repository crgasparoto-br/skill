#!/usr/bin/env python3
"""Collect factual exact-head handoff inputs on a GitHub-hosted runner.

The starter is always BLOCKED pending independent requirement/control closure.
It does not push commits or manufacture certificates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
ISSUE_REF = re.compile(r"\b(?:issue|fixes|closes|resolves)\s*#(\d+)\b", re.IGNORECASE)
SHA = re.compile(r"[0-9a-f]{40}\Z")


def fail(message: str) -> None:
    raise ValueError(message)


def read_event(path: Path, base_ref: str = "develop") -> tuple[str, int, int, str, str]:
    event = json.loads(path.read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    repo = (event.get("repository") or {}).get("full_name")
    number = pr.get("number")
    head = (pr.get("head") or {}).get("sha")
    base = (pr.get("base") or {}).get("sha")
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        fail("missing or invalid repository identity")
    if not isinstance(number, int) or number <= 0 or not SHA.fullmatch(str(head)) or not SHA.fullmatch(str(base)):
        fail("missing PR number or exact SHA identities")
    if (pr.get("base") or {}).get("ref") != base_ref:
        fail("pull_request base ref does not match the configured base branch")
    if (pr.get("head") or {}).get("repo", {}).get("full_name") != repo:
        fail("forked PR head requires a separate, read-only evidence policy")
    title = pr.get("title") or ""
    references = set(ISSUE_REF.findall("\n".join((title, pr.get("body") or ""))))
    trailing = re.search(r"\(#(\d+)\)\s*$", title)
    if trailing:
        references.add(trailing.group(1))
    if len(references) != 1:
        fail("expected exactly one unambiguous Issue #N reference in PR title/body")
    issue = int(references.pop())
    if issue == number:
        fail("issue and PR numbers must not be conflated")
    return repo, number, issue, head, base


def check_checkout(repo_root: Path, head: str) -> None:
    p = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True, capture_output=True, check=True)
    if p.stdout.strip() != head:
        fail("checked-out HEAD differs from the pull_request head SHA")


def code_growth_comparison_base(root: Path, start: str, pr_base: str) -> str:
    """Keep the recorded issue start when the PR base predates remediation."""
    result = subprocess.run(["git", "merge-base", "--is-ancestor", start, pr_base],
                            cwd=root, capture_output=True, text=True, check=False)
    if result.returncode not in {0, 1}:
        fail(f"cannot resolve code-growth comparison ancestry: {result.stderr.strip()}")
    return pr_base if result.returncode == 0 else start


def issue_body(repository: str, issue: int, token: str) -> str:
    if not token:
        fail("missing GITHUB_TOKEN; issue source cannot be authenticated")
    api_url = os.environ.get("GITHUB_API_URL", "")
    if not api_url.startswith("https://"):
        fail("GITHUB_API_URL must be provided by GitHub Actions as an HTTPS URL")
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/repos/{repository}/issues/{issue}",
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("pull_request") or not isinstance(payload.get("body"), str) or not payload["body"].strip():
        fail("source Issue #N is not a nonempty issue body")
    return payload["body"]


def run_script(script: str, *args: str) -> None:
    subprocess.run([sys.executable, str(SCRIPTS / script), *args], check=True)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(args: argparse.Namespace) -> None:
    repo, pr, issue, head, base = read_event(args.event, args.base_ref)
    check_checkout(args.root, head)
    body = issue_body(repo, issue, os.environ.get("GITHUB_TOKEN", ""))
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = out / "issue-body.md"
    source.write_text(body, encoding="utf-8")
    audit = out / ".audit" / "entregar-issue"
    snapshot = audit / "specification-snapshot.json"
    closure = audit / "requirement-closure.json"
    run_script("build_specification_snapshot.py", "--repository", repo, "--issue", str(issue),
               "--primary-source-id", f"SRC-ISSUE-{issue}",
               "--source", f"issue-body:SRC-ISSUE-{issue}:{source}", "--out", str(snapshot))
    run_script("init_requirement_closure.py", "--specification-snapshot", str(snapshot), "--out", str(closure))
    metadata = {
        "schema_version": 1, "status": "blocked", "reason": "unverified-requirement-controls",
        "identity": {"repository": repo, "issue_number": issue, "pull_request_number": pr,
                     "material_head_sha": head, "base_sha": base},
        "source": {"issue_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                   "uri": f"https://github.com/{repo}/issues/{issue}"},
        "unverified": ["requirement-closure", "test-decision-evidence", "codebase-grounding",
                       "code-growth", "risk-profile-evidence", "audit-remediation-lineage",
                       "handoff-certificate", "terminal-handoff"],
        "base_ref": args.base_ref,
        "runner": "github-hosted-actions", "generated_at": datetime.now(UTC).isoformat(),
    }
    write_json(out / "handoff-preflight.json", metadata)
    print(f"BLOCKED: evidence starter for Issue #{issue} PR #{pr} @ {head}; certification not asserted")


def record_tests(args: argparse.Namespace) -> None:
    out = args.out.resolve()
    metadata = json.loads((out / "handoff-preflight.json").read_text(encoding="utf-8"))
    head = metadata["identity"]["material_head_sha"]
    check_checkout(args.root, head)
    log = out / "pytest-exact-head.log"
    if not log.is_file() or not log.stat().st_size:
        fail("missing test log; cannot attest execution")
    if args.exit_code is None or args.exit_code < 0 or not args.test_command.strip():
        fail("missing exact exit code or command from the test runner")
    facts = {
        "schema_version": 1, "subject_sha": head,
        "execution": {"command": args.test_command,
                      "exit_code": args.exit_code,
                      "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                      "log_path": log.name},
        "verification": "passed" if args.exit_code == 0 else "failed",
        "semantic_control_mapping": "UNKNOWN",
        "warning": "A passing runner does not prove requirement coverage or negative controls.",
    }
    write_json(out / "test-execution-facts.json", facts)
    print(f"Recorded exact-SHA test execution, exit={args.exit_code}; semantic mapping UNKNOWN")



def _audit_path(out: Path, filename: str) -> Path:
    """Resolve a declared evidence filename inside the local, ephemeral audit folder."""
    if not isinstance(filename, str) or not re.fullmatch(r"[a-z][a-z0-9-]*\.json", filename):
        fail("evidence inputs require a plain JSON filename, not a path")
    path = out / ".audit" / "entregar-issue" / filename
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        fail(f"required evidence is missing or invalid: {filename}")
    return path


def _load_record(path: Path) -> dict:
    item = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(item, dict):
        fail(f"expected a JSON object: {path.name}")
    return item


def _record_status(out: Path, status: str, reason: str, subject_sha: str) -> None:
    write_json(out / "handoff-certification-status.json", {
        "schema_version": 1, "status": status, "reason": reason, "material_head_sha": subject_sha,
        "certificate_published": False, "terminal_ready": False,
    })


def _verify_exact_starter(out: Path, repo: str, pr: int, issue: int,
                          head: str, base: str) -> None:
    """Verify GitHub issue, PR and immutable test-run provenance."""
    preflight = _load_record(out / "handoff-preflight.json")
    identity = preflight.get("identity")
    expected = {"repository": repo, "issue_number": issue, "pull_request_number": pr,
                "material_head_sha": head, "base_sha": base}
    if not isinstance(identity, dict) or any(identity.get(k) != v for k, v in expected.items()):
        fail("the evidence starter does not match the exact current PR identity")

    execution = _load_record(out / "test-execution-facts.json")
    facts = execution.get("execution") or {}
    log = out / "pytest-exact-head.log"
    if (execution.get("subject_sha") != head or facts.get("exit_code") != 0
            or not log.is_file() or not log.stat().st_size
            or hashlib.sha256(log.read_bytes()).hexdigest() != facts.get("log_sha256")
            or not (out / "pytest-exact-head.xml").is_file()):
        fail("exact-SHA test execution, log digest or JUnit evidence is invalid")


def _read_certification_inputs(out: Path, args: argparse.Namespace, head: str):
    """Reject stale, ambiguous, or unreachable work-item inputs."""
    inputs_path = out / "certification-inputs.json"
    if not inputs_path.is_file():
        fail("certification-inputs.json absent: semantic closures have not been supplied")
    inputs = _load_record(inputs_path)
    if inputs.get("subject_sha") != head:
        fail("certification inputs do not match the material head SHA")
    profile = inputs.get("evidence_profile")
    if profile not in {"light", "standard", "critical"}:
        fail("explicit valid evidence_profile required; never infer risk from CI success")
    start = inputs.get("work_item_start_sha")
    if not isinstance(start, str) or not SHA.fullmatch(start):
        fail("valid, recorded work_item_start_sha required")
    if inputs.get("audit_history") not in {"verified-no-rejection", "previous-rejection"}:
        fail("verified audit history is required; absence must remain UNKNOWN")
    if not isinstance(inputs.get("head_ref"), str) or not inputs["head_ref"].strip():
        fail("missing head_ref binding")
    if inputs.get("base_ref") != args.base_ref:
        fail("base_ref mismatch")

    gitcheck = subprocess.run(["git", "merge-base", "--is-ancestor", start, head], cwd=args.root,
                              capture_output=True, check=False)
    if gitcheck.returncode != 0:
        fail("work_item_start_sha must be a reachable ancestor of the exact material SHA")
    diff = subprocess.run(["git", "diff", "--name-only", "--no-renames", start, head],
                          cwd=args.root, capture_output=True, text=True, check=True)
    changed = sorted({line.strip() for line in diff.stdout.splitlines() if line.strip()})
    if not changed:
        fail("cannot certify an issue with an empty or unverified material diff")

    return inputs, profile, start, changed


def _resolve_certification_requirements(out: Path, args: argparse.Namespace,
                                        repo: str, pr: int, issue: int, head: str, base: str):
    """Resolve only explicitly evidenced controls for the material diff."""
    _verify_exact_starter(out, repo, pr, issue, head, base)
    inputs, profile, start, changed = _read_certification_inputs(out, args, head)
    required = {"specification_snapshot": "specification-snapshot.json",
                "requirement_closure": "requirement-closure.json"}
    if profile == "standard":
        required["standard_evidence"] = "standard-evidence.json"
    if profile == "critical":
        required.update({"attack_matrix": "requirement-attack-matrix.json",
                         "risk_saturation": "risk-saturation.json",
                         "inherited_controls": "inherited-controls.json"})
    if inputs.get("audit_history") == "previous-rejection":
        required.update({"audit_remediation": "audit-remediation.json",
                         "audit_source_result": "audit-source-result.json",
                         "learning_closure": "learning-closure.json",
                         "audit_escape_closure": "audit-escape-closure.json",
                         "previous_audit_escape_closure": "previous-audit-escape-closure.json"})
    touched_code = any(path.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".sh")) for path in changed)
    touched_tests = any("test" in path.lower() or path.endswith((".cy.ts", ".spec.ts")) for path in changed)
    if touched_code or touched_tests:
        required["codebase_grounding"] = "codebase-grounding.json"
    if touched_code:
        required["code_growth"] = "code-growth.json"

    resolved = {key: _audit_path(out, filename) for key, filename in required.items()}
    for item in resolved.values():
        record = _load_record(item)
        if record.get("subject_sha") not in (None, head) and record.get("head_sha") not in (None, head):
            fail(f"stale evidence report: {item.name}")


    return inputs, start, profile, changed, resolved


def result_path_arguments(root: Path, out: Path, inputs: dict, resolved: dict) -> list[str]:
    """Authorize the exact result files needed to retain validated evidence."""
    arguments = []
    if "codebase_grounding" in resolved:
        from bind_grounding_execution import grounding_result_paths
        for relative in grounding_result_paths(root, out, _load_record(resolved["codebase_grounding"])):
            arguments.extend(["--allow-result-path", relative])
    if "previous_audit_escape_closure" in resolved:
        arguments.extend(["--allow-result-path",
                          ".audit/entregar-issue/previous-audit-escape-closure.json"])
    if inputs.get("remediation_mode") in {"systemic-remediation", "mixed-remediation"}:
        arguments.extend(["--allow-result-path",
                          ".audit/entregar-issue/previous-inherited-controls.json"])
    # The certificate must authorize the exact issue source bytes it references.
    snapshot = _load_record(resolved["specification_snapshot"])
    for source in snapshot.get("sources", []):
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            fail("malformed specification source path")
        relative = source["path"]
        if not relative.startswith("specification-sources/") or ".." in Path(relative).parts:
            fail("specification source must remain under specification-sources")
        source_path = out / ".audit" / "entregar-issue" / relative
        if not source_path.is_file() or source_path.is_symlink():
            fail("required specification source bytes are missing")
        if hashlib.sha256(source_path.read_bytes()).hexdigest() != source.get("sha256"):
            fail("specification source bytes differ from the immutable snapshot")
        arguments.extend(["--allow-result-path", f".audit/entregar-issue/{relative}"])
    return arguments


def certify(args: argparse.Namespace) -> None:
    """Certify only authenticated, complete evidence; NEVER perform a repository write."""
    if args.event is None:
        fail("certify phase requires --event")
    repo, pr, issue, head, base = read_event(args.event, args.base_ref)
    check_checkout(args.root, head)
    out = args.out.resolve()
    audit = out / ".audit" / "entregar-issue"
    _record_status(out, "blocked", "unverified-requirement-controls", head)
    (audit / "handoff-ready.json").unlink(missing_ok=True)
    inputs, start, profile, changed, resolved = _resolve_certification_requirements(
        out, args, repo, pr, issue, head, base)

    if "codebase_grounding" in resolved:
        run_script("validate_codebase_grounding.py", "--repo", str(args.root),
                   "--report", str(resolved["codebase_grounding"]),
                   "--base-sha", start, "--head-sha", head)
    if "code_growth" in resolved:
        growth_args = ["--repo", str(args.root), "--base-sha", start,
                       "--comparison-base-sha", code_growth_comparison_base(args.root, start, base), "--head-sha", head,
                       "--out", str(resolved["code_growth"])]
        justification_path = (args.root / ".github" / "handoff-evidence"
                              / f"issue-{issue}" / "code-growth-justifications.json")
        if justification_path.is_file() and not justification_path.is_symlink():
            growth_args.extend(["--justifications", str(justification_path)])
        run_script("check_code_growth.py", *growth_args)

    builder = [
        "--specification-snapshot", str(resolved["specification_snapshot"]),
        "--repository", repo, "--issue-number", str(issue), "--work-item-kind", "pr",
        "--work-item-number", str(pr), "--pull-request-number", str(pr),
        "--work-item-start-sha", start, "--base-ref", args.base_ref,
        "--head-ref", inputs["head_ref"],
        "--requirement-closure", str(resolved["requirement_closure"]),
        "--evidence-profile", profile, "--head-sha", head, "--base-sha", base,
        "--source-repository-root", str(args.root.resolve()),
        "--out", str(audit / "handoff-ready.json"),
    ]
    for path in changed:
        builder.extend(["--issue-changed-path", path])
    builder.extend(result_path_arguments(args.root, out, inputs, resolved))

    switches = {
        "standard_evidence": "--standard-evidence", "attack_matrix": "--attack-matrix",
        "risk_saturation": "--risk-saturation", "inherited_controls": "--inherited-controls",
        "codebase_grounding": "--codebase-grounding", "code_growth": "--code-growth",
        "audit_remediation": "--audit-remediation", "audit_source_result": "--audit-source-result",
        "learning_closure": "--learning-closure", "audit_escape_closure": "--audit-escape-closure",
        "previous_audit_escape_closure": "--previous-audit-escape-closure",
    }
    for key, option in switches.items():
        if key in resolved and key != "previous_audit_escape_closure":
            builder.extend([option, str(resolved[key])])
    if inputs["audit_history"] == "previous-rejection":
        builder.extend(["--previous-independent-rejection", "--previous-audit-escape-closure",
                        str(resolved["previous_audit_escape_closure"])])
    if profile == "critical" and (audit / "evidence-provenance.json").is_file():
        builder.extend(["--evidence-provenance", str(_audit_path(out, "evidence-provenance.json"))])
    if "remediation_mode" in inputs:
        if inputs["remediation_mode"] not in {"targeted-remediation", "systemic-remediation", "mixed-remediation"}:
            fail("invalid remediation mode")
        builder.extend(["--remediation-mode", inputs["remediation_mode"]])
    if inputs.get("remediation_mode") in {"systemic-remediation", "mixed-remediation"}:
        builder.extend(["--previous-inherited-controls",
                        str(_audit_path(out, "previous-inherited-controls.json"))])

    try:
        if "audit_source_result" in resolved:
            from certify_handoff_postcondition import prepare_replay_finalization
            builder = prepare_replay_finalization(args, builder, resolved, head, base, run_script)
        run_script("build_handoff_certificate.py", *builder)
        run_script("validate_handoff_certificate.py",
                   "--certificate", str(audit / "handoff-ready.json"),
                   "--artifacts-dir", str(audit),
                   "--head-sha", head, "--base-sha", base,
                   "--repository", repo, "--issue-number", str(issue),
                   "--work-item-kind", "pr", "--work-item-number", str(pr),
                   "--pull-request-number", str(pr),
                   "--work-item-start-sha", start,
                   "--base-ref", args.base_ref, "--head-ref", inputs["head_ref"],
                   *(arg for path in changed for arg in ("--issue-changed-path", path)),
                   "--source-repository-root", str(args.root.resolve()))
    except (ValueError, OSError, subprocess.CalledProcessError):
        (audit / "handoff-ready.json").unlink(missing_ok=True)
        raise
    _record_status(out, "certificate-generated", "publication-and-terminal-guard-still-required", head)
    print("CERTIFICATE GENERATED: publication is NOT authorized until prepublication and terminal guards pass")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=("prepare", "record-tests", "certify"), required=True)
    p.add_argument("--event", type=Path)
    p.add_argument("--root", type=Path, default=Path())
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--exit-code", type=int)
    p.add_argument("--base-ref", default="develop")
    p.add_argument("--test-command", default="python -m pytest -vv --junitxml=pytest-exact-head.xml")
    a = p.parse_args()
    try:
        if a.phase == "prepare":
            if a.event is None:
                fail("prepare phase requires --event")
            prepare(a)
        elif a.phase == "record-tests":
            record_tests(a)
        else:
            certify(a)
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        if a.phase == "certify":
            _record_status(a.out.resolve(), "blocked", str(exc),
                           (json.loads(a.event.read_text()).get("pull_request") or {}).get("head", {}).get("sha", "unknown") if a.event and a.event.is_file() else "unknown")
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
