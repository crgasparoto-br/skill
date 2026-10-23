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


def read_event(path: Path) -> tuple[str, int, int, str, str]:
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
    if (pr.get("base") or {}).get("ref") != "develop":
        fail("this collection requires develop as the PR base")
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
    repo, pr, issue, head, base = read_event(args.event)
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
    if args.exit_code is None or args.exit_code < 0:
        fail("missing exact exit code from the test runner")
    facts = {
        "schema_version": 1, "subject_sha": head,
        "execution": {"command": "python -m pytest -vv --junitxml=<output>/pytest-exact-head.xml",
                      "exit_code": args.exit_code,
                      "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                      "log_path": log.name},
        "verification": "passed" if args.exit_code == 0 else "failed",
        "semantic_control_mapping": "UNKNOWN",
        "warning": "A passing runner does not prove requirement coverage or negative controls.",
    }
    write_json(out / "test-execution-facts.json", facts)
    print(f"Recorded exact-SHA test execution, exit={args.exit_code}; semantic mapping UNKNOWN")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=("prepare", "record-tests"), required=True)
    p.add_argument("--event", type=Path)
    p.add_argument("--root", type=Path, default=Path())
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--exit-code", type=int)
    a = p.parse_args()
    try:
        if a.phase == "prepare":
            if a.event is None:
                fail("prepare phase requires --event")
            prepare(a)
        else:
            record_tests(a)
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
