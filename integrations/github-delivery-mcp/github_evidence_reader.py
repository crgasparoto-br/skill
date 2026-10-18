"""Read-only GitHub evidence retrieval for a separate trusted verifier process.

Requires a short-lived fine-scoped read-only installation token from an
independent broker. NEVER run in an untrusted executor or expose to MCP users.
The caller must choose PR number from trusted state, not worker-supplied text.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from github_evidence_validation import GitHubEvidenceRejectedError, require_github_evidence

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[a-f0-9]{40}$")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise GitHubEvidenceRejectedError("GitHub redirect refused")


def _get_json(*, token: str, repo: str, suffix: str) -> dict:
    if not token or not _REPO.fullmatch(repo):
        raise GitHubEvidenceRejectedError("missing credential or invalid repository")
    url = "https://api.github.com/repos/" + repo + suffix
    request = urllib.request.Request(
        url, method="GET",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "solverit-delivery-evidence/1"},
    )
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=15) as response:
            payload = response.read(1024 * 1024 + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitHubEvidenceRejectedError("GitHub evidence retrieval failed") from exc
    if len(payload) > 1024 * 1024:
        raise GitHubEvidenceRejectedError("GitHub response too large")
    try:
        result = json.loads(payload)
    except (UnicodeError, ValueError) as exc:
        raise GitHubEvidenceRejectedError("invalid GitHub response") from exc
    if not isinstance(result, dict):
        raise GitHubEvidenceRejectedError("invalid GitHub response type")
    return result


def fetch_and_validate_github(*, job, pr_number: int, token: str,
                              required_checks: frozenset[str], binding=None) -> str:
    if type(pr_number) is not int or pr_number <= 0:
        raise GitHubEvidenceRejectedError("invalid PR number")
    if binding is None or (binding.job_id != job.job_id
                           or binding.pr_number != pr_number
                           or binding.head_sha != job.expected_head):
        raise GitHubEvidenceRejectedError("trusted job-to-PR binding missing or mismatched")
    if not _SHA.fullmatch(job.expected_head):
        raise GitHubEvidenceRejectedError("expected HEAD must be immutable SHA")
    pr = _get_json(token=token, repo=job.repo, suffix="/pulls/" + str(pr_number))
    if pr.get("number") != pr_number:
        raise GitHubEvidenceRejectedError("PR number mismatch")
    branch = pr.get("head") or {}
    base = pr.get("base") or {}
    head_repo = branch.get("repo") or {}
    base_repo = base.get("repo") or {}
    # Cross-repo PRs are not supported at this trust boundary.
    if head_repo.get("full_name") != job.repo or base_repo.get("full_name") != job.repo:
        raise GitHubEvidenceRejectedError("unexpected PR repository")
    # Protected broker-owned binding correlates the job and issue to this PR.
    # A PR title/body alone never establishes the association.
    issue_number = job.issue_number
    checks = _get_json(token=token, repo=job.repo,
                       suffix="/commits/" + job.expected_head + "/check-runs?per_page=100")
    if (checks.get("total_count") is None or
            type(checks["total_count"]) is not int or
            checks["total_count"] > 100 or
            not isinstance(checks.get("check_runs"), list) or
            len(checks["check_runs"]) != checks["total_count"]):
        raise GitHubEvidenceRejectedError("check runs pagination incomplete")
    runs = []
    for item in checks.get("check_runs", []):
        if not isinstance(item, dict):
            raise GitHubEvidenceRejectedError("invalid check run")
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
