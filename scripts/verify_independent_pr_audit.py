#!/usr/bin/env python3
"""Fail-closed independent GitHub review gate; run only from a trusted base checkout."""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
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


PIN_MIGRATION_PATH = "config/trusted-workflow-pin-migrations.json"
PIN_MIGRATION_FILE = Path(__file__).resolve().parents[1] / PIN_MIGRATION_PATH
PIN_LINE = re.compile(
    r"(?P<indent> +)uses: actions/setup-python@[0-9a-f]{40} # v[0-9]+\.[0-9]+\.[0-9]+\Z"
)


def _authenticated_blob_bytes(blob: object) -> bytes:
    """Require complete GitHub contents bytes and verify their Git blob identity."""
    if (not isinstance(blob, dict) or blob.get("type") != "file"
            or not isinstance(blob.get("sha"), str)
            or not SHA.fullmatch(blob["sha"])
            or blob.get("encoding") != "base64"
            or not isinstance(blob.get("content"), str)):
        raise ValueError("authenticated Git blob bytes unavailable")
    try:
        encoded = blob["content"].replace("\n", "").replace("\r", "")
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid Git blob encoding") from exc
    git_blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
    if hashlib.sha1(git_blob, usedforsecurity=False).hexdigest() != blob["sha"]:
        raise ValueError("Git blob SHA does not match content")
    return data


def _unique_json_fields(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate trusted migration policy key")
        result[key] = value
    return result


def parse_pin_migrations(source: bytes) -> list[dict[str, str]]:
    """Reject policy extensions, ambiguous paths and non-immutable action pins."""
    policy = json.loads(source, object_pairs_hook=_unique_json_fields)
    if (not isinstance(policy, dict)
            or set(policy) != {"schema_version", "migrations"}
            or type(policy["schema_version"]) is not int
            or policy["schema_version"] != 1
            or not isinstance(policy["migrations"], list)
            or not policy["migrations"]):
        raise ValueError("invalid trusted migration policy schema")
    paths: set[str] = set()
    for item in policy["migrations"]:
        if (not isinstance(item, dict)
                or set(item) != {"workflow_path", "before_line", "after_line"}
                or type(item["workflow_path"]) is not str
                or item["workflow_path"] not in EXPECTED_WORKFLOWS.values()
                or item["workflow_path"] in paths):
            raise ValueError("invalid or duplicate trusted workflow migration")
        before, after = item["before_line"], item["after_line"]
        if type(before) is not str or type(after) is not str:
            raise ValueError("invalid migration line type")
        old_match, new_match = PIN_LINE.fullmatch(before), PIN_LINE.fullmatch(after)
        if (old_match is None or new_match is None or before == after
                or old_match.group("indent") != new_match.group("indent")):
            raise ValueError("migration must change only an immutable setup-python pin")
        paths.add(item["workflow_path"])
    return policy["migrations"]


def _approved_pin_only_migration(
        repo: str, workflow: str, base_sha: str, token: str,
        base_source: object, head_source: object) -> bool:
    """The trusted baseline, never the candidate, authorizes an exact one-line change."""
    old_bytes = _authenticated_blob_bytes(base_source)
    new_bytes = _authenticated_blob_bytes(head_source)
    if PIN_MIGRATION_FILE.is_symlink():
        raise ValueError("trusted migration policy cannot be a symlink")
    local_policy = PIN_MIGRATION_FILE.read_bytes()
    remote_policy = github(
        f"/repos/{repo}/contents/{PIN_MIGRATION_PATH}?ref={base_sha}", token)
    if _authenticated_blob_bytes(remote_policy) != local_policy:
        raise ValueError("trusted migration policy differs from authenticated base")
    entries = parse_pin_migrations(local_policy)
    for entry in entries:
        if entry["workflow_path"] != workflow:
            continue
        old_line = (entry["before_line"] + "\n").encode("utf-8")
        new_line = (entry["after_line"] + "\n").encode("utf-8")
        lines = old_bytes.splitlines(keepends=True)
        if lines.count(old_line) != 1:
            return False
        expected = b"".join(new_line if line == old_line else line for line in lines)
        return expected == new_bytes
    return False


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
        try:
            allowed = _approved_pin_only_migration(
                repo, workflow, base_sha, token, source[0], source[1])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ValueError(
                f"required workflow differs from trusted base: {workflow} ({exc})"
            ) from exc
        if not allowed:
            raise ValueError(f"required workflow differs from trusted base: {workflow}")


def official_job_matches(
        repo: str, number: int, name: str, check: dict, run: dict, job: dict,
        head: str, base_sha: str, check_id: int, run_id: int, job_id: int) -> bool:
    """Match the authoritative GitHub Actions run, PR base, suite and job."""
    workflow_path = run.get("path")
    if not isinstance(workflow_path, str):
        return False
    api_root = (os.environ.get("GITHUB_API_URL")
                or "https://" + "api." + "github.com").rstrip("/")
    pr_links = run.get("pull_requests")
    return (
        workflow_path.split("@", 1)[0] == EXPECTED_WORKFLOWS[name]
        and run.get("check_suite_id") == check["check_suite"]["id"]
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
    if not official_job_matches(
            repo, number, name, check, run, job, head, base_sha,
            check_id, run_id, job_id):
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
