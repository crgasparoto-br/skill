"""Read-only GitHub evidence retrieval for a separate trusted verifier process.

Requires a short-lived fine-scoped read-only installation token from an
independent broker. NEVER run in an untrusted executor or expose to MCP users.
The caller must choose PR number from trusted state, not worker-supplied text.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from github_evidence_validation import GitHubEvidenceRejected, require_github_evidence

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[a-f0-9]{40}$")


def _get_json(*, token: str, repo: str, suffix: str) -> dict:
    if not token or not _REPO.fullmatch(repo):
        raise GitHubEvidenceRejected("missing credential or invalid repository")
    url = "https://api.github.com/repos/" + repo + suffix
    request = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "solverit-delivery-evidence/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = response.read(1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubEvidenceRejected("GitHub evidence retrieval failed") from exc
    if len(payload) > 1024 * 1024:
        raise GitHubEvidenceRejected("GitHub response too large")
    try:
        result = json.loads(payload)
    except (UnicodeError, ValueError) as exc:
        raise GitHubEvidenceRejected("invalid GitHub response") from exc
    if not isinstance(result, dict):
        raise GitHubEvidenceRejected("invalid GitHub response type")
    return result


def fetch_and_validate_github(*, job, pr_number: int, token: str,
                              required_checks: frozenset[str]) -> str:
    if type(pr_number) is not int or pr_number <= 0:
        raise GitHubEvidenceRejected("invalid PR number")
    if not _SHA.fullmatch(job.expected_head):
        raise GitHubEvidenceRejected("expected HEAD must be immutable SHA")
    pr = _get_json(token=token, repo=job.repo, suffix="/pulls/" + str(pr_number))
    if pr.get("number") != pr_number:
        raise GitHubEvidenceRejected("PR number mismatch")
    branch = pr.get("head") or {}
    base = pr.get("base") or {}
    head_repo = branch.get("repo") or {}
    base_repo = base.get("repo") or {}
    # Cross-repo PRs are not supported at this trust boundary.
    if head_repo.get("full_name") != job.repo or base_repo.get("full_name") != job.repo:
        raise GitHubEvidenceRejected("unexpected PR repository")
    # Issue linkage must be retrieved independently from trusted GitHub state.
    # A title/body containing '#88' is not an authoritative issue relation.
    issue_number = None
    checks = _get_json(token=token, repo=job.repo,
                       suffix="/commits/" + job.expected_head + "/check-runs?per_page=100")
    if (checks.get("total_count") is None or
            type(checks["total_count"]) is not int or
            checks["total_count"] > 100):
        raise GitHubEvidenceRejected("check runs pagination incomplete")
    runs = []
    for item in checks.get("check_runs", []):
        if not isinstance(item, dict):
            raise GitHubEvidenceRejected("invalid check run")
        runs.append({"name": item.get("name"), "head_sha": item.get("head_sha"),
                     "status": item.get("status"), "conclusion": item.get("conclusion"),
                     "source": "github-check-runs"})
    return require_github_evidence(
        job=job,
        pull_request={"repository": base_repo.get("full_name"),
                      "head_branch": branch.get("ref"), "base_branch": base.get("ref"),
                      "state": pr.get("state"), "merged": pr.get("merged"),
                      "head_sha": branch.get("sha"), "issue_number": issue_number},
        check_runs=runs, required_checks=required_checks,
    )
