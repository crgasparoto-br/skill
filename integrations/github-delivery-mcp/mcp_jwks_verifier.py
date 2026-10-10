"""JWT access-token verifier using a trusted, bounded OIDC JWKS cache.

The cache is fetched only from a preconfigured HTTPS endpoint. Untrusted token
headers never select URLs. Unknown key IDs fail closed, including during outage.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.request import Request

import jwt

from mcp_jwt_verifier import MCPTokenRejectedError


@dataclass(frozen=True)
class JWKSVerifierPolicy:
    issuer: str
    audience: str
    jwks_uri: str
    allowed_subjects: frozenset[str]
    required_scope: str = "solverit:read"

    def __post_init__(self):
        for url in (self.issuer, self.audience, self.jwks_uri):
            p = urlsplit(url)
            if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment:
                raise ValueError("trusted URLs must be HTTPS")
        if not self.allowed_subjects:
            raise ValueError("subject allowlist required")
        if not self.jwks_uri.startswith(self.issuer.rstrip("/") + "/"):
            raise ValueError("JWKS must be issuer-relative")


class CachedJWKSVerifier:
    def __init__(self, policy: JWKSVerifierPolicy, *, ttl_seconds: int = 300):
        if not 30 <= ttl_seconds <= 3600:
            raise ValueError("JWKS TTL out of bounds")
        self.policy = policy
        self.ttl_seconds = ttl_seconds
        self._keys: dict[str, object] = {}
        self._expiry = 0.0

    def refresh(self):
        # Disable redirects and any environment proxy to restrict network trust.
        import urllib.request

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )
        request = Request(self.policy.jwks_uri, headers={"Accept": "application/json"})
        with opener.open(request, timeout=5) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise ValueError("invalid JWKS response")
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("JWKS oversized")
        document = json.loads(raw)
        if not isinstance(document, dict) or not isinstance(document.get("keys"), list):
            raise ValueError("JWKS malformed")
        keys = {}
        for item in document["keys"]:
            if not isinstance(item, dict) or item.get("kty") != "RSA" or item.get("use", "sig") != "sig" or item.get("alg", "RS256") != "RS256":
                continue
            kid = item.get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > 256 or kid in keys:
                raise ValueError("invalid or duplicate JWKS key ID")
            if "n" not in item or "e" not in item or any(k in item for k in ("d", "p", "q", "dp", "dq", "qi")):
                raise ValueError("malformed RSA verification key")
            keys[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(item))
        if not keys or len(keys) > 32:
            raise ValueError("JWKS key count invalid")
        self._keys = keys
        self._expiry = time.monotonic() + self.ttl_seconds

    def verify(self, token: str) -> str:
        if not isinstance(token, str) or not 10 <= len(token) <= 8192:
            raise MCPTokenRejectedError("invalid token")
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or len(kid) > 256:
                raise ValueError("disallowed JWT algorithm")
            if any(name in header for name in ("jku", "jwk", "x5u", "x5c", "crit")):
                raise ValueError("untrusted JWT header")
            if time.monotonic() >= self._expiry:
                # A failed refresh invalidates stale keys: availability must never weaken trust.
                self._keys = {}
                self.refresh()
            key = self._keys.get(kid)
            if key is None:
                # Unknown kid is not fetched on demand: avoid attacker-driven JWKS requests.
                raise ValueError("unknown signing key")
            claims = jwt.decode(token, key, algorithms=["RS256"],
                                issuer=self.policy.issuer, audience=self.policy.audience,
                                options={"require": ["iss", "aud", "sub", "iat", "exp", "nbf"]},
                                leeway=0)
            subject = claims["sub"]
            if not isinstance(subject, str) or subject not in self.policy.allowed_subjects:
                raise ValueError("unauthorized subject")
            scope = claims.get("scope")
            if not isinstance(scope, str) or self.policy.required_scope not in scope.split():
                raise ValueError("insufficient scope")
            return subject
        except Exception as exc:
            raise MCPTokenRejectedError("MCP access token rejected") from exc
