"""Fixed-endpoint, read-only GitHub issue lookup for controlled delivery intake.

Issue title and body are *never* returned to the broker or interpreted as
instructions; this confirms only that the selected issue exists and is open.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ISSUE_LIMIT = 2_147_483_647
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubIssueLookupError(RuntimeError):
    """Generic error: never reflect GitHub payload, credentials or issue text."""


def require_open_issue(*, repository: str, issue_number: int,
                       token: str, opener=urlopen) -> None:
    if (not isinstance(repository, str) or not _REPO.fullmatch(repository)
            or type(issue_number) is not int or not 1 <= issue_number <= ISSUE_LIMIT
            or not isinstance(token, str) or not token or "\n" in token or "\r" in token):
        raise GitHubIssueLookupError("invalid issue inspection")
    owner, name = repository.split("/")
    repository_url = f"https://api.github.com/repos/{quote(owner, safe='')}/{quote(name, safe='')}"
    request = Request(
        f"{repository_url}/issues/{issue_number}",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "solverit-issue88-authenticator",
        },
        method="GET",
    )
    try:
        with opener(request, timeout=10) as response:
            if response.status != 200:
                raise GitHubIssueLookupError("issue lookup rejected")
            raw = response.read(32769)
            if len(raw) > 32768:
                raise GitHubIssueLookupError("issue metadata exceeds limit")
            issue = json.loads(raw)
    except (OSError, HTTPError, URLError, TimeoutError, ValueError, TypeError) as exc:
        raise GitHubIssueLookupError("issue lookup unavailable") from exc
    if (not isinstance(issue, dict)
            or type(issue.get("number")) is not int or issue["number"] != issue_number
            or issue.get("repository_url") != repository_url
            or issue.get("state") != "open"
            or "pull_request" in issue):
        raise GitHubIssueLookupError("issue is not eligible for delivery")
