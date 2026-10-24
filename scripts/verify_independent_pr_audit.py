#!/usr/bin/env python3
"""Fail-closed independent GitHub review gate; run only from a trusted base checkout."""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.parse
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "entregar-issue" / "scripts"))
from verify_github_completion import audit_contract, github

if TYPE_CHECKING:
    from collections.abc import Callable

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
APP_ID = 15368  # GitHub Actions
TECHNICAL = ("Structure and tests", "Offline authorization tests")
HANDOFF = "collect / Require certified semantic handoff (exact SHA)"
AUTHORIZED_PERMISSIONS = frozenset({"write", "maintain", "admin"})
# Only these repository-owned workflow entrypoints may supply these check jobs.
EXPECTED_WORKFLOWS = {
    TECHNICAL[0]: ".github/workflows/validate.yml",
    TECHNICAL[1]: ".github/workflows/github-audit-mcp.yml",
    HANDOFF: ".github/workflows/handoff-evidence.yml",
}


def page_all(repo: str, suffix: str, token: str, max_pages: int = 25) -> list[dict]:
    """Refuse truncated inventories rather than omitting a contributor or review."""
    collected: list[dict] = []
    for page in range(1, max_pages + 1):
        batch = github(f"/repos/{repo}/{suffix}?per_page=100&page={page}", token)
        if not isinstance(batch, list) or any(not isinstance(x, dict) for x in batch):
            raise ValueError("invalid GitHub paginated collection")
        collected.extend(batch)
        if len(batch) < 100:
            return collected
    raise ValueError("GitHub review/commit inventory exceeds bounded pagination")


def exact_set(value: object, field: str, *, allow_empty: bool = False) -> set[str]:
    if (not isinstance(value, list) or (not value and not allow_empty)
            or any(not isinstance(x, str) or not x.strip() for x in value)
            or len(value) != len(set(value))):
        raise ValueError(f"invalid independent audit {field}")
    return set(value)


def reviewed_contract(review: dict, head: str) -> bool:
    contract = audit_contract(review)
    if (not contract or contract.get("head_sha") != head
            or not isinstance(contract.get("audit_round"), str)
            or not contract["audit_round"].strip()):
        return False
    try:
        findings = exact_set(contract.get("finding_ids"), "finding_ids", allow_empty=True)
        verified = exact_set(contract.get("verified_finding_ids"), "verified_finding_ids",
                             allow_empty=True)
        excluded = exact_set(contract.get("accepted_exclusions"), "accepted_exclusions",
                             allow_empty=True)
    except ValueError:
        return False
    return not (verified & excluded) and findings == (verified | excluded)


def verify_trusted_workflow_source(
        repo: str, workflow: str, base_sha: str, head: str, token: str) -> None:
    """Reject a PR-altered workflow even when Actions reports the official path."""
    source = [
        github(f"/repos/{repo}/contents/{workflow}?ref={ref}", token)
        for ref in (base_sha, head)
    ]
    if any(
        not isinstance(item, dict) or item.get("type") != "file"
        or not isinstance(item.get("sha"), str)
        or not SHA.fullmatch(item["sha"])
        for item in source
    ):
        raise ValueError("trusted workflow source unavailable")
    if source[0]["sha"] != source[1]["sha"]:
        raise ValueError(f"required workflow differs from trusted base: {workflow}")


