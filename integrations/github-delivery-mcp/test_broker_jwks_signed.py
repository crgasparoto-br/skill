"""Issue #88: independently signed RS256 JWT attack matrix (offline only).

Generates a throwaway 2048-bit RSA key in memory. Never authenticates
with Keycloak, writes keys to disk, or prints signed tokens. This tests
the real broker OAuth/JWKS verifier's cryptographic policy without
claiming that a live Keycloak access token has been accepted.
"""
from __future__ import annotations

import time
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from broker_oauth import BrokerOAuthDenied, verified_actor
from mcp_jwks_verifier import CachedJWKSVerifier, JWKSVerifierPolicy
from mcp_jwt_verifier import MCPTokenRejectedError

ISSUER = "https://auth.solveritconsultoria.com.br/realms/solverit-delivery"
AUDIENCE = "https://mcp.solveritconsultoria.com.br/mcp"
ALLOWED_SUBJECT = "3a067184-4b62-4d37-99a4-55c1e7f916fd"
UNAUTHORIZED_SUBJECT = "e5afb0af-d8fb-4b43-8efc-5e31d4a30f22"
KID = "ephemeral-test-only-kid"


class RealRS256BrokerVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        policy = JWKSVerifierPolicy(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_uri=ISSUER + "/protocol/openid-connect/certs",
            allowed_subjects=frozenset({ALLOWED_SUBJECT}),
            required_scope="solverit:deliver",
            authorized_party="solverit-chatgpt-mcp",
        )
        self.verifier = CachedJWKSVerifier(policy, ttl_seconds=300)
        # Inject a genuine RSA public key derived from an in-memory test
        # private key; NO network calls, NO production trust anchor.
        self.verifier._keys = {KID: self.key.public_key()}
        self.verifier._expiry = time.monotonic() + 300

    def claims(self, **changes):
        now = int(time.time())
        result = {
            "iss": ISSUER, "aud": AUDIENCE, "sub": ALLOWED_SUBJECT,
            "azp": "solverit-chatgpt-mcp",
            "scope": "openid solverit:deliver", "iat": now - 10,
            "nbf": now - 10, "exp": now + 300,
        }
        result.update(changes)
        return result

    def signed(self, claims=None, *, key=None, headers=None, algorithm="RS256"):
        return jwt.encode(
            self.claims() if claims is None else claims,
            self.key if key is None else key, algorithm=algorithm,
            headers={"kid": KID, **(headers or {})},
        )

    def rejected(self, token):
        with self.assertRaises(BrokerOAuthDenied):
            verified_actor(token, verifier=self.verifier)

    def test_authorized_rs256_access_token_accepted(self):
        self.assertEqual(verified_actor(self.signed(), verifier=self.verifier),
                         ALLOWED_SUBJECT)

    def test_wrong_or_missing_oauth_client_denied(self):
        for azp in (None, "unknown-client", "solverit-github-auditor"):
            with self.subTest(azp=azp):
                claims = self.claims()
                if azp is None:
                    del claims["azp"]
                else:
                    claims["azp"] = azp
                self.rejected(self.signed(claims))

    def test_read_only_scope_denied(self):
        self.rejected(self.signed(self.claims(scope="openid solverit:read")))

    def test_scope_substrings_not_accepted(self):
        for scope in ("openid solverit:delivery", "solverit:deliver-other",
                      "xsolverit:deliver", "", "openid"):
            with self.subTest(scope=scope):
                self.rejected(self.signed(self.claims(scope=scope)))

    def test_unapproved_subject_denied_even_with_delivery_scope(self):
        self.rejected(self.signed(self.claims(sub=UNAUTHORIZED_SUBJECT)))

    def test_wrong_resource_audience_denied(self):
        for aud in ("https://untrusted.invalid/mcp", "solverit-chatgpt-mcp", []):
            with self.subTest(aud=aud):
                self.rejected(self.signed(self.claims(aud=aud)))

    def test_wrong_issuer_denied(self):
        self.rejected(self.signed(self.claims(iss="https://attacker.invalid/realms/test")))

    def test_expired_and_future_tokens_denied(self):
        now = int(time.time())
        self.rejected(self.signed(self.claims(exp=now - 30)))
        self.rejected(self.signed(self.claims(nbf=now + 300)))
        self.rejected(self.signed(self.claims(iat=now + 300)))

    def test_missing_required_claims_denied(self):
        for missing in ("iss", "aud", "sub", "iat", "nbf", "exp"):
            with self.subTest(missing=missing):
                claims = self.claims()
                claims.pop(missing)
                self.rejected(self.signed(claims))

    def test_signature_tampering_rejected(self):
        token = self.signed()
        parts = token.split(".")
        # Flip bytes in signed payload while keeping the original signature.
        altered = parts[1][:-3] + ("A" if parts[1][-3] != "A" else "B") + parts[1][-2:]
        self.rejected(".".join((parts[0], altered, parts[2])))

    def test_untrusted_signing_key_denied(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.rejected(self.signed(key=other))

    def test_unknown_kid_denied(self):
        self.rejected(self.signed(headers={"kid": "untrusted-kid"}))

    def test_forbidden_jku_jwk_or_crit_headers_denied(self):
        for header in (
            {"jku": "https://attacker.invalid/jwks.json"},
            {"jwk": {"kty": "RSA"}},
            {"crit": ["exp"]},
            {"x5u": "https://attacker.invalid/key.pem"},
        ):
            with self.subTest(header=header):
                self.rejected(self.signed(headers=header))

    def test_wrong_alg_denied(self):
        self.rejected(self.signed(
            claims=self.claims(), key="test-hmac-secret",
            algorithm="HS256"))

    def test_failed_key_refresh_never_silently_accepts_old_key(self):
        self.verifier._expiry = time.monotonic() - 1
        with patch.object(self.verifier, "refresh",
                          side_effect=OSError("fake JWKS outage")):
            self.rejected(self.signed())
        self.assertEqual(self.verifier._keys, {})

    def test_empty_and_malformed_bearers_denied(self):
        for value in (None, "", "x.y.z", "Bearer token", "a" * 9000):
            with self.subTest(value=repr(value)[:30]):
                self.rejected(value)


if __name__ == "__main__":
    unittest.main()
