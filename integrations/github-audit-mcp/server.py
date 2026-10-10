"""Read-only GitHub ruleset/branch-protection MCP. Never accepts caller-supplied URLs."""
from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
import jwt
from fastmcp import FastMCP
from fastmcp.server.auth.providers.github import GitHubProvider

API = "https://api.github.com"
APP_ID = os.environ["GITHUB_APP_ID"]
PRIVATE_KEY_PATH = Path(os.environ["GITHUB_APP_PRIVATE_KEY_FILE"])
BASE_URL = os.environ["MCP_BASE_URL"].rstrip("/")
ALLOWED_REPOS = frozenset(
    repo.strip().lower()
    for repo in os.environ["ALLOWED_REPOS"].split(",")
    if repo.strip()
)
if not ALLOWED_REPOS or any("/" not in repo or repo.count("/") != 1 for repo in ALLOWED_REPOS):
    raise RuntimeError("ALLOWED_REPOS must contain owner/repository names")
if not BASE_URL.startswith("https://"):
    raise RuntimeError("MCP_BASE_URL must use HTTPS")

# OAuth authenticates MCP clients independently of the GitHub App installation.
auth = GitHubProvider(
    client_id=os.environ["MCP_OAUTH_CLIENT_ID"],
    client_secret=os.environ["MCP_OAUTH_CLIENT_SECRET"],
    base_url=BASE_URL,
)
mcp = FastMCP("SolverIT GitHub Auditor", auth=auth)


def _allowed(repo: str) -> tuple[str, str]:
    value = repo.strip().lower()
    if value not in ALLOWED_REPOS:
        raise ValueError("Repository not on the server-side allowlist")
    return tuple(value.split("/", 1))


def _jwt() -> str:
    key = PRIVATE_KEY_PATH.read_text(encoding="utf-8")
    return jwt.encode(
        {"iat": int(time.time()) - 60, "exp": int(time.time()) + 540, "iss": APP_ID},
        key,
        algorithm="RS256",
    )


def _request(path: str, token: str) -> Any:
    # All routes are constructed internally from allowlisted repository names.
    with httpx.Client(base_url=API, timeout=15.0, follow_redirects=False) as client:
        response = client.get(
            path,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        return response.json()


@lru_cache(maxsize=32)
def _repository_installation(repo: str) -> int:
    owner, name = _allowed(repo)
    result = _request(f"/repos/{owner}/{name}/installation", _jwt())
    return int(result["id"])


def _installation_token(repo: str) -> str:
    installation_id = _repository_installation(repo)
    with httpx.Client(base_url=API, timeout=15.0, follow_redirects=False) as client:
        response = client.post(
            f"/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"repositories": [repo.split("/", 1)[1]], "permissions": {"metadata": "read", "administration": "read"}},
        )
        response.raise_for_status()
        return response.json()["token"]


def _get(repo: str, suffix: str) -> Any:
    owner, name = _allowed(repo)
    return _request(f"/repos/{owner}/{name}/{suffix}", _installation_token(repo))


@mcp.tool()
def list_rulesets(repository: str) -> dict[str, Any]:
    """List repository and inherited rulesets; no writes."""
    data = _get(repository, "rulesets?includes_parents=true&per_page=100")
    return {"repository": repository, "rulesets": data, "pagination_complete": len(data) < 100}


@mcp.tool()
def get_branch_rules(repository: str, branch: str) -> dict[str, Any]:
    """Read effective active rules for an allowlisted branch; no writes."""
    if branch not in ("develop", "main"):
        raise ValueError("Only main and develop are accepted")
    data = _get(repository, f"rules/branches/{branch}")
    return {"repository": repository, "branch": branch, "rules": data}


@mcp.tool()
def get_branch_protection(repository: str, branch: str) -> dict[str, Any]:
    """Read classic protection. A 404 is not evidence that rulesets are absent."""
    if branch not in ("develop", "main"):
        raise ValueError("Only main and develop are accepted")
    try:
        data = _get(repository, f"branches/{branch}/protection")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {"repository": repository, "branch": branch, "classic_protection": "NOT_OBSERVED", "note": "Rulesets must be checked separately"}
        raise
    return {"repository": repository, "branch": branch, "classic_protection": data}


@mcp.tool()
def get_ruleset_details(repository: str, ruleset_id: int) -> dict[str, Any]:
    """Inspect checks, enforcement and bypass visibility without inferring missing actors."""
    if ruleset_id <= 0:
        raise ValueError("Invalid ruleset ID")
    data = _get(repository, f"rulesets/{ruleset_id}?includes_parents=true")
    return {
        "repository": repository,
        "ruleset": data,
        "bypass_actors_visibility": "OBSERVED" if "bypass_actors" in data else "UNKNOWN_NO_WRITE_ACCESS",
        "note": "GitHub can omit bypass_actors without write access; omission never proves no bypass.",
    }


if __name__ == "__main__":
    mcp.run(transport="http", host=os.getenv("BIND_HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8765")))
