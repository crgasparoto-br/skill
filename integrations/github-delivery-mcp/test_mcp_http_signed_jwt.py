"""Real loopback HTTP tests for MCP resource-bound JWT authentication."""
import http.client
import json
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from mcp_http_local import MCPHandler
from mcp_jwt_verifier import MCPTokenPolicy
from mcp_read_dispatch import VERSION, META_VERSION

class SignedHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = cls.key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
        class Handler(MCPHandler):
            token_policy = MCPTokenPolicy(
                issuer="https://identity.example.test",
                audience="https://delivery.example.test/mcp",
                public_key_pem=pem,
                key_id="test-key",
                allowed_subjects=frozenset({"authorized"}))
            oauth_metadata_url = "https://delivery.example.test/.well-known/oauth-protected-resource"
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.allow_ephemeral_host = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def token(self, **changes):
        now = int(datetime.now(timezone.utc).timestamp())
        claims = {"iss": "https://identity.example.test",
                  "aud": "https://delivery.example.test/mcp",
                  "sub": "authorized", "scope": "solverit:read",
                  "iat": now - 5, "nbf": now - 5, "exp": now + 90}
        claims.update(changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "test-key"})

    def send(self, token=None, method="tools/list"):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method,
                   "params": {"_meta": {META_VERSION: VERSION, "io.modelcontextprotocol/clientCapabilities": {}, "io.modelcontextprotocol/clientInfo": {"name": "issue88-http-test", "version": "1.0"}}}}
        headers = {"Content-Type": "application/json", "MCP-Protocol-Version": VERSION,
                   "MCP-Method": method}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        conn.request("POST", "/mcp", json.dumps(payload), headers)
        response = conn.getresponse()
        status, body = response.status, json.loads(response.read())
        conn.close()
        return status, body

    def test_valid_mcp_jwt_can_discover_empty_tools(self):
        status, payload = self.send(self.token())
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["tools"], [])

    def test_github_token_rejected(self):
        self.assertEqual(self.send("ghu_not_an_mcp_jwt")[0], 401)

    def test_missing_token_rejected(self):
        self.assertEqual(self.send()[0], 401)

    def test_wrong_audience_rejected(self):
        self.assertEqual(self.send(self.token(aud="https://api.github.com"))[0], 401)

    def test_expired_token_rejected(self):
        self.assertEqual(self.send(self.token(exp=1))[0], 401)

    def test_no_write_or_tool_call_exposed(self):
        self.assertEqual(self.send(self.token(), method="tools/call")[0], 404)

    def test_discovery_has_server_info(self):
        status, payload = self.send(self.token())
        self.assertEqual(status, 200)
        self.assertIn("io.modelcontextprotocol/serverInfo", payload["result"]["_meta"])

    def test_rejected_method_is_jsonrpc_error(self):
        status, payload = self.send(self.token(), method="tools/call")
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"]["code"], -32601)

    def test_missing_client_info_allowed(self):
        # Reuse real HTTP transport, sending a valid token with incomplete metadata.
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=3)
        payload = {"jsonrpc": "2.0", "id": 9, "method": "tools/list",
                   "params": {"_meta": {META_VERSION: VERSION,
                                       "io.modelcontextprotocol/clientCapabilities": {}}}}
        conn.request("POST", "/mcp", json.dumps(payload),
                     {"Content-Type": "application/json",
                      "Authorization": "Bearer " + self.token(),
                      "MCP-Protocol-Version": VERSION, "MCP-Method": "tools/list"})
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        response.read()
        conn.close()

    def test_server_discover(self):
        status, payload = self.send(self.token(), method="server/discover")
        self.assertEqual(status, 200)
        self.assertEqual(payload["result"]["supportedVersions"], [VERSION])
        self.assertEqual(payload["result"]["capabilities"], {})

    def test_no_policy_fails_closed(self):
        class NoPolicyHandler(MCPHandler):
            token_policy = None
        other = ThreadingHTTPServer(("127.0.0.1", 0), NoPolicyHandler)
        other.allow_ephemeral_host = True
        thread = threading.Thread(target=other.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", other.server_address[1], timeout=3)
            connection.request("POST", "/mcp", json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/list",
                "params": {"_meta": {META_VERSION: VERSION}}}),
                {"Content-Type": "application/json", "MCP-Protocol-Version": VERSION,
                 "MCP-Method": "tools/list"})
            response = connection.getresponse()
            self.assertEqual(response.status, 503)
            response.read()
            connection.close()
        finally:
            other.shutdown()
            other.server_close()
            thread.join(timeout=3)

if __name__ == "__main__":
    unittest.main()
