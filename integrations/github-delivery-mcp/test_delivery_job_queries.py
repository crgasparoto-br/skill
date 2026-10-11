"""Regression tests for identity-bound, read-only delivery job retrieval."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from delivery_job_queries import get_authorized_job_status
from jobs import JobStore
from policy import PolicyDeniedError, VerifiedPrincipal


class JobQueryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "jobs.sqlite3")
        self.store = JobStore(self.database)
        self.owner = VerifiedPrincipal("allowed-user", frozenset({"entregar-issue"}), True)
        self.other = VerifiedPrincipal("different-user", frozenset({"entregar-issue"}), True)
        self.job = self.store.create(
            actor="allowed-user", key="k1", payload_hash=hashlib.sha256(b"job").hexdigest(),
            repo="crgasparoto-br/training-system", issue_number=499,
            branch="feat/499-example", base_sha="a" * 40, expected_head="a" * 40,
        )

    def query(self, principal, **changes):
        args = dict(
            database_path=self.database, job_id=self.job.job_id, principal=principal,
            allowed_subjects=frozenset({"allowed-user", "different-user"}),
            allowed_repositories=frozenset({"crgasparoto-br/training-system"}),
        )
        args.update(changes)
        return get_authorized_job_status(**args)

    def test_owner_reads_only_safe_fields(self):
        result = self.query(self.owner)
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["issue_number"], 499)
        self.assertNotIn("actor", result)
        self.assertNotIn("idempotency_key", result)
        self.assertNotIn("payload_hash", result)

    def test_other_user_cannot_read_job(self):
        with self.assertRaises(KeyError):
            self.query(self.other)

    def test_missing_delivery_profile_denied(self):
        with self.assertRaises(PolicyDeniedError):
            self.query(VerifiedPrincipal("allowed-user", frozenset(), True))

    def test_unverified_identity_denied(self):
        with self.assertRaises(PolicyDeniedError):
            self.query(VerifiedPrincipal("allowed-user", frozenset({"entregar-issue"}), False))

    def test_unlisted_repository_denied(self):
        with self.assertRaises(PolicyDeniedError):
            self.query(self.owner, allowed_repositories=frozenset())

    def test_invalid_job_id_denied(self):
        with self.assertRaises(PolicyDeniedError):
            self.query(self.owner, job_id="' OR 1=1--")

    def test_missing_database_does_not_create_file(self):
        missing = str(Path(self.directory.name) / "missing.sqlite3")
        with self.assertRaises(FileNotFoundError):
            self.query(self.owner, database_path=missing)
        self.assertFalse(Path(missing).exists())
