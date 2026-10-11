"""Intake cannot trust a caller-supplied branch SHA or unauthenticated principal."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from policy import PolicyDeniedError, VerifiedPrincipal
from trusted_workspace_intake import intake_prepare_workspace


class TrustedWorkspaceIntakeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "jobs.db")
        self.resolve = Mock(return_value="a" * 40)
        self.params = dict(
            database_path=self.database,
            principal=VerifiedPrincipal("operator", frozenset({"entregar-issue"}), True),
            allowed_subjects=frozenset({"operator"}),
            allowed_repositories=frozenset({"crgasparoto-br/training-system"}),
            repository="crgasparoto-br/training-system",
            issue_number=499, idempotency_key="request-499",
            trusted_develop_head=self.resolve,
        )

    def test_accepted_request_resolves_develop_and_queues(self):
        result = intake_prepare_workspace(**self.params)
        self.assertEqual(result["base_sha"], "a" * 40)
        self.assertEqual(result["status"], "queued")
        self.resolve.assert_called_once_with("crgasparoto-br/training-system")

    def test_unverified_identity_denied_before_network(self):
        with self.assertRaises(PolicyDeniedError):
            intake_prepare_workspace(**(self.params | {
                "principal": VerifiedPrincipal("operator", frozenset({"entregar-issue"}), False)
            }))
        self.resolve.assert_not_called()

    def test_other_repo_denied_before_network(self):
        with self.assertRaises(PolicyDeniedError):
            intake_prepare_workspace(**(self.params | {"repository": "unlisted/repo"}))
        self.resolve.assert_not_called()

    def test_invalid_resolved_sha_denied(self):
        self.resolve.return_value = "branch-name-instead-of-sha"
        with self.assertRaises(PolicyDeniedError):
            intake_prepare_workspace(**self.params)
        self.assertFalse(Path(self.database).exists())

    def test_resolver_failure_does_not_create_job(self):
        self.resolve.side_effect = RuntimeError("github unavailable")
        with self.assertRaises(RuntimeError):
            intake_prepare_workspace(**self.params)
        self.assertFalse(Path(self.database).exists())

    def test_missing_resolver_denied(self):
        with self.assertRaises(PolicyDeniedError):
            intake_prepare_workspace(**(self.params | {"trusted_develop_head": None}))
