"""Offline cryptographic verification of MCP-specific JWT access tokens.

Accepts only RS256 tokens from a preconfigured trusted public key, issuer,
resource audience, and subject allowlist. Tokens from GitHub are not accepted
as MCP credentials. No dynamic jku/jwk/x5u headers or remote key retrieval.
Requires PyJWT[crypto]; do not replace verification with decode-only parsing.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt

class MCPTokenRejectedError(ValueError):
    pass

@dataclass(frozen=True)
class MCPTokenPolicy:
    issuer: str
    audience: str
    public_key_pem: str
    key_id: str
    allowed_subjects: frozenset[str]
    required_scope: str = "solverit:read"

    def __post_init__(self):
        for url in (self.issuer, self.audience):
            parsed = urlsplit(url)
            if (parsed.scheme != "https" or not parsed.netloc
                    or parsed.username or parsed.password or parsed.fragment):
                raise ValueError("issuer/audience must be HTTPS")
        if not self.public_key_pem or not self.key_id or not self.allowed_subjects:
            raise ValueError("pinned public key, key ID and subject allowlist required")


def verify_mcp_access_token(token: str, policy: MCPTokenPolicy) -> str:
    if not isinstance(token, str) or not 10 <= len(token) <= 8192:
        raise MCPTokenRejectedError("Invalid MCP token")
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or header.get("kid") != policy.key_id:
            raise MCPTokenRejectedError("Unexpected signing algorithm or key")
        if any(k in header for k in ("jku", "jwk", "x5u", "x5c", "crit")):
            raise MCPTokenRejectedError("Untrusted key header")
        claims = jwt.decode(
            token, policy.public_key_pem,
            algorithms=["RS256"],
            issuer=policy.issuer,
            audience=policy.audience,
            options={"require": ["iss", "aud", "sub", "iat", "exp", "nbf"]},
            leeway=0,
        )
        subject = claims["sub"]
        if not isinstance(subject, str) or subject not in policy.allowed_subjects:
            raise MCPTokenRejectedError("Subject not authorized")
        scope = claims.get("scope")
        if not isinstance(scope, str) or policy.required_scope not in scope.split():
            raise MCPTokenRejectedError("Insufficient scope")
        return subject
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise MCPTokenRejectedError("MCP token rejected") from exc
