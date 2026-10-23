"""End-to-end negative HTTP requests through real loopback server, no mocks.

Uses deliberately malformed OAuth bearer values rejected locally before any
network request to GitHub; no credentials, GitHub access or job execution.
"""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from mcp_http_local import MCPHandler
from mcp_jwt_verifier import MCPTokenPolicy
from mcp_read_dispatch import META_VERSION, VERSION


class RealNegativeHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class PilotHandler(MCPHandler):
            token_policy = MCPTokenPolicy(issuer="https://identity.example.test",
                audience="https://delivery.example.test/mcp",
                public_key_pem="TEST ONLY UNUSED", key_id="test-key",
                allowed_subjects=frozenset({"test-user"}))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), PilotHandler)
        cls.server.allow_ephemeral_host = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def send(self, method, payload, bearer=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        headers = {
            "Content-Type": "application/json",
            "MCP-Protocol-Version": VERSION,
            "MCP-Method": method,
        }
        if method == "tools/call":
            headers["MCP-Name"] = "solverit_authorize_read"
        if bearer is not None:
            headers["Authorization"] = "Bearer " + bearer
        body = json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": method,
            "params": {"_meta": {META_VERSION: VERSION},
                       **({"name": "solverit_authorize_read",
                           "arguments": {"repository": "crgasparoto-br/training-system",
                                         "branch": "feat/88-controlled-issue-delivery",
                                         "expected_head": "a" * 40}}
                          if method == "tools/call" else {})},
        })
        conn.request("POST", "/mcp", body, headers)
        response = conn.getresponse()
        status = response.status
        response.read()
        conn.close()
        return status

    def test_absent_bearer_denied(self):
        self.assertEqual(self.send("tools/call", {}, None), 401)

    def test_blank_bearer_denied(self):
        self.assertEqual(self.send("tools/call", {}, "   "), 401)

    def test_malformed_bearer_denied_without_github(self):
        self.assertEqual(self.send("tools/call", {}, "x"), 401)

    def test_tools_list_malformed_bearer_denied_without_github(self):
        self.assertEqual(self.send("tools/list", {}, "x"), 401)

if __name__ == "__main__":
    unittest.main()
