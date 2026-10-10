"""Loopback-only HTTP adapter for the read-only MCP authorization pilot.

Not a public MCP service. OAuth discovery, token acquisition, proxy trust,
production quotas and compatibility certification remain outside this pilot.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp_read_dispatch import VERSION
from oauth_resource_metadata import resource_metadata, authenticate_challenge
from mcp_jwt_verifier import MCPTokenPolicy, MCPTokenRejected, verify_mcp_access_token

MAX_BODY = 16384

class MCPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    oauth_metadata = None
    oauth_metadata_url = None
    token_policy = None

    def log_message(self, *args):
        # Avoid logging tokens, request contents or untrusted paths.
        return

    def do_POST(self):
        if self.path != "/mcp":
            self._send(404, {"error": "not found"})
            return
        # Reject browser-origin requests (including DNS rebinding attempts).
        # This prototype is a non-browser loopback API only.
        if len(self.headers.get_all("Host", [])) != 1:
            self._send(403, {"error": "ambiguous host"})
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self._send(400, {"error": "chunked bodies are not supported"})
            return
        if self.headers.get("Origin") is not None:
            self._send(403, {"error": "browser origins are not accepted"})
            return
        if self.headers.get("Host") not in ("127.0.0.1:8769", "localhost:8769") and not getattr(self.server, "allow_ephemeral_host", False):
            self._send(403, {"error": "invalid host"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._send(415, {"error": "unsupported media type"})
            return
        if len(self.headers.get_all("Content-Length", [])) != 1:
            self._send(400, {"error": "ambiguous content length"})
            return
        try:
            size = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            size = -1
        if not 0 <= size <= MAX_BODY:
            self._send(413, {"error": "invalid content length"})
            return
        try:
            request = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "invalid json"})
            return
        authorization = self.headers.get("Authorization", "")
        if len(authorization) > 1200 or "," in authorization or self.headers.get_all("Authorization", []) and len(self.headers.get_all("Authorization", [])) != 1:
            self._send(401, {"error": "invalid authorization header"})
            return
        bearer = authorization[7:] if authorization.startswith("Bearer ") else ""
        # Never fall back to GitHub user-token authentication.
        if self.token_policy is None:
            self._send(503, {"error": "MCP token validation not configured"})
            return
        try:
            subject = verify_mcp_access_token(bearer, self.token_policy)
        except MCPTokenRejected:
            self._send(401, {"error": "invalid MCP access token"},
                       headers={"WWW-Authenticate": authenticate_challenge(
                           resource_metadata_url=self.oauth_metadata_url)}
                       if self.oauth_metadata_url else None)
            return
        # This pilot intentionally exposes no tools or write methods.
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            self._send(400, {"error": "invalid JSON-RPC request"})
            return
        if type(request.get("id")) not in (int, str):
            self._send(400, {"error": "invalid JSON-RPC request id"})
            return
        params = request.get("params")
        metadata = params.get("_meta") if isinstance(params, dict) else None
        if not isinstance(metadata, dict):
            self._send(400, {"error": "missing MCP request metadata"})
            return
        if (self.headers.get("MCP-Protocol-Version") != VERSION
                or metadata.get("io.modelcontextprotocol/protocolVersion") != VERSION):
            self._send(400, {"error": "unsupported or mismatched MCP protocol version"})
            return
        client_info = metadata.get("io.modelcontextprotocol/clientInfo")
        if (client_info is not None and (not isinstance(client_info, dict)
                or not isinstance(client_info.get("name"), str)
                or not client_info["name"].strip()
                or not isinstance(client_info.get("version"), str)
                or not client_info["version"].strip())):
            self._send(400, {"error": "valid MCP clientInfo required"})
            return
        if not isinstance(metadata.get("io.modelcontextprotocol/clientCapabilities"), dict):
            self._send(400, {"error": "client capabilities required"})
            return
        if self.headers.get("MCP-Method") != request.get("method"):
            self._send(400, {"error": "MCP method header mismatch"})
            return
        if request.get("method") == "server/discover" and self.headers.get("MCP-Name") is None:
            self._send(200, {"jsonrpc": "2.0", "id": request["id"],
                             "result": {"supportedVersions": [VERSION],
                                        "capabilities": {},
                                        "_meta": {
                                            "io.modelcontextprotocol/serverInfo": {
                                                "name": "solverit-issue-delivery-pilot",
                                                "version": "0.0.0"}}}})
            return
        if request.get("method") == "tools/list" and self.headers.get("MCP-Name") is None:
            self._send(200, {"jsonrpc": "2.0", "id": request["id"],
                             "result": {"tools": [], "_meta": {
                                 "io.modelcontextprotocol/serverInfo": {
                                     "name": "solverit-issue-delivery-pilot", "version": "0.0.0"}}}})
            return
        self._send(404, {"jsonrpc": "2.0", "id": request["id"],
                         "error": {"code": -32601, "message": "Method not found"}})
        return

    def do_GET(self):
        if self.path == "/.well-known/oauth-protected-resource":
            if self.oauth_metadata is None:
                self._send(404, {"error": "OAuth is not configured"})
            else:
                self._send(200, self.oauth_metadata)
            return
        self._send(405, {"error": "method not allowed"})

    def _send(self, status, payload, headers=None):
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

def main():
    resource = os.environ.get("SOLVERIT_MCP_RESOURCE_URL", "")
    issuer = os.environ.get("SOLVERIT_OAUTH_ISSUER_URL", "")
    if bool(resource) != bool(issuer):
        raise RuntimeError("resource and issuer must be configured together")
    if resource:
        MCPHandler.oauth_metadata = resource_metadata(resource_url=resource, issuer_url=issuer)
        MCPHandler.oauth_metadata_url = resource.removesuffix("/mcp") + "/.well-known/oauth-protected-resource"
    key_path = os.environ.get("SOLVERIT_MCP_JWT_PUBLIC_KEY_FILE", "")
    key_id = os.environ.get("SOLVERIT_MCP_JWT_KEY_ID", "")
    subjects = frozenset(v for v in os.environ.get("SOLVERIT_MCP_SUBJECTS", "").split(",") if v)
    if resource and issuer and key_path and key_id and subjects:
        with open(key_path, "r", encoding="ascii") as pem_file:
            MCPHandler.token_policy = MCPTokenPolicy(
                issuer=issuer, audience=resource, public_key_pem=pem_file.read(),
                key_id=key_id, allowed_subjects=subjects)
    server = ThreadingHTTPServer(("127.0.0.1", 8769), MCPHandler)
    server.serve_forever()

if __name__ == "__main__":
    main()
