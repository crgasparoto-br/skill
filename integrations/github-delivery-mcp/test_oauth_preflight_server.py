"""No-network authorization preflight tests."""
import unittest
from unittest.mock import patch

from oauth_preflight_server import authorize_http_request
from policy import PolicyDeniedError, VerifiedPrincipal

VALID = {"action": "prepare_workspace",
         "repository": "crgasparoto-br/training-system",
         "branch": "feat/88-controlled-issue-delivery",
         "expected_head": "a" * 40}



class PreflightTests(unittest.TestCase):
    def test_valid_request(self):
        with patch("oauth_preflight_server.verify_github_user_token",
                   return_value=VerifiedPrincipal("github:123", frozenset({"entregar-issue"}), True)):
            result = authorize_http_request("opaque-bearer", VALID, frozenset({123}))
        self.assertEqual(result.subject, "github:123")

    def test_unverified_identity_rejected(self):
        with patch("oauth_preflight_server.verify_github_user_token",
                   return_value=VerifiedPrincipal("github:123", frozenset({"entregar-issue"}), False)):
            with self.assertRaises(PolicyDeniedError):
                authorize_http_request("opaque-bearer", VALID, frozenset({123}))

    def test_write_operation_disabled(self):
        payload = {**VALID, "action": "open_pull_request"}
        with patch("oauth_preflight_server.verify_github_user_token") as verify, self.assertRaises(PolicyDeniedError):
            authorize_http_request("opaque-bearer", payload, frozenset({123}))
        verify.assert_not_called()

    def test_client_cannot_inject_principal(self):
        with self.assertRaises(ValueError):
            authorize_http_request("opaque-bearer", {**VALID, "oauth_verified": True}, frozenset({123}))

    def test_other_repository_rejected(self):
        with patch("oauth_preflight_server.verify_github_user_token",
                   return_value=VerifiedPrincipal("github:123", frozenset({"entregar-issue"}), True)):
            with self.assertRaises(PolicyDeniedError):
                authorize_http_request("opaque-bearer", {**VALID, "repository": "crgasparoto-br/solverfin"}, frozenset({123}))

    def test_other_user_rejected(self):
        with patch("oauth_preflight_server.verify_github_user_token",
                   return_value=VerifiedPrincipal("github:456", frozenset({"entregar-issue"}), True)):
            with self.assertRaises(PolicyDeniedError):
                authorize_http_request("opaque-bearer", VALID, frozenset({123}))

if __name__ == "__main__":
    unittest.main()
