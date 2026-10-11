"""Credential-free tests of durable job state and actor isolation."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from jobs import JobConflictError, JobStore

SHA = "a" * 40
DIGEST = hashlib.sha256(b"request").hexdigest()


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "jobs.sqlite3")
        self.store = JobStore(self.path)

    def create(self, **overrides):
        args = {"actor": "trusted", "key": "attempt-1", "payload_hash": DIGEST,
                "repo": "crgasparoto-br/training-system", "issue_number": 88,
                "branch": "feat/88-controlled-delivery", "base_sha": SHA,
                "expected_head": SHA}
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

    def test_prepared_workspace_is_not_terminal_success(self):
        job = self.create()
        self.store.transition(job.job_id, "trusted", "queued", "running")
        self.store.transition(job.job_id, "trusted", "running", "prepared")
        reopened = JobStore(self.path)
        self.assertEqual(reopened.read(job.job_id, "trusted").status, "prepared")
        self.assertEqual(reopened.recover_interrupted(), 0)
        with self.assertRaises(JobConflictError):
            reopened.transition(job.job_id, "trusted", "prepared", "succeeded")
        reopened.transition(job.job_id, "trusted", "prepared", "running")
        reopened.transition(job.job_id, "trusted", "running", "failed")

    def test_legacy_smoke_still_can_finish(self):
        job = self.create(base_sha="offline-smoke-no-repo-operation",
                          expected_head="offline-smoke-no-repo-operation")
        self.store.transition(job.job_id, "trusted", "queued", "running")
        self.store.transition(job.job_id, "trusted", "running", "succeeded")
        self.assertEqual(self.store.read(job.job_id, "trusted").status, "succeeded")

    def test_transitions_and_recovery(self):
        job = self.create()
        self.store.transition(job.job_id, "trusted", "queued", "running")
        self.assertEqual(JobStore(self.path).recover_interrupted(), 1)
        self.assertEqual(self.store.read(job.job_id, "trusted").status, "timed_out")
        with self.assertRaises(JobConflictError):
            self.store.transition(job.job_id, "trusted", "running", "succeeded")
        self.store.transition(job.job_id, "trusted", "timed_out", "queued")
        self.store.transition(job.job_id, "trusted", "queued", "running")
        with self.assertRaises(JobConflictError):
            self.store.transition(job.job_id, "trusted", "running", "succeeded")
        self.store.transition(job.job_id, "trusted", "running", "failed")


if __name__ == "__main__":
    unittest.main()
