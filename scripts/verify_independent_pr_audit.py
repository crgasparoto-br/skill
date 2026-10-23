#!/usr/bin/env python3
"""Fail-closed independent GitHub review gate; run only from a trusted base checkout."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "entregar-issue" / "scripts"))
from verify_github_completion import audit_contract, github

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
APP_ID = 15368  # GitHub Actions
TECHNICAL = ("Structure and tests", "Offline authorization tests")
HANDOFF = "collect / Require certified semantic handoff (exact SHA)"


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
        findings = exact_set(contract.get("finding_ids"), "finding_ids")
        verified = exact_set(contract.get("verified_finding_ids"), "verified_finding_ids",
                             allow_empty=True)
        excluded = exact_set(contract.get("accepted_exclusions"), "accepted_exclusions",
                             allow_empty=True)
    except ValueError:
        return False
    return not (verified & excluded) and findings == (verified | excluded)


def required_checks_green(checks: dict, head: str, base: str) -> None:
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
        ]
        if not matches:
            raise ValueError(f"required exact-HEAD check missing: {name}")
        latest = max(matches, key=lambda c: int(c.get("id") or 0))
        if latest.get("status") != "completed" or latest.get("conclusion") != "success":
            raise ValueError(f"required exact-HEAD check not green: {name}")


def contributor_logins(pr: dict, commits: list[dict]) -> set[str]:
    author = (pr.get("user") or {}).get("login")
    if not author:
        raise ValueError("PR author missing")
    implementers = {author.casefold()}
    for commit in commits:
        author_user = (commit.get("author") or {}).get("login")
        committer_user = (commit.get("committer") or {}).get("login")
        if not author_user and not committer_user:
            raise ValueError("commit contributor identity unavailable")
        implementers.update(x.casefold() for x in (author_user, committer_user) if x)
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


def verify_gate(pr: dict, reviews: list[dict], commits: list[dict],
                checks: dict, base: str) -> str:
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
    required_checks_green(checks, head, base)
    current = latest_reviews(reviews)
    if any(x.get("state") == "CHANGES_REQUESTED" for x in current.values()):
        raise ValueError("outstanding request for changes")
    accepted = [
        review for user, review in current.items()
        if is_independent_approval(user, review, implementers, head)
    ]
    if not accepted:
        raise ValueError("independent APPROVED review with complete exact-SHA audit contract absent")
    return str(accepted[-1]["html_url"])


def run(repo: str, number: int, base: str, token: str) -> str:
    pr = github(f"/repos/{repo}/pulls/{number}", token)
    reviews = page_all(repo, f"pulls/{number}/reviews", token)
    commits = page_all(repo, f"pulls/{number}/commits", token)
    head = pr["head"]["sha"]
    checks = github(f"/repos/{repo}/commits/{head}/check-runs?per_page=100", token)
    approval = verify_gate(pr, reviews, commits, checks, base)
    current = github(f"/repos/{repo}/pulls/{number}", token)
    if current.get("head", {}).get("sha") != head or current.get("base", {}).get("ref") != base:
        raise ValueError("PR changed while validating independent audit")
    return approval


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--base", choices=("develop", "main"), required=True)
    args = parser.parse_args()
    if not REPO.fullmatch(args.repo) or args.pr < 1:
        parser.error("invalid repository or PR")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        if not token:
            raise ValueError("authenticated GitHub token unavailable")
        url = run(args.repo, args.pr, args.base, token)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2
    print(f"INDEPENDENT AUDIT APPROVED on exact HEAD: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
