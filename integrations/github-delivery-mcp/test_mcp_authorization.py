"""Tests of server-side MCP authorization decisions. No live OAuth/GitHub."""
import unittest

from policy import PolicyDenied, VerifiedPrincipal
from mcp_authorization import authorize_operation, authorize_token_operation

SHA = "a" * 40
REPO = "crgasparoto-br/training-system"
BRANCH = "feat/88-controlled-issue-delivery"

class MCPAuthorizationTests(unittest.TestCase):
    def allowed(self, principal=None, action="prepare_workspace", repository=REPO):
        if principal is None:
            principal = VerifiedPrincipal("github:12345",
                frozenset({"entregar-issue"}), True)
        return authorize_operation(
            principal=principal, action=action, repository=repository,
            branch=BRANCH, expected_head=SHA,
            allowed_subjects=frozenset({"github:12345"}))

    def test_verified_allowed_identity(self):
        decision = self.allowed()
        self.assertEqual(decision.subject, "github:12345")
        authorize_token_operation(decision, requested_operation="read-issue")

    def test_unverified_oauth_denied(self):
        with self.assertRaises(PolicyDenied):
            self.allowed(VerifiedPrincipal("github:12345",
                         frozenset({"entregar-issue"}), False))

    def test_other_user_denied(self):
        with self.assertRaises(PolicyDenied):
            self.allowed(VerifiedPrincipal("github:999",
                         frozenset({"entregar-issue"}), True))

    def test_missing_profile_denied(self):
        with self.assertRaises(PolicyDenied):
            self.allowed(VerifiedPrincipal("github:12345", frozenset(), True))

    def test_unlisted_repository_denied(self):
        with self.assertRaises(PolicyDenied):
            self.allowed(repository="crgasparoto-br/solverfin")

    def test_read_decision_cannot_grant_write_token(self):
        decision = self.allowed()
        with self.assertRaises(PolicyDenied):
            authorize_token_operation(decision, requested_operation="publish-pr")

    def test_empty_allowlist_denied(self):
        with self.assertRaises(PolicyDenied):
            authorize_operation(
                principal=VerifiedPrincipal("github:12345",
                    frozenset({"entregar-issue"}), True),
                action="prepare_workspace", repository=REPO,
                branch=BRANCH, expected_head=SHA,
                allowed_subjects=frozenset())

if __name__ == "__main__":
    unittest.main()
