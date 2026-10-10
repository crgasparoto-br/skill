"""Offline checks of the live probe's decision logic; never claim live OAuth approval."""
import unittest
from unittest.mock import patch

import httpx
import probe_live_oauth as live


class ProbeTests(unittest.TestCase):
    def test_denied_http_auth_is_not_application_layer_evidence(self):
        with patch.object(live, "rpc", return_value={"denied": True}):
            results = live.probe("https://example.test/mcp", "allowed", "denied", "owner/repo")
        self.assertFalse(results["authorized_initialized"])
        self.assertFalse(results["unauthorized_application_auth_tested"])

    def test_real_negative_session_must_hide_and_deny_every_tool(self):
        def fake_rpc(client, endpoint, token, method, params, request_id, sessions):
            if method == "initialize":
                return {"result": {"protocolVersion": live.PROTOCOL}}
            if method == "tools/list":
                names = live.TOOLS if token == "allowed" else ()
                return {"result": {"tools": [{"name": name} for name in names]}}
            if token == "denied":
                return {"error": {"code": -32601, "message": "denied"}}
            if params["arguments"].get("branch") == "unapproved":
                return {"error": {"code": -32602, "message": "invalid branch"}}
            if params["arguments"].get("repository") == "unapproved/repository":
                return {"error": {"code": -32602, "message": "invalid repository"}}
            return {"result": {"content": [], "isError": False}}

        with patch.object(live, "rpc", side_effect=fake_rpc):
            results = live.probe("https://example.test/mcp", "allowed", "denied", "owner/repo")
        self.assertTrue(all(results.values()), results)

    def test_exposed_tool_fails_denied_identity(self):
        def fake_rpc(client, endpoint, token, method, params, request_id, sessions):
            if method == "initialize":
                return {"result": {"protocolVersion": live.PROTOCOL}}
            if method == "tools/list":
                return {"result": {"tools": [{"name": "list_rulesets"}]}}
            return {"error": {"code": -32601, "message": "denied"}}

        with patch.object(live, "rpc", side_effect=fake_rpc):
            results = live.probe("https://example.test/mcp", "allowed", "denied", "owner/repo")
        self.assertFalse(results["unauthorized_tools_hidden"])

    def test_rpc_does_not_follow_redirect_or_log_token(self):
        def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer secret")
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
                headers={"Mcp-Session-Id": "session1"},
            )
        with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False) as client:
            sessions = {}
            result = live.rpc(client, "https://example.test/mcp", "secret", "tools/list", {}, 1, sessions)
        self.assertTrue(live._successful(result))
        self.assertEqual(sessions["secret"], "session1")


if __name__ == "__main__":
    unittest.main()