def trusted_workflow_check(repo: str, number: int, name: str, check: dict,
                           head: str, base_sha: str, token: str) -> bool:
    """Authenticate the job and pin its workflow source to the trusted base."""
    details = check.get("details_url")
    if not isinstance(details, str):
        return False
    parsed = urllib.parse.urlsplit(details)
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or parsed.query or parsed.fragment):
        return False
    match = re.fullmatch(
        rf"/{re.escape(repo)}/actions/runs/([1-9][0-9]*)/job/([1-9][0-9]*)",
        parsed.path,
    )
    suite = (check.get("check_suite") or {}).get("id")
    check_id = check.get("id")
    if not match or type(suite) is not int or type(check_id) is not int:
        return False
    run_id, job_id = (int(value) for value in match.groups())
    run = github(f"/repos/{repo}/actions/runs/{run_id}", token)
    job = github(f"/repos/{repo}/actions/jobs/{job_id}", token)
    if not isinstance(run, dict) or not isinstance(job, dict):
        raise ValueError("invalid GitHub Actions workflow provenance")
    workflow_path = run.get("path")
    if not isinstance(workflow_path, str):
        return False
    api_root = (os.environ.get("GITHUB_API_URL")
                or "https://" + "api." + "github.com").rstrip("/")
    pr_links = run.get("pull_requests")
    identity_matches = (
        workflow_path.split("@", 1)[0] == EXPECTED_WORKFLOWS[name]
        and run.get("check_suite_id") == suite
        and run.get("head_sha") == head
        and run.get("event") == "pull_request"
        and isinstance(pr_links, list)
        and any(
            p.get("number") == number
            and isinstance(p.get("base"), dict)
            and p["base"].get("sha") == base_sha
            for p in pr_links if isinstance(p, dict)
        )
        and job.get("id") == job_id
        and job.get("run_id") == run_id
        and job.get("name") == name
        and job.get("check_run_url") ==
        f"{api_root}/repos/{repo}/check-runs/{check_id}"
    )
    if not identity_matches:
        return False

    # A workflow reported by the Actions app can still have untrusted code.
    verify_trusted_workflow_source(repo, EXPECTED_WORKFLOWS[name], base_sha, head, token)

    # A failed official job must remain eligible for recency selection; filtering
    # by success here would let an older green run hide a newer red run.
    if (job.get("status") != check.get("status")
            or job.get("conclusion") != check.get("conclusion")):
        raise ValueError("GitHub Actions job/check outcome mismatch")
    if check.get("conclusion") == "success" and (
            run.get("status") != "completed" or run.get("conclusion") != "success"):
        raise ValueError("required GitHub Actions workflow not green")
    return True


def required_checks_green(checks: dict, head: str, base: str,
                          trusted: Callable[[str, dict], bool]) -> None:
    if not isinstance(checks, dict) or not isinstance(checks.get("check_runs"), list):
        raise ValueError("check-run inventory missing")
    runs = checks["check_runs"]
    if checks.get("total_count", len(runs)) > len(runs):
        raise ValueError("check-run inventory truncated")
    names = (*TECHNICAL, *((HANDOFF,) if base == "develop" else ()))
    for name in names:
        matches = [
            c for c in runs if c.get("name") == name and c.get("head_sha") == head
            and (c.get("app") or {}).get("id") == APP_ID
            and trusted(name, c)
        ]
        if not matches:
            raise ValueError(f"required trusted exact-HEAD check missing: {name}")
        latest = max(matches, key=lambda c: int(c.get("id") or 0))
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ValueError(f"required exact-HEAD check not green: {name}")


def contributor_logins(pr: dict, commits: list[dict]) -> set[str]:
    author = (pr.get("user") or {}).get("login")
    if not isinstance(author, str) or not author.strip():
        raise ValueError("PR author missing")
    implementers = {author.casefold()}
    for commit in commits:
        author_user = (commit.get("author") or {}).get("login")
        committer_user = (commit.get("committer") or {}).get("login")
        # GitHub may return null for unlinked Git identities. Never treat an
        # unknown contributor as different from the purported reviewer.
        if any(not isinstance(x, str) or not x.strip()
               for x in (author_user, committer_user)):
            raise ValueError("commit contributor identity unavailable")
        implementers.update((author_user.casefold(), committer_user.casefold()))
    return implementers


def latest_reviews(reviews: list[dict]) -> dict[str, dict]:
    current: dict[str, dict] = {}
    ordered = sorted(reviews, key=lambda x: (str(x.get("submitted_at") or ""), int(x.get("id") or 0)))
    for review in ordered:
        user = (review.get("user") or {}).get("login")
        if user:
            current[user.casefold()] = review
    return current


def is_independent_approval(user: str, review: dict, implementers: set[str], head: str) -> bool:
    if review.get("state") != "APPROVED" or user in implementers or user.endswith("[bot]"):
        return False
    if review.get("commit_id") != head or not review.get("html_url") or not review.get("submitted_at"):
        return False
    return reviewed_contract(review, head)


