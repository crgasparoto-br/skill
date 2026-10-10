"""Verify a user's GitHub OAuth bearer token against GitHub, server-side.

This adapter is not an OAuth authorization-code flow or MCP HTTP endpoint.
Do not accept user_id, oauth_verified, roles or profiles from caller arguments.
The server admin must configure ALLOWED_GITHUB_IDS outside user requests.
Never log, store or return the supplied OAuth bearer token.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from policy import VerifiedPrincipal

GITHUB_USER_ENDPOINT = "https://api.github.com/user"


class IdentityVerificationError(PermissionError):
    pass


def verify_github_user_token(token: str, *, allowed_github_ids: frozenset[int]) -> VerifiedPrincipal:
    if not isinstance(token, str) or not token.startswith("ghu_") and not token.startswith("gho_"):
        # Fine-grained / OAuth bearer formats may evolve; caller must configure
        # accepted OAuth formats as part of provider integration.
        raise IdentityVerificationError("unsupported GitHub OAuth token format")
    if len(token) > 1024 or not allowed_github_ids:
        raise IdentityVerificationError("invalid token or empty allowlist")
    request = urllib.request.Request(
        GITHUB_USER_ENDPOINT,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "solverit-issue88-identity",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            identity = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError) as exc:
        raise IdentityVerificationError("GitHub identity verification failed") from exc
    user_id = identity.get("id")
    if type(user_id) is not int or user_id <= 0:
        raise IdentityVerificationError("GitHub returned invalid user identity")
    if user_id not in allowed_github_ids:
        raise IdentityVerificationError("GitHub user not authorized")
    return VerifiedPrincipal(subject=f"github:{user_id}",
                             profiles=frozenset({"entregar-issue"}),
                             oauth_verified=True)
