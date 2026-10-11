"""No caller-supplied claim may finalize a delivery."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from jobs import JobStore
from delivery_finalization import DeliveryNotVerified, require_verified_delivery


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "jobs.sqlite3")
        self.jobs = JobStore(self.db)
        self.job = self.jobs.create(
            actor="operator", key="attempt", payload_hash=hashlib.sha256(b"x").hexdigest(),
            repo="crgasparoto-br/skill", issue_number=88,
            branch="feat/88-controlled-delivery", base_sha="a"*40,
            expected_head="a"*40,
        )

    def test_queued_denied(self):
        with self.assertRaises(DeliveryNotVerified):
            require_verified_delivery(self.db, job_id=self.job.job_id, actor="operator")

    def test_prepared_still_denied_without_external_evidence(self):
        self.jobs.transition(self.job.job_id, "operator", "queued", "running")
        self.jobs.transition(self.job.job_id, "operator", "running", "prepared")
        with self.assertRaisesRegex(DeliveryNotVerified, "independent audit"):
            require_verified_delivery(self.db, job_id=self.job.job_id, actor="operator")
        self.assertEqual(self.jobs.read(self.job.job_id, "operator").status, "prepared")

    def test_other_actor_denied(self):
        with self.assertRaises(KeyError):
            require_verified_delivery(self.db, job_id=self.job.job_id, actor="intruder")
