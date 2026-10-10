"""Loopback-only HTTP adapter for the read-only MCP authorization pilot.

Not a public MCP service. OAuth discovery, token acquisition, proxy trust,
production quotas and compatibility certification remain outside this pilot.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp_read_dispatch import dispatch, VERSION
from oauth_resource_metadata import resource_metadata, authenticate_challenge

MAX_BODY = 16384

class MCPHandler(BaseHTTPRequestHandler):
    allowed_ids = frozenset()
    protocol_version = "HTTP/1.1"
    oauth_metadata = None
    oauth_metadata_url = None

    def log_message(self, *args):
        # Avoid logging tokens, request contents or untrusted paths.
        return

    def do_POST(self):
        if self.path != "/mcp":
            self._send(404, {"error": "not found"})
            return
        # Reject browser-origin requests (including DNS rebinding attempts).
        # This prototype is a non-browser loopback API only.
        if self.headers.get("Origin") is not None:
            self._send(403, {"error": "browser origins are not accepted"})
            return
        if self.headers.get("Host") not in ("127.0.0.1:8769", "localhost:8769") and not getattr(self.server, "allow_ephemeral_host", False):
            self._send(403, {"error": "invalid host"})
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self._send(415, {"error": "unsupported media type"})
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
        outcome = dispatch(
            request,
            protocol_header=self.headers.get("MCP-Protocol-Version", ""),
            method_header=self.headers.get("MCP-Method", ""),
            name_header=self.headers.get("MCP-Name"),
            bearer=bearer,
            allowed_ids=self.allowed_ids,
        )
        extra = {}
        if outcome.http_status == 401 and self.oauth_metadata_url:
            extra["WWW-Authenticate"] = authenticate_challenge(
                resource_metadata_url=self.oauth_metadata_url)
        self._send(outcome.http_status, outcome.payload, headers=extra)

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
    raw = os.environ.get("SOLVERIT_ALLOWED_GITHUB_IDS", "")
    ids = frozenset(int(part) for part in raw.split(",") if part.isdecimal())
    if not ids:
        raise RuntimeError("non-empty server-side GitHub ID allowlist required")
    MCPHandler.allowed_ids = ids
    resource = os.environ.get("SOLVERIT_MCP_RESOURCE_URL", "")
    issuer = os.environ.get("SOLVERIT_OAUTH_ISSUER_URL", "")
    if bool(resource) != bool(issuer):
        raise RuntimeError("resource and issuer must be configured together")
    if resource:
        MCPHandler.oauth_metadata = resource_metadata(resource_url=resource, issuer_url=issuer)
        MCPHandler.oauth_metadata_url = resource.removesuffix("/mcp") + "/.well-known/oauth-protected-resource"
    server = ThreadingHTTPServer(("127.0.0.1", 8769), MCPHandler)
    server.serve_forever()

if __name__ == "__main__":
    main()
