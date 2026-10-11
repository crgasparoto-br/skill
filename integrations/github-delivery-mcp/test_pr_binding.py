"""Binding is durable, immutable, actor-scoped, and never marks success."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from jobs import JobConflictError, JobStore
from pr_binding import PRBindingStore


class PRBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "jobs.sqlite3")
        self.jobs = JobStore(self.db)
        self.job = self.jobs.create(
            actor="authorized", key="attempt", payload_hash=hashlib.sha256(b"x").hexdigest(),
            repo="crgasparoto-br/skill", issue_number=88,
            branch="feat/88-delivery", base_sha="a"*40, expected_head="b"*40,
        )
        self.store = PRBindingStore(self.db)
        self.args = dict(job_id=self.job.job_id, actor="authorized",
                         pr_number=89, head_sha="b"*40)

    def prepare(self):
        self.jobs.transition(self.job.job_id, "authorized", "queued", "running")
        self.jobs.transition(self.job.job_id, "authorized", "running", "prepared")

    def test_binding_requires_prepared(self):
        with self.assertRaises(JobConflictError):
            self.store.bind_published_pr(**self.args)

    def test_persists_without_delivery_success(self):
        self.prepare()
        first = self.store.bind_published_pr(**self.args)
        self.assertEqual(first, self.store.bind_published_pr(**self.args))
        self.assertEqual(first, PRBindingStore(self.db).read(
            job_id=self.job.job_id, actor="authorized"))
        self.assertEqual(self.jobs.read(self.job.job_id, "authorized").status, "prepared")

    def test_other_actor_denied(self):
        self.prepare()
        with self.assertRaises(KeyError):
            self.store.bind_published_pr(**(self.args | {"actor": "other"}))

    def test_stale_sha_denied(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.store.bind_published_pr(**(self.args | {"head_sha": "a"*40}))

    def test_conflicting_rebinding_denied(self):
        self.prepare()
        self.store.bind_published_pr(**self.args)
        with self.assertRaises(JobConflictError):
            self.store.bind_published_pr(**(self.args | {"pr_number": 90}))
