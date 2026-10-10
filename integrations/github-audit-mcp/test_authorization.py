"""Regression tests for MCP authorization and repository allowlists.

Run: python -m unittest discover -s integrations/github-audit-mcp -p 'test_*.py'
"""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

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
        protected_tools = (
            ("list_rulesets", {"repository": "crgasparoto-br/training-system"}),
            ("get_branch_rules", {"repository": "crgasparoto-br/training-system", "branch": "develop"}),
            ("get_branch_protection", {"repository": "crgasparoto-br/training-system", "branch": "main"}),
            ("get_ruleset_details", {"repository": "crgasparoto-br/training-system", "ruleset_id": 1}),
        )

        async def check():
            for tool_name, arguments in protected_tools:
                with self.subTest(tool=tool_name), patch.object(server, "_get") as github_api:
                    try:
                        await server.mcp.call_tool(tool_name, arguments)
                    except Exception:
                        pass  # Not found / unauthorized are valid fail-closed outcomes.
                    else:
                        self.fail(f"{tool_name} unexpectedly succeeded without OAuth")
                    github_api.assert_not_called()

        asyncio.run(check())

    def test_rulesets_multiple_pages(self):
        first = [{"id": i} for i in range(100)]
        second = [{"id": 100}]
        with patch.object(server, "_get", side_effect=[first, second]) as github_api:
            result = server.list_rulesets.fn("crgasparoto-br/training-system") if hasattr(server.list_rulesets, "fn") else server.list_rulesets("crgasparoto-br/training-system")
        self.assertEqual(len(result["rulesets"]), 101)
        self.assertTrue(result["pagination_complete"])
        self.assertIn("page=2", github_api.call_args_list[1].args[1])

    def test_rulesets_limit_fails_closed(self):
        with patch.object(server, "_get", return_value=[{"id": i} for i in range(100)]) as github_api:
            result = server.list_rulesets.fn("crgasparoto-br/training-system") if hasattr(server.list_rulesets, "fn") else server.list_rulesets("crgasparoto-br/training-system")
        self.assertFalse(result["pagination_complete"])
        self.assertEqual(github_api.call_count, 10)

    def test_rulesets_api_failure_propagates(self):
        with patch.object(server, "_get", side_effect=httpx.TimeoutException("timeout")), self.assertRaises(httpx.TimeoutException):
                server.list_rulesets.fn("crgasparoto-br/training-system") if hasattr(server.list_rulesets, "fn") else server.list_rulesets("crgasparoto-br/training-system")

    def test_missing_bypass_remains_unknown(self):
        with patch.object(server, "_get", return_value={"id": 42}):
            result = server.get_ruleset_details.fn("crgasparoto-br/training-system", 42) if hasattr(server.get_ruleset_details, "fn") else server.get_ruleset_details("crgasparoto-br/training-system", 42)
        self.assertEqual(result["bypass_actors_visibility"], "UNKNOWN_NO_WRITE_ACCESS")

    def test_explicit_empty_bypass_is_observed(self):
        with patch.object(server, "_get", return_value={"id": 42, "bypass_actors": []}):
            result = server.get_ruleset_details.fn("crgasparoto-br/training-system", 42) if hasattr(server.get_ruleset_details, "fn") else server.get_ruleset_details("crgasparoto-br/training-system", 42)
        self.assertEqual(result["bypass_actors_visibility"], "OBSERVED")

    def test_token_generation_is_not_cached(self):
        with patch.object(server, "_repository_installation", return_value=123), patch.object(server, "_jwt", return_value="appjwt"), patch.object(server.httpx, "Client") as client:
            response = client.return_value.__enter__.return_value.post.return_value
            response.json.side_effect = [{"token": "first"}, {"token": "second"}]
            self.assertEqual(server._installation_token("crgasparoto-br/training-system"), "first")  # noqa: SLF001 - verify token renewal behavior
            self.assertEqual(server._installation_token("crgasparoto-br/training-system"), "second")  # noqa: SLF001 - verify token renewal behavior
            self.assertEqual(response.raise_for_status.call_count, 2)

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
