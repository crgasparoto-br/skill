"""Resolve develop from GitHub using a trusted, preconfigured token.

No caller-controlled URL, branch or HTTP headers. The token belongs to the
privileged control plane, never to an MCP tool argument or an untrusted worker.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from policy import PolicyDeniedError

_REPO = re.compile(r"^(?!\\.{1,2}/)[A-Za-z0-9_.-]+/(?!\\.{1,2}$)[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_API = "https://api.github.com"


class GitHubDevelopResolver:
    def __init__(self, *, token: str, allowed_repositories: frozenset[str], opener=urlopen):
        if not isinstance(token, str) or not token.strip() or "\r" in token or "\n" in token:
            raise ValueError("trusted installation token required")
        if not allowed_repositories or any(not _REPO.fullmatch(r) for r in allowed_repositories):
            raise ValueError("valid repository allowlist required")
        self._token = token
        self._repos = allowed_repositories
        self._opener = opener

    def __call__(self, repository: str) -> str:
        if repository not in self._repos or not _REPO.fullmatch(repository):
            raise PolicyDeniedError("repository not authorized")
        owner, name = repository.split("/")
        url = f"{_API}/repos/{quote(owner, safe='')}/{quote(name, safe='')}/git/ref/heads/develop"
        request = Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "solverit-issue88-controller",
        })
        try:
            with self._opener(request, timeout=10) as response:
                if response.status != 200:
                    raise RuntimeError("GitHub develop lookup failed")
                document = json.loads(response.read(16385))
        except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError("GitHub develop lookup failed") from exc
        if (not isinstance(document, dict)
                or document.get("ref") != "refs/heads/develop"
                or not isinstance(document.get("object"), dict)
                or document["object"].get("type") != "commit"):
            raise RuntimeError("GitHub develop reference invalid")
        sha = document["object"].get("sha")
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise RuntimeError("GitHub develop commit SHA invalid")
        return sha
