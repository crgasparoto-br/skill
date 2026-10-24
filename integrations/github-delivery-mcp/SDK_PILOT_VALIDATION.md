# Issue 88 — SDK Streamable HTTP compatibility candidate

The legacy pilot on 127.0.0.1:8769 is unchanged. This *candidate* runs on
127.0.0.1:8770 and exposes no tools. Do not update Caddy until authenticated
protocol compatibility and denial tests pass. It does not implement the executor.

Run in a dedicated worktree checked out at the exact PR #89 HEAD:

```bash
python3 -m venv /tmp/issue88-sdk-venv
/tmp/issue88-sdk-venv/bin/python -m pip install -r integrations/github-delivery-mcp/requirements-sdk-pilot.txt
cd integrations/github-delivery-mcp
/tmp/issue88-sdk-venv/bin/python -m unittest -v test_mcp_sdk_pilot
```

The SDK should be pinned to an audited lockfile before any production deployment.
The pilot deliberately fails startup when issuer, audience, allowed subjects or
JWKS cannot be loaded. Do not print or paste bearer tokens.

For an authenticated integration test, configure these env variables locally:
SOLVERIT_MCP_RESOURCE_URL, SOLVERIT_OAUTH_ISSUER_URL,
SOLVERIT_OAUTH_JWKS_URI, SOLVERIT_MCP_SUBJECTS. Start only the candidate
`mcp_sdk_pilot.py` in a non-production session. With a valid token, check
the standard MCP `initialize` handshake and `tools/list` empty result.
With missing/invalid tokens, expect HTTP 401. Check OAuth protected resource
metadata via the SDK's discovery route. Test the allowed subject, scope,
audience and token expiry against the real Keycloak before any public cutover.

Do not merge, expose write tools, restart the audit MCP, or change the Caddy
reverse proxy as part of these offline checks.
