"""Offline key rotation and JWT rejection checks for trusted JWKS verifier."""
import datetime
import json
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp_jwks_verifier import CachedJWKSVerifier, JWKSVerifierPolicy
from mcp_jwt_verifier import MCPTokenRejectedError


class JWKSRotationTests(unittest.TestCase):
    def setUp(self):
        self.keys = [rsa.generate_private_key(public_exponent=65537, key_size=2048)
                     for _ in range(2)]
        policy = JWKSVerifierPolicy(
            issuer="https://auth.example.test/realms/solverit-delivery",
            audience="https://mcp.example.test/mcp",
            jwks_uri="https://auth.example.test/realms/solverit-delivery/protocol/openid-connect/certs",
            allowed_subjects=frozenset({"test-sub"}))
        self.verifier = CachedJWKSVerifier(policy, ttl_seconds=30)

    def signed(self, index=0, **changes):
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        claims = {"iss": self.verifier.policy.issuer,
                  "aud": self.verifier.policy.audience,
                  "sub": "test-sub", "iat": now - 1, "nbf": now - 1,
                  "exp": now + 120, "scope": "openid solverit:read"}
        claims.update(changes)
        return jwt.encode(claims, self.keys[index], algorithm="RS256",
                          headers={"kid": "key-" + str(index)})

    def install(self, index):
        self.verifier._keys = {"key-" + str(index): self.keys[index].public_key()}
        self.verifier._expiry = float("inf")

    def test_valid(self):
        self.install(0)
        self.assertEqual(self.verifier.verify(self.signed()), "test-sub")

    def test_scope_and_audience_rejected(self):
        self.install(0)
        for token in (self.signed(scope="openid"), self.signed(aud="https://wrong.test")):
            with self.assertRaises(MCPTokenRejectedError):
                self.verifier.verify(token)

    def test_rotation_rejects_old_and_accepts_new(self):
        self.install(0)
        self.assertEqual(self.verifier.verify(self.signed()), "test-sub")
        self.install(1)
        self.assertEqual(self.verifier.verify(self.signed(1)), "test-sub")
        with self.assertRaises(MCPTokenRejectedError):
            self.verifier.verify(self.signed())

    def test_unknown_kid_does_not_trigger_network(self):
        self.install(0)
        with patch.object(self.verifier, "refresh", side_effect=AssertionError("network")):
            with self.assertRaises(MCPTokenRejectedError):
                self.verifier.verify(self.signed(1))

    def test_expired_cache_refuses_when_refresh_fails(self):
        self.install(0)
        self.verifier._expiry = 0
        with patch.object(self.verifier, "refresh", side_effect=OSError("unavailable")):
            with self.assertRaises(MCPTokenRejectedError):
                self.verifier.verify(self.signed())

    def test_malformed_policy(self):
        with self.assertRaises(ValueError):
            JWKSVerifierPolicy("https://a.test", "https://m.test/mcp",
                               "https://untrusted.test/jwks", frozenset({"a"}))


if __name__ == "__main__":
    unittest.main()
