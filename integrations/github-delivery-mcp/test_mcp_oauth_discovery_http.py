"""HTTP contract tests for optional protected-resource discovery."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer

from mcp_http_local import MCPHandler
from oauth_resource_metadata import resource_metadata
from mcp_read_dispatch import VERSION, META_VERSION

class OAuthDiscoveryHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(MCPHandler):
            oauth_metadata = resource_metadata(
                resource_url="https://delivery.example.test/mcp",
                issuer_url="https://identity.example.test")
            oauth_metadata_url = "https://delivery.example.test/.well-known/oauth-protected-resource"
            allowed_ids = frozenset({123})
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.allow_ephemeral_host = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        conn.request(method, path, body=body, headers=headers or {})
        result = conn.getresponse()
        status, headers, data = result.status, dict(result.getheaders()), result.read()
        conn.close()
        return status, headers, json.loads(data)

    def test_discovery_returns_protected_resource(self):
        status, _, payload = self.request("GET", "/.well-known/oauth-protected-resource")
        self.assertEqual(status, 200)
        self.assertEqual(payload["authorization_servers"], ["https://identity.example.test"])

    def test_missing_token_gets_metadata_challenge(self):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list",
                           "params": {"_meta": {META_VERSION: VERSION}}})
        status, headers, _ = self.request("POST", "/mcp", body, {
            "Content-Type": "application/json", "MCP-Protocol-Version": VERSION,
            "MCP-Method": "tools/list"})
        self.assertEqual(status, 401)
        self.assertEqual(headers["WWW-Authenticate"],
                         'Bearer resource_metadata="https://delivery.example.test/.well-known/oauth-protected-resource"')

    def test_discovery_does_not_enable_writes(self):
        status, _, _ = self.request("GET", "/mcp")
        self.assertEqual(status, 405)

if __name__ == "__main__":
    unittest.main()
