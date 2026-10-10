"""Stateless MCP 2026-07-28 authorization-only pilot.

This is NOT a complete MCP deployment: OAuth discovery, authorization-code
flow, public endpoints, production rate limits and writes are not enabled.
All requests must pass verified GitHub identity in a trusted HTTP wrapper.
"""
from __future__ import annotations
from dataclasses import dataclass
from oauth_preflight_server import authorize_http_request

VERSION = "2026-07-28"
META_VERSION = "io.modelcontextprotocol/protocolVersion"
TOOLS = [{
    "name": "solverit_authorize_read",
    "description": "Validate a proposed read-only workspace inspection; executes no jobs.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "repository": {"type": "string"},
            "branch": {"type": "string"},
            "expected_head": {"type": "string"},
        },
        "required": ["repository", "branch", "expected_head"],
        "additionalProperties": False,
    },
}]

@dataclass(frozen=True)
class MCPResponse:
    http_status: int
    payload: dict

def _error(request_id, code, message, status):
    return MCPResponse(status, {"jsonrpc": "2.0", "id": request_id,
                                "error": {"code": code, "message": message}})

def dispatch(request: dict, *, protocol_header: str, method_header: str,
             name_header: str | None, bearer: str, allowed_ids: frozenset[int]):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return _error(None, -32600, "Invalid request", 400)
    request_id = request.get("id")
    if type(request_id) not in (int, str):
        return _error(None, -32600, "Invalid request ID", 400)
    method = request.get("method")
    params = request.get("params", {})
    if not isinstance(params, dict) or not isinstance(method, str):
        return _error(request_id, -32600, "Invalid request", 400)
    metadata = params.get("_meta", {})
    if (protocol_header != VERSION or not isinstance(metadata, dict)
            or metadata.get(META_VERSION) != VERSION):
        return _error(request_id, -32600, "Unsupported or mismatched protocol version", 400)
    if method_header != method:
        return _error(request_id, -32600, "Method header mismatch", 400)
    if method == "tools/list":
        if name_header is not None:
            return _error(request_id, -32600, "Unexpected tool name header", 400)
        # No unauthenticated tool discovery.
        if not bearer:
            return _error(request_id, -32001, "Unauthorized", 401)
        from github_oauth_identity import verify_github_user_token
        try:
            verify_github_user_token(bearer, allowed_github_ids=allowed_ids)
        except Exception:
            return _error(request_id, -32001, "Unauthorized", 401)
        return MCPResponse(200, {"jsonrpc": "2.0", "id": request_id,
                                 "result": {"tools": TOOLS}})
    if method != "tools/call":
        return _error(request_id, -32601, "Method not found", 404)
    if params.get("name") != "solverit_authorize_read" or name_header != params.get("name"):
        return _error(request_id, -32601, "Tool not available", 404)
    args = params.get("arguments", {})
    if not isinstance(args, dict) or set(args) != {"repository", "branch", "expected_head"}:
        return _error(request_id, -32602, "Invalid arguments", 400)
    try:
        authorize_http_request(bearer, {
            "action": "prepare_workspace",
            "repository": args["repository"],
            "branch": args["branch"],
            "expected_head": args["expected_head"],
        }, allowed_ids)
    except Exception:
        return _error(request_id, -32001, "Unauthorized or forbidden", 403)
    return MCPResponse(200, {"jsonrpc": "2.0", "id": request_id,
                             "result": {"content": [{"type": "text",
                                                     "text": "Read-only authorization preflight approved; no job started."}]}})
