"""No-execution, authorization and idempotency tests for enqueue boundary."""
import tempfile
import unittest
from pathlib import Path

from delivery_job_submission import enqueue_prepare_workspace
from jobs import JobConflictError
from policy import PolicyDeniedError, VerifiedPrincipal


class EnqueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "jobs.db")
        self.owner = VerifiedPrincipal("allowed", frozenset({"entregar-issue"}), True)
        self.params = {
            "database_path": self.database, "principal": self.owner,
            "allowed_subjects": frozenset({"allowed"}),
            "allowed_repositories": frozenset({"crgasparoto-br/training-system"}),
            "repository": "crgasparoto-br/training-system", "issue_number": 499,
            "base_sha": "a" * 40, "idempotency_key": "attempt-1",
        }

    def test_authorized_enqueue_is_queued_not_executed(self):
        job = enqueue_prepare_workspace(**self.params)
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["branch"], "feat/499-delivery")
        self.assertEqual(job["base_sha"], "a" * 40)

    def test_idempotency_no_duplicate(self):
        first = enqueue_prepare_workspace(**self.params)
        second = enqueue_prepare_workspace(**self.params)
        self.assertEqual(first["job_id"], second["job_id"])

    def test_reused_key_other_issue_conflicts(self):
        enqueue_prepare_workspace(**self.params)
        with self.assertRaises(JobConflictError):
            enqueue_prepare_workspace(**(self.params | {"issue_number": 500}))

    def test_unverified_cannot_create_store(self):
        with self.assertRaises(PolicyDeniedError):
            enqueue_prepare_workspace(**(self.params | {
                "principal": VerifiedPrincipal("allowed", frozenset({"entregar-issue"}), False)
            }))
        self.assertFalse(Path(self.database).exists())

    def test_profile_missing_denied(self):
        with self.assertRaises(PolicyDeniedError):
            enqueue_prepare_workspace(**(self.params | {
                "principal": VerifiedPrincipal("allowed", frozenset(), True)
            }))

    def test_repository_denied(self):
        with self.assertRaises(PolicyDeniedError):
            enqueue_prepare_workspace(**(self.params | {"repository": "other/other"}))

    def test_invalid_issue_and_head_denied(self):
        for issue in (-1, 0, True):
            with self.subTest(issue=issue), self.assertRaises(PolicyDeniedError):
                enqueue_prepare_workspace(**(self.params | {"issue_number": issue}))
        with self.assertRaises(PolicyDeniedError):
            enqueue_prepare_workspace(**(self.params | {"base_sha": "not-a-sha"}))
