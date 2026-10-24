"""Pure validation of independently fetched GitHub PR and check-run records.

Only a privileged, read-only GitHub adapter may supply these dictionaries.
Neither the worker nor an MCP request may call this as proof of delivery.
Successful validation is necessary but NOT sufficient: the independent audit
and atomic finalization remain absent.
"""
from __future__ import annotations

import re

_SHA = re.compile(r"^[0-9a-f]{40}$")


class GitHubEvidenceRejectedError(PermissionError):
    pass


def require_github_evidence(*, job, pull_request: dict,
                            check_runs: list[dict],
                            required_checks: frozenset[str]) -> str:
    """Return verified PR head only after exact identity and check matching."""
    if not isinstance(pull_request, dict) or not isinstance(check_runs, list):
        raise GitHubEvidenceRejectedError("untrusted or missing GitHub evidence")
    head = pull_request.get("head_sha")
    if (not isinstance(head, str) or not _SHA.fullmatch(head)
            or pull_request.get("repository") != job.repo
            or pull_request.get("head_branch") != job.branch
            or pull_request.get("base_branch") != "develop"
            or pull_request.get("state") != "open"
            or pull_request.get("merged") is not False
            or head != job.expected_head
            or job.base_sha == head
            or pull_request.get("issue_number") != job.issue_number):
        raise GitHubEvidenceRejectedError("PR identity or exact HEAD mismatch")
    if (not isinstance(required_checks, frozenset) or not required_checks
            or any(not isinstance(name, str) or not name for name in required_checks)):
        raise GitHubEvidenceRejectedError("required check policy missing")
    seen = set()
    for run in check_runs:
        if not isinstance(run, dict):
            raise GitHubEvidenceRejectedError("invalid check record")
        name = run.get("name")
        if name not in required_checks:
            continue
        if name in seen:
            raise GitHubEvidenceRejectedError("ambiguous duplicate check name")
        seen.add(name)
        if (run.get("head_sha") != head or run.get("status") != "completed"
                or run.get("conclusion") != "success"
                or run.get("source") != "github-check-runs"):
            raise GitHubEvidenceRejectedError("required check not successful on exact HEAD")
    if seen != required_checks:
        raise GitHubEvidenceRejectedError("missing required check")
    return head
