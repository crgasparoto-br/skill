"""Loopback-only HTTP adapter for the read-only MCP authorization pilot.

Not a public MCP service. OAuth discovery, token acquisition, proxy trust,
production quotas and compatibility certification remain outside this pilot.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mcp_read_dispatch import dispatch, VERSION

MAX_BODY = 16384

class MCPHandler(BaseHTTPRequestHandler):
    allowed_ids = frozenset()
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        # Avoid logging tokens, request contents or untrusted paths.
        return

    def do_POST(self):
        if self.path != "/mcp":
            self._send(404, {"error": "not found"})
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
        bearer = authorization[7:] if authorization.startswith("Bearer ") else ""
        outcome = dispatch(
            request,
            protocol_header=self.headers.get("MCP-Protocol-Version", ""),
            method_header=self.headers.get("MCP-Method", ""),
            name_header=self.headers.get("MCP-Name"),
            bearer=bearer,
            allowed_ids=self.allowed_ids,
        )
        self._send(outcome.http_status, outcome.payload)

    def do_GET(self):
        self._send(405, {"error": "method not allowed"})

    def _send(self, status, payload):
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

def main():
    raw = os.environ.get("SOLVERIT_ALLOWED_GITHUB_IDS", "")
    ids = frozenset(int(part) for part in raw.split(",") if part.isdecimal())
    if not ids:
        raise RuntimeError("non-empty server-side GitHub ID allowlist required")
    MCPHandler.allowed_ids = ids
    server = ThreadingHTTPServer(("127.0.0.1", 8769), MCPHandler)
    server.serve_forever()

if __name__ == "__main__":
    main()
