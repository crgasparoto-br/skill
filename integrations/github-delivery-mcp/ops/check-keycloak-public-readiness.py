#!/usr/bin/env python3
"""Read-only Keycloak/OIDC public readiness check for Issue #88.

Never authenticates as a user, reads tokens or keys from disk, or modifies
Keycloak. Public OIDC metadata cannot prove that a delivery scope is
configured for, or granted to, a particular authenticated subject.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ISSUER = "https://auth.solveritconsultoria.com.br/realms/solverit-delivery"
RESOURCE = "https://mcp.solveritconsultoria.com.br/mcp"
SCOPE = "solverit:deliver"
LIMIT = 65536


class ReadinessError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ReadinessError("unexpected HTTP redirect")


def fetch_json(url: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise ReadinessError("non-HTTPS or ambiguous endpoint")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect()
    )
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "solverit-issue88-public-readiness/1",
    })
    try:
        with opener.open(request, timeout=8) as response:
            if response.status != 200 or response.headers.get_content_type() != "application/json":
                raise ReadinessError("unexpected OIDC response")
            raw = response.read(LIMIT + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ReadinessError("OIDC endpoint unavailable") from exc
    if len(raw) > LIMIT:
        raise ReadinessError("OIDC response oversized")
    try:
        payload = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ReadinessError("malformed OIDC response") from exc
    if not isinstance(payload, dict):
        raise ReadinessError("invalid OIDC response shape")
    return payload


def validate_document(discovery: dict, jwks: dict) -> dict[str, str | int]:
    if discovery.get("issuer") != ISSUER:
        raise ReadinessError("unexpected OIDC issuer")
    uri = discovery.get("jwks_uri")
    if (not isinstance(uri, str)
            or not uri.startswith(ISSUER + "/protocol/openid-connect/")
            or urlsplit(uri).scheme != "https"):
        raise ReadinessError("untrusted JWKS URI")
    for field in ("authorization_endpoint", "token_endpoint"):
        value = discovery.get(field)
        if (not isinstance(value, str)
                or not value.startswith(ISSUER + "/protocol/openid-connect/")
                or urlsplit(value).scheme != "https"):
            raise ReadinessError("untrusted " + field)
    methods = discovery.get("code_challenge_methods_supported")
    if not isinstance(methods, list) or "S256" not in methods:
        raise ReadinessError("PKCE S256 not advertised")
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise ReadinessError("JWKS keys unavailable")
    signing = []
    for key in keys:
        if (isinstance(key, dict) and key.get("kty") == "RSA"
                and key.get("use", "sig") == "sig"
                and key.get("alg", "RS256") == "RS256"
                and isinstance(key.get("n"), str)
                and isinstance(key.get("e"), str)
                and isinstance(key.get("kid"), str)):
            signing.append(key["kid"])
    if not signing or len(signing) != len(set(signing)):
        raise ReadinessError("no unique RS256 verification keys")
    scopes = discovery.get("scopes_supported")
    advertised = ("yes" if SCOPE in scopes else "no") if isinstance(scopes, list) else "unspecified"
    return {
        "issuer": ISSUER,
        "resource": RESOURCE,
        "pkce_s256": "supported",
        "rs256_public_key_count": len(signing),
        "deliver_scope_advertised": advertised,
    }


def inspect_public_endpoints() -> dict[str, str | int]:
    discovery = fetch_json(ISSUER + "/.well-known/openid-configuration")
    jwks_uri = discovery.get("jwks_uri")
    if (not isinstance(jwks_uri, str)
            or not jwks_uri.startswith(ISSUER + "/protocol/openid-connect/")):
        raise ReadinessError("JWKS URI not issuer-relative")
    jwks = fetch_json(jwks_uri)
    return validate_document(discovery, jwks)


def main() -> int:
    print("=== ISSUE 88: KEYCLOAK PUBLIC OIDC READINESS (READ ONLY) ===")
    try:
        evidence = inspect_public_endpoints()
    except ReadinessError as exc:
        print("RESULT: FAIL - " + str(exc))
        return 1
    for key, value in evidence.items():
        print(f"{key}: {value}")
    print("RESULT: PASS - public OIDC/JWKS transport")
    print("PENDING: Keycloak admin proof of optional delivery client scope,")
    print("         per-user authorization and exact approved OIDC subject")
    print("PENDING: root-managed broker.env; broker must stay stopped")
    print("WARNING: scopes_supported does not prove scope assignment or token claims")
    return 0


if __name__ == "__main__":
    sys.exit(main())
