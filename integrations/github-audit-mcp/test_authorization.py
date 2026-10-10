"""Regression tests for MCP authorization and repository allowlists.

Run: python -m unittest discover -s integrations/github-audit-mcp -p 'test_*.py'
"""
import asyncio
import os
import unittest

from types import SimpleNamespace
from unittest.mock import patch

ENV = {
    "GITHUB_APP_ID": "5257238",
    "GITHUB_APP_PRIVATE_KEY_FILE": "/dev/null",
    "MCP_BASE_URL": "https://audit-mcp.solveritconsultoria.com.br",
    "ALLOWED_REPOS": "crgasparoto-br/training-system",
    "ALLOWED_GITHUB_USERS": "crgasparoto-br",
    "MCP_OAUTH_CLIENT_ID": "test",
    "MCP_OAUTH_CLIENT_SECRET": "test",
}

with patch.dict(os.environ, ENV):
    import server


class AuthorizationTests(unittest.TestCase):
    def test_tools_hidden_without_authenticated_context(self):
        async def check():
            tools = await server.mcp.list_tools()
            self.assertEqual([tool.name for tool in tools], [])
        asyncio.run(check())

    def test_direct_tool_call_without_context_is_denied(self):
        async def check():
            with patch.object(server, "_get") as github_api:
                try:
                    await server.mcp.call_tool(
                        "list_rulesets",
                        {"repository": "crgasparoto-br/training-system"},
                    )
                except Exception:
                    pass  # Not found / unauthorized are valid fail-closed outcomes.
                else:
                    self.fail("Protected tool unexpectedly succeeded without OAuth")
                github_api.assert_not_called()
        asyncio.run(check())

    def test_allowed_identity(self):
        ctx = SimpleNamespace(token=SimpleNamespace(claims={"login": "CrGasparoto-Br"}))
        self.assertTrue(server.authorized_github_user(ctx))

    def test_denied_identities(self):
        for claims in ({}, {"login": ""}, {"login": "stranger"}, {"login": None}, {"login": ["crgasparoto-br"]}):
            with self.subTest(claims=claims):
                ctx = SimpleNamespace(token=SimpleNamespace(claims=claims))
                self.assertFalse(server.authorized_github_user(ctx))

    def test_no_token(self):
        self.assertFalse(server.authorized_github_user(SimpleNamespace(token=None)))

    def test_allowed_repo(self):
        self.assertEqual(server.allowed_repository("CRGASPAROTO-BR/TRAINING-SYSTEM"), ("crgasparoto-br", "training-system"))

    def test_blocked_repo(self):
        with self.assertRaises(ValueError):
            server.allowed_repository("another-owner/private")


if __name__ == "__main__":
    unittest.main()
