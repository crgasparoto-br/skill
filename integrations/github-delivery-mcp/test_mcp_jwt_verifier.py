"""Offline RSA signature and claim rejection tests for MCP tokens."""
import datetime
import unittest

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from mcp_jwt_verifier import MCPTokenPolicy, MCPTokenRejectedError, verify_mcp_access_token

class JWTVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_key = key
        pem = key.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        cls.policy = MCPTokenPolicy(
            issuer="https://identity.example.test",
            audience="https://delivery.example.test/mcp",
            public_key_pem=pem, key_id="test-key", allowed_subjects=frozenset({"user-123"}))

    def signed(self, **overrides):
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        claims = {"iss": self.policy.issuer, "aud": self.policy.audience,
                  "sub": "user-123", "iat": now - 10, "nbf": now - 10,
                  "exp": now + 120, "scope": "solverit:read"}
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="RS256",
                          headers={"kid": "test-key"})

    def test_valid_token(self):
        self.assertEqual(verify_mcp_access_token(self.signed(), self.policy), "user-123")

    def test_wrong_issuer(self):
        with self.assertRaises(MCPTokenRejectedError):
            verify_mcp_access_token(self.signed(iss="https://other.example.test"), self.policy)

    def test_wrong_audience(self):
        with self.assertRaises(MCPTokenRejectedError):
            verify_mcp_access_token(self.signed(aud="https://api.github.com"), self.policy)

    def test_expired(self):
        with self.assertRaises(MCPTokenRejectedError):
            verify_mcp_access_token(self.signed(exp=1), self.policy)

    def test_missing_scope(self):
        with self.assertRaises(MCPTokenRejectedError):
            verify_mcp_access_token(self.signed(scope="unrelated"), self.policy)

    def test_unknown_subject(self):
        with self.assertRaises(MCPTokenRejectedError):
            verify_mcp_access_token(self.signed(sub="unknown"), self.policy)

    def test_tampered_signature(self):
        parts = self.signed().split(".")
        parts[-1] = ("A" if parts[-1][0] != "A" else "B") + parts[-1][1:]
        with self.assertRaises(MCPTokenRejectedError):
            verify_mcp_access_token(".".join(parts), self.policy)

    def test_plain_github_token_denied(self):
        with self.assertRaises(MCPTokenRejectedError):
            verify_mcp_access_token("ghu_invalid_example", self.policy)

    def test_missing_exp(self):
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        token = jwt.encode({"iss": self.policy.issuer, "aud": self.policy.audience,
            "sub": "user-123", "iat": now, "nbf": now, "scope": "solverit:read"},
            self.private_key, algorithm="RS256", headers={"kid": "test-key"})
        with self.assertRaises(MCPTokenRejectedError):
            verify_mcp_access_token(token, self.policy)

if __name__ == "__main__":
    unittest.main()
