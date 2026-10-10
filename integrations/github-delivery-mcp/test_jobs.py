"""Credential-free tests of durable job state and actor isolation."""
import hashlib
import os
import tempfile
import unittest

from jobs import JobConflictError, JobStore

SHA = "a" * 40
DIGEST = hashlib.sha256(b"request").hexdigest()


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = os.path.join(self.temp.name, "jobs.sqlite3")
        self.store = JobStore(self.path)

    def create(self, **overrides):
        args = dict(actor="trusted", key="attempt-1", payload_hash=DIGEST,
                    repo="crgasparoto-br/training-system", issue_number=88,
                    branch="feat/88-controlled-delivery", base_sha=SHA,
                    expected_head=SHA)
        args.update(overrides)
        return self.store.create(**args)

    def test_idempotent_and_durable(self):
        job = self.create()
        self.assertEqual(self.create().job_id, job.job_id)
        self.assertEqual(JobStore(self.path).read(job.job_id, "trusted"), job)
        with self.assertRaises(JobConflictError):
            self.create(payload_hash="b" * 64)

    def test_actor_isolation(self):
        job = self.create()
        with self.assertRaises(KeyError):
            self.store.read(job.job_id, "stranger")
        with self.assertRaises(JobConflictError):
            self.store.transition(job.job_id, "stranger", "queued", "running")

    def test_transitions_and_recovery(self):
        job = self.create()
        self.store.transition(job.job_id, "trusted", "queued", "running")
        self.assertEqual(JobStore(self.path).recover_interrupted(), 1)
        self.assertEqual(self.store.read(job.job_id, "trusted").status, "timed_out")
        with self.assertRaises(JobConflictError):
            self.store.transition(job.job_id, "trusted", "running", "succeeded")
        self.store.transition(job.job_id, "trusted", "timed_out", "queued")
        self.store.transition(job.job_id, "trusted", "queued", "running")
        self.store.transition(job.job_id, "trusted", "running", "succeeded")
        with self.assertRaises(JobConflictError):
            self.store.transition(job.job_id, "trusted", "succeeded", "queued")


if __name__ == "__main__":
    unittest.main()
