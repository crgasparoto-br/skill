"""Local HTTP transport tests; no credentials or GitHub network access."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from mcp_http_local import MCPHandler
from mcp_read_dispatch import VERSION, META_VERSION

class HTTPMCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MCPHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, payload, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request("POST", "/mcp", body=json.dumps(payload),
                     headers={"Content-Type": "application/json", **(headers or {})})
        response = conn.getresponse()
        result = (response.status, json.loads(response.read()))
        conn.close()
        return result

    def rpc(self):
        return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"_meta": {META_VERSION: VERSION},
                           "name": "solverit_authorize_read",
                           "arguments": {
                               "repository": "crgasparoto-br/training-system",
                               "branch": "feat/88-controlled-issue-delivery",
                               "expected_head": "a" * 40}}}

    def headers(self):
        return {"Authorization": "Bearer simulated-oauth",
                "MCP-Protocol-Version": VERSION, "MCP-Method": "tools/call",
                "MCP-Name": "solverit_authorize_read"}

    def test_absent_token_rejected(self):
        h = self.headers()
        del h["Authorization"]
        status, _ = self.request(self.rpc(), h)
        self.assertEqual(status, 401)

    def test_valid_authorization_preflight(self):
        with patch("mcp_read_dispatch.authorize_http_request"):
            status, body = self.request(self.rpc(), self.headers())
        self.assertEqual(status, 200)
        self.assertIn("no job started", body["result"]["content"][0]["text"])

    def test_wrong_version_rejected(self):
        h = self.headers()
        h["MCP-Protocol-Version"] = "invalid"
        status, _ = self.request(self.rpc(), h)
        self.assertEqual(status, 400)

    def test_write_not_exposed(self):
        payload = self.rpc()
        payload["params"]["name"] = "publish_pr"
        h = self.headers()
        h["MCP-Name"] = "publish_pr"
        status, _ = self.request(payload, h)
        self.assertEqual(status, 404)

    def test_invalid_body_rejected(self):
        status, _ = self.request([], self.headers())
        self.assertEqual(status, 400)

if __name__ == "__main__":
    unittest.main()
