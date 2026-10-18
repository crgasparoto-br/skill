"""Evidence persistence, immutability, actor separation and fail-closed gate."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from check_evidence import _CHECKS, _IMAGES, CheckEvidenceStore


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "jobs.sqlite3")
        self.store = CheckEvidenceStore(self.path)
        self.job = self.store.jobs.create(
            actor="operator", key="one", payload_hash=hashlib.sha256(b"one").hexdigest(),
            repo="crgasparoto-br/skill", issue_number=88,
            branch="feat/88-delivery", base_sha="a" * 40, expected_head="a" * 40)
        self.kwargs = dict(job_id=self.job.job_id, actor="operator",
                           base_sha="a" * 40)

    def prepare(self):
        self.store.jobs.transition(self.job.job_id, "operator", "queued", "running")
        self.store.jobs.transition(self.job.job_id, "operator", "running", "prepared")

    def record(self, check, **overrides):
        kw = dict(self.kwargs, check=check, image=_IMAGES[check], passed=True)
        kw.update(overrides)
        return self.store.record(**kw)

    def test_cannot_record_until_prepared(self):
        with self.assertRaises(PermissionError):
            self.record("integrity-v1")

    def test_cannot_publish_with_missing_or_failed_checks(self):
        self.prepare()
        with self.assertRaises(PermissionError):
            self.store.require_checks(self.job.job_id, "operator")
        self.record("integrity-v1", passed=False)
        for check in _CHECKS - {"integrity-v1"}:
            self.record(check)
        with self.assertRaises(PermissionError):
            self.store.require_checks(self.job.job_id, "operator")

    def test_evidence_persists_across_restart(self):
        self.prepare()
        for check in _CHECKS:
            self.record(check)
        reopened = CheckEvidenceStore(self.path)
        reopened.require_checks(self.job.job_id, "operator")
        self.assertEqual(len(reopened.list_for_owner(self.job.job_id, "operator")), 3)

    def test_immutable_and_actor_isolation(self):
        self.prepare()
        self.record("integrity-v1")
        with self.assertRaises(PermissionError):
            self.record("integrity-v1", passed=False)
        with self.assertRaises(KeyError):
            self.store.list_for_owner(self.job.job_id, "stranger")
        with self.assertRaises(KeyError):
            self.store.record(**(self.kwargs | {"actor":"stranger",
                "check":"posix-shell-syntax-v1", "image":_IMAGES["posix-shell-syntax-v1"],
                "passed":True}))

    def test_wrong_sha_image_and_timeout_denied(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.record("integrity-v1", base_sha="b" * 40)
        with self.assertRaises(ValueError):
            self.record("integrity-v1", image="alpine:latest")
        with self.assertRaises(ValueError):
            self.record("integrity-v1", passed=True, timed_out=True)
