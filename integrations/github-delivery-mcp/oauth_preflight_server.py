"""Loopback-only authorization preflight for Issue 88 (NOT a full MCP server).

Never accepts principals, profiles, tokens for GitHub App, or auth decisions from
the JSON body. Caller must send a GitHub user OAuth bearer token via header.
This service deliberately performs no writes, token minting or job dispatch.
Deployment requires a dedicated service identity and an OAuth-compatible
trusted client flow; do not expose to public networks.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from github_oauth_identity import IdentityVerificationError, verify_github_user_token
from mcp_authorization import authorize_operation
from policy import PolicyDeniedError

MAX_BODY = 4096
BIND_ADDRESS = "127.0.0.1"



def authorize_http_request(bearer: str, payload: dict, allowed_ids: frozenset[int]):
    if not isinstance(payload, dict) or set(payload) != {
        "action", "repository", "branch", "expected_head"
    }:
        raise ValueError("invalid request fields")
    if payload["action"] not in ("prepare_workspace", "get_job_status"):
        raise PolicyDeniedError("operation not enabled")
    principal = verify_github_user_token(bearer, allowed_github_ids=allowed_ids)
    return authorize_operation(
        principal=principal,
        action=payload["action"],
        repository=payload["repository"],
        branch=payload["branch"],
        expected_head=payload["expected_head"],
        allowed_subjects=frozenset(f"github:{user_id}" for user_id in allowed_ids),
    )

class AuthPreflightHandler(BaseHTTPRequestHandler):
    allowed_ids: frozenset[int] = frozenset()

    def log_message(self, fmt, *args):
        # Never print arbitrary request paths or headers to logs.
        pass

    def do_POST(self):
        if urlsplit(self.path).path != "/authorize" or self.path != "/authorize":
            self.send_error(404)
            return
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or len(auth) > 1200:
            self._reply(401, {"allowed": False})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "-1"))
            if not 0 <= content_length <= MAX_BODY:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(content_length))
            authorize_http_request(auth[7:], payload, self.allowed_ids)
        except (ValueError, TypeError, IdentityVerificationError, PolicyDeniedError,
                KeyError, AttributeError):
            self._reply(403, {"allowed": False})
            return
        except Exception:
            self._reply(503, {"allowed": False})
            return
        self._reply(200, {"allowed": True})

    def _reply(self, status, payload):
        encoded = json.dumps(payload).encode("ascii")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

def main():
    raw_ids = os.environ.get("SOLVERIT_ALLOWED_GITHUB_IDS", "")
    allowed = frozenset(int(item) for item in raw_ids.split(",") if item.isdecimal())
    if not allowed:
        raise RuntimeError("server-side GitHub allowlist is required")
    AuthPreflightHandler.allowed_ids = allowed
    server = ThreadingHTTPServer((BIND_ADDRESS, 8768), AuthPreflightHandler)
    server.serve_forever()

if __name__ == "__main__":
    main()
