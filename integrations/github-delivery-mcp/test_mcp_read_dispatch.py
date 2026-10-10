"""No-network tests for stateless read-only MCP dispatcher."""
import unittest
from unittest.mock import patch
from policy import VerifiedPrincipal
from mcp_read_dispatch import dispatch, VERSION, META_VERSION

META = {META_VERSION: VERSION}
ARGS = {"repository": "crgasparoto-br/training-system",
        "branch": "feat/88-controlled-issue-delivery", "expected_head": "a" * 40}

def rpc(method="tools/call", args=ARGS):
    return {"jsonrpc": "2.0", "id": 1, "method": method,
            "params": {"_meta": META, "name": "solverit_authorize_read",
                       "arguments": args} if method == "tools/call" else {"_meta": META}}

def call(req=None, bearer="sample-valid-token", version=VERSION, method="tools/call",
         name="solverit_authorize_read"):
    return dispatch(req or rpc(), protocol_header=version, method_header=method,
                    name_header=name, bearer=bearer, allowed_ids=frozenset({123}))

class MCPReadTests(unittest.TestCase):
    def test_missing_bearer_denied(self):
        with patch("mcp_read_dispatch.authorize_http_request") as auth:
            self.assertEqual(call(bearer="").http_status, 401)
            auth.assert_not_called()

    def test_whitespace_bearer_denied_before_authorization(self):
        with patch("mcp_read_dispatch.authorize_http_request") as auth:
            self.assertEqual(call(bearer="   ").http_status, 401)
            auth.assert_not_called()

    def test_mismatched_version_denied(self):
        with patch("mcp_read_dispatch.authorize_http_request") as auth:
            self.assertEqual(call(version="2025-11-25").http_status, 400)
            auth.assert_not_called()

    def test_header_mismatch_denied(self):
        self.assertEqual(call(name="unexpected").http_status, 404)

    def test_forbidden_write_method_denied(self):
        self.assertEqual(call(rpc(method="tools/publish"), method="tools/publish", name=None).http_status, 404)

    def test_extra_arguments_denied(self):
        self.assertEqual(call(rpc(args={**ARGS, "oauth_verified": True})).http_status, 400)

    def test_authorized_preflight_does_not_run_jobs(self):
        with patch("mcp_read_dispatch.authorize_http_request") as auth:
            response = call()
        self.assertEqual(response.http_status, 200)
        auth.assert_called_once()
        self.assertIn("no job started", response.payload["result"]["content"][0]["text"])

    def test_tools_list_requires_identity(self):
        with patch("github_oauth_identity.verify_github_user_token",
                   return_value=VerifiedPrincipal("github:123", frozenset({"entregar-issue"}), True)):
            response = call(rpc(method="tools/list"), method="tools/list", name=None)
        self.assertEqual(response.http_status, 200)
        self.assertEqual(len(response.payload["result"]["tools"]), 1)

if __name__ == "__main__":
    unittest.main()