def is_authorized_reviewer(repo: str, reviewer: str, token: str) -> bool:
    """Only current repository collaborators with write-capable roles can approve."""
    if not re.fullmatch(r"[A-Za-z0-9-]+", reviewer):
        return False
    try:
        permission = github(f"/repos/{repo}/collaborators/{reviewer}/permission", token)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False  # Non-collaborator; other eligible approvals may exist.
        raise
    if not isinstance(permission, dict):
        raise ValueError("invalid GitHub collaborator permission response")
    return permission.get("permission") in AUTHORIZED_PERMISSIONS


def verify_gate(pr: dict, reviews: list[dict], commits: list[dict],
                checks: dict, base: str, authorized: Callable[[str], bool],
                trusted: Callable[[str, dict], bool]) -> str:
    """Authenticate identities, exact-HEAD checks and an actual independent review."""
    if base not in ("develop", "main") or pr.get("base", {}).get("ref") != base:
        raise ValueError("PR base differs from protected branch")
    if pr.get("state") != "open":
        raise ValueError("PR is not open")
    head = (pr.get("head") or {}).get("sha")
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise ValueError("invalid PR HEAD")
    if not reviews or not commits:
        raise ValueError("independent audit requires review history and commits")
    implementers = contributor_logins(pr, commits)
    required_checks_green(checks, head, base, trusted)
    current = latest_reviews(reviews)
    if any(x.get("state") == "CHANGES_REQUESTED" for x in current.values()):
        raise ValueError("outstanding request for changes")
    accepted = [
        review for user, review in current.items()
        if is_independent_approval(user, review, implementers, head) and authorized(user)
    ]
    if not accepted:
        raise ValueError("independent APPROVED review with complete exact-SHA audit contract absent")
    return str(accepted[-1]["html_url"])


def run(repo: str, number: int, base: str, base_sha: str, token: str) -> str:
    if not SHA.fullmatch(base_sha):
        raise ValueError("invalid trusted base SHA")
    pr = github(f"/repos/{repo}/pulls/{number}", token)
    if pr.get("base", {}).get("ref") != base or pr["base"].get("sha") != base_sha:
        raise ValueError("trusted PR base SHA changed before verification")
    reviews = page_all(repo, f"pulls/{number}/reviews", token)
    commits = page_all(repo, f"pulls/{number}/commits", token)
    head = pr["head"]["sha"]
    checks = github(f"/repos/{repo}/commits/{head}/check-runs?per_page=100", token)
    approval = verify_gate(
        pr, reviews, commits, checks, base,
        lambda reviewer: is_authorized_reviewer(repo, reviewer, token),
        lambda name, check: trusted_workflow_check(
            repo, number, name, check, head, base_sha, token),
    )
    current = github(f"/repos/{repo}/pulls/{number}", token)
    if (current.get("head", {}).get("sha") != head
            or current.get("base", {}).get("ref") != base
            or current["base"].get("sha") != base_sha):
        raise ValueError("PR HEAD or trusted base SHA changed while validating independent audit")

    # Reviews can be edited/dismissed and CI checks rerun without changing HEAD.
    # Reauthenticate the live review, permissions and checks before returning.
    latest_reviews_snapshot = page_all(repo, f"pulls/{number}/reviews", token)
    latest_checks = github(f"/repos/{repo}/commits/{head}/check-runs?per_page=100", token)
    current_approval = verify_gate(
        current, latest_reviews_snapshot, commits, latest_checks, base,
        lambda reviewer: is_authorized_reviewer(repo, reviewer, token),
        lambda name, check: trusted_workflow_check(
            repo, number, name, check, head, base_sha, token),
    )
    if current_approval != approval:
        raise ValueError("independent approval changed while validating")
    final = github(f"/repos/{repo}/pulls/{number}", token)
    if (final.get("head", {}).get("sha") != head
            or final.get("base", {}).get("ref") != base
            or final["base"].get("sha") != base_sha):
        raise ValueError("PR HEAD or trusted base SHA changed while validating independent audit")
    return current_approval


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--base", choices=("develop", "main"), required=True)
    parser.add_argument("--base-sha", required=True)
    args = parser.parse_args()
    if not REPO.fullmatch(args.repo) or args.pr < 1:
        parser.error("invalid repository or PR")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        if not token:
            raise ValueError("authenticated GitHub token unavailable")
        url = run(args.repo, args.pr, args.base, args.base_sha, token)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2
    print(f"INDEPENDENT AUDIT APPROVED on exact HEAD: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
