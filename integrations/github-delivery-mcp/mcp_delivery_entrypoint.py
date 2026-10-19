"""Staging-only OAuth resource server for queued Issue 88 delivery jobs.

Neither the public MCP tool parameters nor issue text supply identity, role,
GitHub credentials, base SHA, branch, filesystem paths or executable commands.
This module runs only over streamable HTTP and binds only to loopback. It does
not dispatch workers, execute code, publish branches or finalize deliveries.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from urllib.parse import urlsplit

import jwt
from broker_oauth import DELIVERY_CLIENT, DELIVERY_SCOPE
from delivery_controller_intake import enqueue_verified_delivery
from delivery_job_queries import get_authorized_job_status
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp_jwks_verifier import CachedJWKSVerifier, JWKSVerifierPolicy
from mcp_jwt_verifier import MCPTokenRejectedError
from policy import PolicyDeniedError, VerifiedPrincipal
from pydantic import AnyHttpUrl

CONTROLLER_DB_DIRECTORY = Path("/var/lib/solverit/issue-delivery/controller")
CONTROLLER_DATABASE = CONTROLLER_DB_DIRECTORY / "jobs.sqlite3"


class DeliveryOAuthVerifier:
    """Validate real Keycloak JWT signature, deliver scope, azp and audience."""

    def __init__(self, verifier: CachedJWKSVerifier, resource: str):
        self.verifier = verifier
        self.resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            subject = self.verifier.verify(token)
            # Verification of *this same token* completes before reading claims.
            claims = jwt.decode(token, options={"verify_signature": False})
            if not isinstance(claims, dict):
                return None
            expiry = claims.get("exp")
            scopes = claims.get("scope")
            if (claims.get("azp") != DELIVERY_CLIENT
                    or type(expiry) is not int
                    or not isinstance(scopes, str)
                    or DELIVERY_SCOPE not in scopes.split()):
                return None
            return AccessToken(
                token=token, client_id=DELIVERY_CLIENT,
                subject=subject, scopes=scopes.split(), expires_at=expiry,
                resource=self.resource, claims={"iss": self.verifier.policy.issuer},
            )
        except (MCPTokenRejectedError, ValueError, jwt.PyJWTError):
            return None


def _database_guard() -> str:
    """Never create the privileged controller store from an untrusted request."""
    uid = os.geteuid()
    if uid in (0, 997, 1004):
        raise PermissionError("dedicated controller identity required")
    for path, expected_type, denied_mode in (
        (CONTROLLER_DB_DIRECTORY, stat.S_ISDIR, 0o077),
        (CONTROLLER_DATABASE, stat.S_ISREG, 0o177),
    ):
        info = os.lstat(path)
        if info.st_uid != uid or not expected_type(info.st_mode) or info.st_mode & denied_mode:
            raise PermissionError("untrusted controller store")
    return str(CONTROLLER_DATABASE)


def _current_principal(allowed_subjects: frozenset[str]) -> tuple[VerifiedPrincipal, str]:
    """Return server-verifier identity only, never tool-supplied impersonation."""
    token = get_access_token()
    if (token is None or not isinstance(token.subject, str)
            or token.subject not in allowed_subjects
            or token.client_id != DELIVERY_CLIENT
            or not isinstance(token.scopes, list)
            or DELIVERY_SCOPE not in token.scopes
            or not isinstance(token.token, str)):
        raise PolicyDeniedError("delivery OAuth access denied")
    return VerifiedPrincipal(token.subject, frozenset({"entregar-issue"}), True), token.token


def prepare_authenticated_workspace(
    *, repository: str, issue_number: int, idempotency_key: str,
    allowed_subjects: frozenset[str],
) -> dict[str, object]:
    """Enqueue an authorized intent. NOT a workspace execution or PR."""
    principal, token = _current_principal(allowed_subjects)
    db = _database_guard()
    return enqueue_verified_delivery(
        database_path=db, principal=principal, allowed_subjects=allowed_subjects,
        repository=repository, issue_number=issue_number,
        idempotency_key=idempotency_key, mcp_access_token=token,
    )


def read_authenticated_status(
    *, job_id: str, allowed_subjects: frozenset[str],
) -> dict[str, object]:
    """Read only caller-owned job metadata; no GitHub token is requested."""
    principal, _token = _current_principal(allowed_subjects)
    db = _database_guard()
    return get_authorized_job_status(
        database_path=db, job_id=job_id, principal=principal,
        allowed_subjects=allowed_subjects,
        allowed_repositories=frozenset({"crgasparoto-br/training-system"}),
    )


def build_delivery_server(*, env=None) -> FastMCP:
    env = os.environ if env is None else env
    resource = env.get("SOLVERIT_MCP_RESOURCE_URL", "")
    issuer = env.get("SOLVERIT_OAUTH_ISSUER_URL", "")
    jwks = env.get("SOLVERIT_OAUTH_JWKS_URI", "")
    entries = env.get("SOLVERIT_MCP_DELIVERY_SUBJECTS", "")
    allowed_subjects = frozenset(x.strip() for x in entries.split(",") if x.strip())
    if (not all((resource, issuer, jwks, allowed_subjects))
            or env.get("SOLVERIT_CONTROLLER_DATABASE_PATH") != str(CONTROLLER_DATABASE)
            or urlsplit(resource).path != "/mcp"):
        raise RuntimeError("delivery resource configuration unavailable")
    _database_guard()
    policy = JWKSVerifierPolicy(
        issuer=issuer, audience=resource, jwks_uri=jwks,
        allowed_subjects=allowed_subjects, required_scope=DELIVERY_SCOPE,
        authorized_party=DELIVERY_CLIENT,
    )
    verifier = CachedJWKSVerifier(policy)
    verifier.refresh()
    server = FastMCP(
        "SolverIT Issue Delivery - Authorized Staging",
        host="127.0.0.1", port=8771,
        streamable_http_path="/mcp", stateless_http=True, json_response=True,
        token_verifier=DeliveryOAuthVerifier(verifier, resource),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(issuer),
            resource_server_url=AnyHttpUrl(resource),
            required_scopes=[DELIVERY_SCOPE],
            validate_token_resource=True,
        ),
    )

    def prepare_workspace(repository: str, issue_number: int, idempotency_key: str) -> dict[str, object]:
        """Validate the open issue and queue one isolated-workspace delivery."""
        return prepare_authenticated_workspace(
            repository=repository, issue_number=issue_number,
            idempotency_key=idempotency_key, allowed_subjects=allowed_subjects,
        )

    def get_job_status(job_id: str) -> dict[str, object]:
        """Read own queued/prepared job metadata, without executing a job."""
        return read_authenticated_status(job_id=job_id, allowed_subjects=allowed_subjects)

    server.add_tool(prepare_workspace, name="prepare_workspace",
                    description="Authorize an issue and enqueue a workspace (no code execution).")
    server.add_tool(get_job_status, name="get_job_status",
                    description="Read only your own queued/prepared delivery status.")
    return server


if __name__ == "__main__":
    # Only the HTTP transport carries authenticated bearer tokens.
    build_delivery_server().run(transport="streamable-http")
