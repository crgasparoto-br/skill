"""Offline behavior tests only; do not certify production lifecycle."""
import unittest
from unittest.mock import patch

import operational_check as ops


class OperationalCheckTests(unittest.TestCase):
    def test_baseline_fails_when_any_identity_check_fails(self):
        with patch.object(ops, "probe", return_value={"authorized_develop": True, "unauthorized_tools_hidden": False}):
            result = ops.run_phase("https://example.test/mcp", "owner/repo", "new", "denied", "baseline")
        self.assertEqual(result["result"], "NOT_VALIDATED")

    def test_restart_requires_both_live_identities(self):
        with patch.object(ops, "probe", return_value={"authorized_develop": True, "unauthorized_tools_hidden": True}):
            result = ops.run_phase("https://example.test/mcp", "owner/repo", "new", "denied", "post-restart")
        self.assertEqual(result["result"], "PASS")
        self.assertIn("operator", result["operator_confirmation_required"].lower() + " operator")

    def test_expiry_requires_distinct_retired_token(self):
        with self.assertRaises(ValueError):
            ops.run_phase("https://example.test/mcp", "owner/repo", "new", "denied", "post-expiry")
        with self.assertRaises(ValueError):
            ops.run_phase("https://example.test/mcp", "owner/repo", "new", "denied", "post-rotation", "new")

    def test_retired_token_must_fail_at_transport_layer(self):
        with patch.object(ops, "probe", return_value={"authorized_develop": True}), \
             patch.object(ops, "rpc", return_value={"error": {"code": -32603}}):
            result = ops.run_phase("https://example.test/mcp", "owner/repo", "new", "denied", "post-expiry", "old")
        self.assertEqual(result["result"], "NOT_VALIDATED")
        self.assertFalse(result["checks"]["retired_session_transport_denied"])

    def test_retired_token_401_and_authorized_sessions_pass(self):
        with patch.object(ops, "probe", return_value={"authorized_develop": True, "unauthorized_tools_hidden": True}), \
             patch.object(ops, "rpc", return_value={"denied": True}):
            result = ops.run_phase("https://example.test/mcp", "owner/repo", "new", "denied", "post-rotation", "old")
        self.assertEqual(result["result"], "PASS")
        self.assertNotIn("old", str(result))
        self.assertNotIn("new", str(result))


if __name__ == "__main__":
    unittest.main()
