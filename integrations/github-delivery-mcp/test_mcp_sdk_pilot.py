"""Fail-closed authorization adapter tests (requires requirements-sdk-pilot.txt)."""
import unittest
from unittest.mock import patch

from mcp_sdk_pilot import KeycloakVerifier, build_server


class FakePolicy:
    issuer = "https://auth.example.com/realms/test"


class FakeVerifier:
    policy = FakePolicy()

    def verify(self, token):
        if token != "accepted":
            from mcp_jwt_verifier import MCPTokenRejectedError
            raise MCPTokenRejectedError("rejected")
        return "approved-user"


class SDKPilotTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_token_denied(self):
        verifier = KeycloakVerifier(FakeVerifier(), "https://mcp.example.com/mcp")
        self.assertIsNone(await verifier.verify_token("invalid"))

    async def test_verified_subject_requires_azp_and_exp(self):
        verifier = KeycloakVerifier(FakeVerifier(), "https://mcp.example.com/mcp")
        with patch("mcp_sdk_pilot.jwt.decode", return_value={"scope": "solverit:read"}):
            self.assertIsNone(await verifier.verify_token("accepted"))

    async def test_valid_verified_subject_passes(self):
        verifier = KeycloakVerifier(FakeVerifier(), "https://mcp.example.com/mcp")
        with patch("mcp_sdk_pilot.jwt.decode", return_value={
            "azp": "chatgpt", "exp": 2000000000, "scope": "openid solverit:read"
        }):
            token = await verifier.verify_token("accepted")
        self.assertEqual(token.subject, "approved-user")
        self.assertEqual(token.resource, "https://mcp.example.com/mcp")
        self.assertIn("solverit:read", token.scopes)

    async def test_absent_configuration_refused(self):
        with self.assertRaises(RuntimeError):
            build_server(env={})
