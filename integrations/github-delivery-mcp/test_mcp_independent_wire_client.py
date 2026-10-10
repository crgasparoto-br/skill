"""Independent, no-SDK MCP 2026-07-28 HTTP wire client smoke test.

Exercises the actual TCP/HTTP/JSON-RPC boundary with signed test JWTs.
No GitHub requests, production credentials, jobs, or writes. A passing run
is a wire-contract smoke test, NOT certification by an external MCP SDK.
"""
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
from mcp_read_dispatch import META_VERSION, VERSION


class IndependentWireClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = cls.key.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode("ascii")
        class Handler(MCPHandler):
            token_policy = MCPTokenPolicy(
                issuer="https://id.example.test",
                audience="https://mcp.example.test/mcp",
                public_key_pem=pem, key_id="wire-test",
                allowed_subjects=frozenset({"operator"}))
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.allow_ephemeral_host = True
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=3)

    def token(self):
        now = int(datetime.now(timezone.utc).timestamp())
        return jwt.encode({
            "iss": "https://id.example.test", "aud": "https://mcp.example.test/mcp",
            "sub": "operator", "iat": now - 5, "nbf": now - 5,
            "exp": now + 120, "scope": "solverit:read"},
            self.key, algorithm="RS256", headers={"kid": "wire-test"})

    def exchange(self, method, params=None, *, token=None, method_header=None):
        message = {"jsonrpc": "2.0", "id": 78, "method": method,
                   "params": params if params is not None else {
                       "_meta": {META_VERSION: VERSION,
                                 "io.modelcontextprotocol/clientCapabilities": {},
                                 "io.modelcontextprotocol/clientInfo": {
                                     "name": "independent-wire-client", "version": "1.0"}}}}
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": VERSION,
                   "Mcp-Method": method if method_header is None else method_header}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        conn = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=5)
        conn.request("POST", "/mcp", json.dumps(message), headers)
        response = conn.getresponse()
        status, content_type = response.status, response.getheader("Content-Type")
        payload = json.loads(response.read())
        conn.close()
        return status, content_type, payload

    def test_discovery_has_response_identity(self):
        status, content_type, body = self.exchange("server/discover", token=self.token())
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(body["id"], 78)
        self.assertIn(VERSION, body["result"]["supportedVersions"])
        self.assertIn("io.modelcontextprotocol/serverInfo", body["result"]["_meta"])

    def test_tool_catalog_is_empty_without_write_access(self):
        status, _, body = self.exchange("tools/list", token=self.token())
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["tools"], [])

    def test_header_mismatch_is_denied(self):
        status, _, _body = self.exchange(
            "tools/list", token=self.token(), method_header="tools/call")
        self.assertEqual(status, 400)

    def test_unknown_method_jsonrpc_error(self):
        status, _, body = self.exchange("tools/unknown", token=self.token())
        self.assertEqual(status, 404)
        self.assertEqual(body["error"]["code"], -32601)

    def test_unauthenticated_client_is_rejected(self):
        status, _, _ = self.exchange("server/discover")
        self.assertEqual(status, 401)

if __name__ == "__main__":
    unittest.main()
