"""Broker-local OAuth verifier: an IPC peer UID is not user authorization.

The GitHub App broker independently verifies the MCP access token before it
reads job metadata or mints installation tokens. The token is never logged,
persisted, sent to GitHub, or included in an IPC response. A separate
Keycloak scope (solverit:deliver) is mandatory; read-only tokens are denied.
"""
from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from mcp_jwks_verifier import CachedJWKSVerifier, JWKSVerifierPolicy
from mcp_jwt_verifier import MCPTokenRejectedError

DELIVERY_SCOPE = "solverit:deliver"
MAX_OAUTH_TOKEN_BYTES = 8192


class BrokerOAuthDenied(PermissionError):
    pass


def build_broker_verifier(env: Mapping[str, str]) -> CachedJWKSVerifier:
    resource = env.get("SOLVERIT_MCP_RESOURCE_URL", "")
    issuer = env.get("SOLVERIT_OAUTH_ISSUER_URL", "")
    jwks = env.get("SOLVERIT_OAUTH_JWKS_URI", "")
    entries = env.get("SOLVERIT_MCP_DELIVERY_SUBJECTS", "")
    subjects = frozenset(x.strip() for x in entries.split(",") if x.strip())
    if not all((resource, issuer, jwks, subjects)):
        raise BrokerOAuthDenied("broker OAuth policy is incomplete")
    if urlsplit(resource).path != "/mcp":
        raise BrokerOAuthDenied("broker MCP resource invalid")
    policy = JWKSVerifierPolicy(
        issuer=issuer, audience=resource, jwks_uri=jwks,
        allowed_subjects=subjects, required_scope=DELIVERY_SCOPE,
    )
    verifier = CachedJWKSVerifier(policy)
    verifier.refresh()  # Fail closed on missing/revoked JWKS at service startup.
    return verifier


def verified_actor(token: str, *, verifier: CachedJWKSVerifier) -> str:
    if (not isinstance(token, str) or not token.isascii()
            or any(char.isspace() for char in token)
            or not 10 <= len(token) <= MAX_OAUTH_TOKEN_BYTES):
        raise BrokerOAuthDenied("invalid broker access token")
    if not isinstance(verifier, CachedJWKSVerifier):
        raise BrokerOAuthDenied("trusted broker verifier unavailable")
    try:
        subject = verifier.verify(token)
    except MCPTokenRejectedError as exc:
        raise BrokerOAuthDenied("broker token rejected") from exc
    if not isinstance(subject, str) or not subject:
        raise BrokerOAuthDenied("verified broker identity missing")
    return subject
