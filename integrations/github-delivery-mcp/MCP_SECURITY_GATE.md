# Issue #88: MCP pilot security gate

This is a **read-only, loopback-only pilot**, not a production MCP server or OAuth login flow.
The actual MCP request handler currently advertises **zero tools**. It cannot deliver
issues, publish GitHub branches/PRs, or execute worker jobs.

## Mandatory checks on each PR

The GitHub Actions workflow `.github/workflows/issue88-mcp-security.yml`
runs actual HTTP socket tests, JSON-RPC discovery checks, OAuth protected-resource
discovery, cryptographic signed-JWT tests and HTTP framing regression tests.

For local verification (Python 3.12, isolated virtual environment):

```sh
python3 -m venv /tmp/solverit-issue88-mcp-ci
/tmp/solverit-issue88-mcp-ci/bin/python -m pip install -r integrations/github-delivery-mcp/requirements-jwt.txt
(cd integrations/github-delivery-mcp && /tmp/solverit-issue88-mcp-ci/bin/python -B -m unittest -v \
  test_mcp_http_local test_mcp_http_boundary test_mcp_http_real_negative \
  test_mcp_oauth_discovery_http test_mcp_http_signed_jwt \
  test_mcp_jwt_verifier test_oauth_resource_metadata \
  test_mcp_http_framing test_mcp_independent_wire_client)
```

Do not expose port 8769 publicly or give the worker access to the GitHub App PEM.
The signature verifier uses a pinned RSA public key; tests generate throwaway keys.

## Pending gates before production

1. Test with an independently maintained MCP SDK/client and resolve any protocol gaps.
2. Establish a compliant authorization server, including discovery and token issuance.
3. Verify audience and scope for every operation; make the end-user identity non-forgeable.
4. Tie tool requests to an authenticated, allowlisted job; perform write actions only through
   the separated GitHub App auth broker with explicit repository/branch/head constraints.
5. Run confinement and recovery tests against the actual rootless worker.
6. Require green checks on the **exact PR HEAD** plus independent issue/PR audit.
7. Obtain explicit approval before merging or enabling production writes.

**Passing the pilot suite does not satisfy these production gates.**
