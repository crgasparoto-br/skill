"""Offline, credential-free regression tests for delivery authorization."""
import unittest

from policy import DeliveryPolicy, PolicyDeniedError, VerifiedPrincipal, require_unchanged_head

SHA = "a" * 40
POLICY = DeliveryPolicy(
    allowed_users=frozenset({"trusted-user"}),
    allowed_repos=frozenset({"crgasparoto-br/training-system"}),
)
WRITER = VerifiedPrincipal("trusted-user", frozenset({"entregar-issue"}), True)


class AuthorizationTests(unittest.TestCase):
    def call(self, **overrides):
        args = dict(
            principal=WRITER, action="apply_patch",
            repo="crgasparoto-br/training-system",
            branch="feat/88-controlled-delivery", expected_head=SHA,
            path="src/example.py", size=12,
        )
        args.update(overrides)
        POLICY.authorize(**args)

    def test_allowed(self):
        self.call()

    def test_unverified_or_missing_identity(self):
        for principal in (
            None,
            VerifiedPrincipal("trusted-user", frozenset({"entregar-issue"}), False),
            VerifiedPrincipal("stranger", frozenset({"entregar-issue"}), True),
            VerifiedPrincipal("trusted-user", frozenset({"auditar-issue"}), True),
        ):
            with self.subTest(principal=principal), self.assertRaises(PolicyDeniedError):
                self.call(principal=principal)

    def test_prohibited_repo_and_operations(self):
        for change in (
            {"repo": "crgasparoto-br/skill"},
            {"repo": "../training-system"},
            {"action": "merge"},
            {"action": "delete_branch"},
            {"action": "force_push"},
            {"action": "run_shell"},
        ):
            with self.subTest(change=change), self.assertRaises(PolicyDeniedError):
                self.call(**change)

    def test_protected_branches(self):
        for branch in ("main", "develop", "refs/heads/main", "feat/../../main", "fix/88"):
            with self.subTest(branch=branch), self.assertRaises(PolicyDeniedError):
                self.call(branch=branch)

    def test_prohibited_paths(self):
        for path in (
            "../x", "/etc/passwd", "src/../.env", ".github/workflows/ci.yml",
            "src\\evil", "secrets/key.txt", "cert.pem", ".npmrc", "src//file.py",
        ):
            with self.subTest(path=path), self.assertRaises(PolicyDeniedError):
                self.call(path=path)

    def test_invalid_sha_and_content_size(self):
        for head in (None, "", "other", "B" * 40):
            with self.subTest(head=head), self.assertRaises(PolicyDeniedError):
                self.call(expected_head=head)
        with self.assertRaises(PolicyDeniedError):
            self.call(size=262145)

    def test_concurrent_update(self):
        require_unchanged_head(SHA, SHA)
        with self.assertRaises(PolicyDeniedError):
            require_unchanged_head(SHA, "b" * 40)


if __name__ == "__main__":
    unittest.main()
