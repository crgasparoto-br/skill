"""Offline integration tests for state transitions; never starts Docker."""
import os
import tempfile
import unittest
from unittest.mock import patch
from offline_executor import CheckResult
from jobs import JobStore
from local_job_runner import submit_offline_smoke

class LocalJobRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "jobs.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_success_and_no_replay(self):
        with patch("local_job_runner.run_allowed_check",
                   return_value=CheckResult("smoke-v1", 0, "CHECK_OK\n", "", False)) as execute:
            first = submit_offline_smoke(self.path, actor="local-smoke-operator", idempotency_key="run1")
            again = submit_offline_smoke(self.path, actor="local-smoke-operator", idempotency_key="run1")
        self.assertEqual(first.status, "succeeded")
        self.assertEqual(first.job_id, again.job_id)
        execute.assert_called_once()
        self.assertEqual(JobStore(self.path).read(first.job_id, "local-smoke-operator").status, "succeeded")

    def test_failure_persisted(self):
        with patch("local_job_runner.run_allowed_check", side_effect=RuntimeError("cleanup")):
            result = submit_offline_smoke(self.path, actor="local-smoke-operator", idempotency_key="run2")
        self.assertEqual(result.status, "failed")
        self.assertEqual(JobStore(self.path).read(result.job_id, "local-smoke-operator").status, "failed")

    def test_wrong_actor_rejected(self):
        with self.assertRaises(PermissionError):
            submit_offline_smoke(self.path, actor="external", idempotency_key="run3")

if __name__ == "__main__":
    unittest.main()
