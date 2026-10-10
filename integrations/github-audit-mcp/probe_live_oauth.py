"""Live MCP OAuth authorization probe. Requires two *real* MCP bearer sessions.

This never mints credentials or calls GitHub directly. Redacted output only.
The separate server-side zero-GitHub-call assertion remains mandatory.
"""
import argparse
import json
from pathlib import Path

import httpx

PROTOCOL = "2025-03-26"
TOOLS = ("list_rulesets", "get_branch_rules", "get_branch_protection", "get_ruleset_details")


def rpc(client, endpoint, token, method, params, request_id, session_ids):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": PROTOCOL,
    }
    session_id = session_ids.get(token)
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    response = client.post(endpoint, headers=headers, json=payload)
    if response.status_code in (401, 403):
        return {"denied": True}
    response.raise_for_status()
    new_session = response.headers.get("Mcp-Session-Id")
    if new_session:
        # Track MCP transport sessions per credential without printing token or session id.
        session_ids[token] = new_session
    if "text/event-stream" in response.headers.get("content-type", ""):
        messages = [
            json.loads(line[6:])
            for line in response.text.splitlines()
            if line.startswith("data: ") and line[6:].startswith("{")
        ]
        if not messages:
            raise ValueError("No JSON-RPC response in SSE")
        data = messages[-1]
    else:
        data = response.json()
    return data


def _successful(result):
    return (
        isinstance(result, dict)
        and isinstance(result.get("result"), dict)
        and ("protocolVersion" in result["result"] or "content" in result["result"])
        and not result["result"].get("isError", False)
    )


def probe(endpoint, authorized_token, denied_token, repository):
    outcomes = {}
    session_ids = {}
    with httpx.Client(timeout=25.0, follow_redirects=False) as client:
        for label, token in (("authorized", authorized_token), ("unauthorized", denied_token)):
            initial = rpc(client, endpoint, token, "initialize", {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "solverit-live-audit-probe", "version": "1.0"},
            }, 1, session_ids)
            outcomes[label + "_initialized"] = _successful(initial)
            if not outcomes[label + "_initialized"]:
                # A rejected OAuth session proves ingress denial, not application-layer denial.
                outcomes[label + "_application_auth_tested"] = False
                continue
            listed = rpc(client, endpoint, token, "tools/list", {}, 2, session_ids)
            names = {t.get("name") for t in listed.get("result", {}).get("tools", [])}
            if label == "authorized":
                outcomes["authorized_tools_visible"] = set(TOOLS).issubset(names)
                for branch in ("develop", "main"):
                    result = rpc(client, endpoint, token, "tools/call", {
                        "name": "get_branch_rules", "arguments": {"repository": repository, "branch": branch}
                    }, 3 if branch == "develop" else 4, session_ids)
                    outcomes["authorized_" + branch] = _successful(result)
                for name, arguments in (
                    ("list_rulesets", {"repository": "unapproved/repository"}),
                    ("get_branch_rules", {"repository": repository, "branch": "unapproved"}),
                ):
                    result = rpc(client, endpoint, token, "tools/call", {
                        "name": name, "arguments": arguments
                    }, 5, session_ids)
                    outcomes["blocked_" + name] = not _successful(result)
            else:
                outcomes["unauthorized_application_auth_tested"] = True
                outcomes["unauthorized_tools_hidden"] = not bool(names.intersection(TOOLS))
                for name in TOOLS:
                    args = {"repository": repository}
                    if name in ("get_branch_rules", "get_branch_protection"):
                        args["branch"] = "develop"
                    if name == "get_ruleset_details":
                        args["ruleset_id"] = 1
                    result = rpc(client, endpoint, token, "tools/call", {
                        "name": name, "arguments": args
                    }, 6, session_ids)
                    outcomes["unauthorized_denied_" + name] = not _successful(result)
    return outcomes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True, help="HTTPS MCP endpoint")
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-token-file", type=Path, required=True)
    parser.add_argument("--denied-token-file", type=Path, required=True)
    args = parser.parse_args()
    if not args.endpoint.startswith("https://"):
        parser.error("HTTPS endpoint is required")
    allowed = args.allowed_token_file.read_text(encoding="utf-8").strip()
    denied = args.denied_token_file.read_text(encoding="utf-8").strip()
    if not allowed or not denied or allowed == denied:
        parser.error("Two distinct nonempty MCP session tokens are required")
    try:
        outcomes = probe(args.endpoint, allowed, denied, args.repository)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        print(json.dumps({"result": "NOT_VALIDATED", "error_type": type(exc).__name__}))
        return 1
    passed = bool(outcomes) and all(outcomes.values())
    print(json.dumps({"result": "PASS" if passed else "NOT_VALIDATED", "checks": outcomes}, sort_keys=True))
    # This is not release approval; server-side outbound-call and rotation evidence are separate.
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
