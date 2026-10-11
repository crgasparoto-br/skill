"""Fail-closed authorization adapter tests (requires requirements-sdk-pilot.txt)."""
import unittest
from unittest.mock import patch

from mcp_sdk_pilot import KeycloakVerifier, build_server, get_delivery_status


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

    async def test_status_is_inert_and_disables_write(self):
        result = get_delivery_status()
        self.assertEqual(result["status"], "authentication_pilot")
        self.assertIs(result["executor_enabled"], False)
        self.assertIs(result["write_operations_enabled"], False)
        self.assertEqual(set(result), {
            "service", "status", "executor_enabled", "write_operations_enabled"
        })

    async def test_exactly_one_read_only_tool_registered(self):
        with patch("mcp_sdk_pilot.CachedJWKSVerifier") as mock_verifier:
            mock_verifier.return_value.refresh.return_value = None
            server = build_server(env={
                "SOLVERIT_MCP_RESOURCE_URL": "https://mcp.example.com/mcp",
                "SOLVERIT_OAUTH_ISSUER_URL": "https://auth.example.com/realms/test",
                "SOLVERIT_OAUTH_JWKS_URI": "https://auth.example.com/realms/test/certs",
                "SOLVERIT_MCP_SUBJECTS": "approved-user",
            })
        tools = await server.list_tools()
        self.assertEqual([tool.name for tool in tools], ["get_delivery_status"])

    async def test_absent_configuration_refused(self):
        with self.assertRaises(RuntimeError):
            build_server(env={})
