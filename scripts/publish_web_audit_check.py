#!/usr/bin/env python3
"""Trusted GitHub Actions check publisher for signed, independently produced audits.

Run only from a trusted default-branch workflow with checks:write.
Candidate source is never executed or interpreted as workflow instructions.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from produce_web_independent_audit import github, verify_technical_checks
from verify_independent_pr_audit import required_checks_green, trusted_workflow_check

SHA = re.compile(r"[a-f0-9]{40}\Z")
CHECK_NAME = "Verify independent web audit (exact SHA)"
TRUSTED_WORKFLOW = ".github/workflows/produce-independent-audit.yml"


def call_api(repo: str, suffix: str, token: str, body: dict) -> dict:
    api_root = os.environ.get("GITHUB_API_URL")
    if not api_root or not api_root.startswith("https://"):
        raise ValueError("trusted GitHub API URL unavailable")
    req = urllib.request.Request(
        f"{api_root.rstrip('/')}/repos/{repo}/{suffix}",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "solverit-web-audit-check",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def discover_target(repo: str, report: dict, token: str) -> dict:
    sha = report.get("head_sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError("missing signed report head SHA")
    pulls = github(repo, f"commits/{sha}/pulls?per_page=100", token)
    if not isinstance(pulls, list) or len(pulls) >= 100:
        raise ValueError("incomplete PR association inventory")
    matching = [
        pr for pr in pulls if isinstance(pr, dict) and pr.get("state") == "open"
        and pr.get("head", {}).get("sha") == sha
        and pr.get("base", {}).get("ref") in ("develop", "main")
    ]
    if len(matching) != 1:
        raise ValueError("signed head must belong to exactly one open PR")
    pr = github(repo, f"pulls/{matching[0]['number']}", token)
    if not isinstance(pr, dict):
        raise ValueError("PR identity unavailable")
    refs = {int(v) for v in re.findall(
        r"(?i)\b(?:closes|fixes|refs)\s+#(\d+)\b", pr.get("body") or ""
    )}
    if refs != {report.get("issue")}:
        raise ValueError("report issue does not match canonical PR reference")
    return pr


def verify_producer(repo: str, run_id: int, token: str) -> dict:
    run = github(repo, f"actions/runs/{run_id}", token)
    if not isinstance(run, dict):
        raise ValueError("missing producer workflow run")
    if (run.get("repository", {}).get("full_name") != repo
        or str(run.get("path", "")).split("@")[0] != TRUSTED_WORKFLOW
        or run.get("event") != "workflow_run"
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"):
        raise ValueError("producer is not a successful trusted workflow_run")
    return run


def publish_check(repo: str, sha: str, conclusion: str, details_url: str,
                  summary: str, token: str) -> dict:
    if conclusion not in ("success", "failure") or not SHA.fullmatch(sha):
        raise ValueError("invalid check publication arguments")
    return call_api(repo, "check-runs", token, {
        "name": CHECK_NAME,
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
        "details_url": details_url,
        "output": {
            "title": "Independent signed audit: " + conclusion,
            "summary": summary[:65000],
        },
    })


def verify_material(repo: str, pr: dict, report: Path, registry: Path, run_id: int,
                    token: str) -> None:
    current = github(repo, f"pulls/{pr['number']}", token)
    if not isinstance(current, dict) or current.get("state") != "open":
        raise ValueError("PR is no longer open")
    if any(
        current.get(key, {}).get("sha") != pr.get(key, {}).get("sha")
        for key in ("head", "base")
    ) or current.get("merge_commit_sha") != pr.get("merge_commit_sha"):
        raise ValueError("PR target changed while verifying audit")
    audited = json.loads(report.read_text(encoding="utf-8"))
    cmd = [
        sys.executable, str(Path(__file__).resolve().parent / "verify_web_external_audit.py"),
        "--report", str(report), "--trusted-auditors", str(registry),
        "--repository", repo, "--issue", str(audited["issue"]),
        "--base-ref", current["base"]["ref"], "--base-sha", current["base"]["sha"],
        "--head-sha", current["head"]["sha"],
        "--merge-preview-sha", current["merge_commit_sha"],
        "--audit-context-id", f"github-actions:{run_id}",
    ]
    verified = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if verified.returncode:
        raise ValueError(f"external signature or exact target rejected: {verified.stderr[:500]}")
    verify_technical_checks({
        "repository": repo,
        "head_sha": current["head"]["sha"],
        "base_ref": current["base"]["ref"],
    }, token)
    check_inventory = github(repo, f"commits/{current['head']['sha']}/check-runs?per_page=100", token)
    required_checks_green(
        check_inventory, current["head"]["sha"], current["base"]["ref"],
        lambda name, check: trusted_workflow_check(
            repo, current["number"], name, check, current["head"]["sha"],
            current["base"]["sha"], token,
        ),
    )
    # Re-fetch after all validations, before publishing a success check.
    latest = github(repo, f"pulls/{pr['number']}", token)
    if not isinstance(latest, dict) or latest.get("state") != "open":
        raise ValueError("PR closed before publishing")
    if (latest.get("head", {}).get("sha") != current["head"]["sha"]
        or latest.get("base", {}).get("sha") != current["base"]["sha"]
        or latest.get("merge_commit_sha") != current["merge_commit_sha"]):
        raise ValueError("PR changed before publishing")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repository", required=True)
    p.add_argument("--producer-run-id", required=True, type=int)
    p.add_argument("--report", required=True, type=Path)
    p.add_argument("--trusted-auditors", required=True, type=Path)
    args = p.parse_args()
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("BLOCK: GitHub token missing", file=sys.stderr)
        return 2
    try:
        run = verify_producer(args.repository, args.producer_run_id, token)
        report_value = json.loads(args.report.read_text(encoding="utf-8"))
        if report_value.get("repository") != args.repository:
            raise ValueError("foreign report repository")
        pr = discover_target(args.repository, report_value, token)
        sha = pr["head"]["sha"]
        try:
            verify_material(
                args.repository, pr, args.report, args.trusted_auditors,
                args.producer_run_id, token
            )
            conclusion, summary = "success", "Verified signed independent audit, exact SHA, issue, merge preview and mandatory technical certification."
        except (ValueError, KeyError, OSError) as exc:
            conclusion, summary = "failure", f"BLOCK: {exc}"
        published = publish_check(
            args.repository, sha, conclusion,
            run.get("html_url") or f"https://github.com/{args.repository}/actions/runs/{args.producer_run_id}",
            summary, token
        )
        if published.get("conclusion") != conclusion:
            raise ValueError("GitHub did not confirm published check outcome")
        print(f"{conclusion.upper()}: {summary}")
        return 0 if conclusion == "success" else 2
    except (ValueError, KeyError, OSError, urllib.error.URLError) as exc:
        print(f"BLOCK: no authenticated independent audit check could be published: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
