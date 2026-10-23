"""Controller check execution records observed outcomes, not client assertions."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_evidence import CheckEvidenceStore
from verified_check_runner import run_and_record_checks


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.database = str(Path(self.tmp.name) / "jobs.sqlite3")
        self.store = CheckEvidenceStore(self.database)
        job = self.store.jobs.create(actor="operator", key="run-1",
            payload_hash=hashlib.sha256(b"job").hexdigest(),
            repo="crgasparoto-br/skill", issue_number=88,
            branch="feat/88-test", base_sha="a"*40, expected_head="a"*40)
        self.job_id = job.job_id
        self.args = {"database_path": self.database, "job_id": job.job_id,
                         "actor": "operator", "snapshot_dir": "/trusted/snapshot"}

    def prepare(self):
        self.store.jobs.transition(self.job_id, "operator", "queued", "running")
        self.store.jobs.transition(self.job_id, "operator", "running", "prepared")

    def test_worker_identity_required(self):
        self.prepare()
        with patch("verified_check_runner.os.geteuid", return_value=1000), self.assertRaises(PermissionError):
            run_and_record_checks(**self.args)

    def test_success_is_durable_but_not_delivery_success(self):
        self.prepare()
        with patch("verified_check_runner.os.geteuid", return_value=1004), patch(
                "verified_check_runner.inspect_workspace_in_container", return_value=True) as run:
            result = run_and_record_checks(**self.args)
            self.assertEqual(len(result), 3)
            self.assertEqual(run.call_count, 3)
        self.assertEqual(self.store.jobs.read(self.job_id, "operator").status, "prepared")
        CheckEvidenceStore(self.database).require_checks(self.job_id, "operator")
        with patch("verified_check_runner.os.geteuid", return_value=1004), self.assertRaises(PermissionError):
            run_and_record_checks(**self.args)

    def test_failed_check_is_recorded_and_blocks_gate(self):
        self.prepare()
        with patch("verified_check_runner.os.geteuid", return_value=1004), patch(
                "verified_check_runner.inspect_workspace_in_container",
                side_effect=[True, RuntimeError("container failed")]) as run:
            with self.assertRaises(RuntimeError):
                run_and_record_checks(**self.args)
            self.assertEqual(run.call_count, 2)
        results = self.store.list_for_owner(self.job_id, "operator")
        self.assertEqual(len(results), 2)
        self.assertFalse(results[-1].passed)
        with self.assertRaises(PermissionError):
            self.store.require_checks(self.job_id, "operator")

    def test_unprepared_job_denied_without_execution(self):
        with patch("verified_check_runner.os.geteuid", return_value=1004), patch(
                "verified_check_runner.inspect_workspace_in_container") as run:
            with self.assertRaises(PermissionError):
                run_and_record_checks(**self.args)
            run.assert_not_called()

    def test_actor_isolation(self):
        self.prepare()
        with patch("verified_check_runner.os.geteuid", return_value=1004), self.assertRaises(KeyError):
            run_and_record_checks(**(self.args | {"actor": "stranger"}))
