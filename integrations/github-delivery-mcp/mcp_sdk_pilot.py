"""Issue 88: read-only OAuth MCP interoperability pilot using the official SDK.

This is a separate candidate from mcp_http_local.py. Only one inert status
inspection tool is registered. Bind to loopback; do not enable write operations.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import jwt
from mcp.server.fastmcp import FastMCP
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from mcp_jwks_verifier import CachedJWKSVerifier, JWKSVerifierPolicy
from mcp_jwt_verifier import MCPTokenRejectedError


class KeycloakVerifier:
    def __init__(self, verifier: CachedJWKSVerifier, resource: str):
        self.verifier = verifier
        self.resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            subject = self.verifier.verify(token)
            # Claims are read only AFTER cryptographic/issuer/audience validation.
            claims = jwt.decode(token, options={"verify_signature": False})
            client_id = claims.get("azp")
            expiry = claims.get("exp")
            scopes = claims.get("scope", "").split()
            if not isinstance(client_id, str) or not client_id:
                return None
            if not isinstance(expiry, int):
                return None
            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=scopes,
                expires_at=expiry,
                resource=self.resource,
                subject=subject,
                claims={"iss": self.verifier.policy.issuer},
            )
        except (MCPTokenRejectedError, ValueError, jwt.PyJWTError):
            return None


def get_delivery_status() -> dict[str, object]:
    """Return public pilot status; never access GitHub, jobs, credentials or host."""
    return {
        "service": "SolverIT Issue Delivery",
        "status": "authentication_pilot",
        "executor_enabled": False,
        "write_operations_enabled": False,
    }


def build_server(*, env=None) -> FastMCP:
    env = os.environ if env is None else env
    resource = env.get("SOLVERIT_MCP_RESOURCE_URL", "")
    issuer = env.get("SOLVERIT_OAUTH_ISSUER_URL", "")
    jwks_uri = env.get("SOLVERIT_OAUTH_JWKS_URI", "")
    subjects = frozenset(s.strip() for s in env.get("SOLVERIT_MCP_SUBJECTS", "").split(",") if s.strip())
    if not all((resource, issuer, jwks_uri, subjects)):
        raise RuntimeError("OAuth issuer, resource, JWKS and allowlist are required")
    if urlsplit(resource).path != "/mcp":
        raise ValueError("public MCP resource must end in /mcp")
    policy = JWKSVerifierPolicy(
        issuer=issuer, audience=resource, jwks_uri=jwks_uri,
        allowed_subjects=subjects, required_scope="solverit:read",
    )
    verifier = CachedJWKSVerifier(policy)
    verifier.refresh()  # startup fails closed if keys unavailable
    server = FastMCP(
        "SolverIT Issue Delivery - Authentication Pilot",
        host="127.0.0.1",
        port=8770,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        token_verifier=KeycloakVerifier(verifier, resource),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=AnyHttpUrl(resource),
            required_scopes=["solverit:read"],
        ),
    )
    server.add_tool(get_delivery_status, name="get_delivery_status", description="Read-only authentication pilot status; no GitHub access.")
    return server


if __name__ == "__main__":
    server = build_server()
    server.run(transport="streamable-http")
