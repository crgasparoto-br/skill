"""Offline recovery tests; no real Docker or GitHub calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from jobs import JobStore
from local_recovery import recover_local_jobs


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / "jobs.sqlite3")
        self.store = JobStore(self.path)
        self.job = self.store.create(
            actor="local-smoke-operator", key="recover-one", payload_hash="a" * 64,
            repo="crgasparoto-br/training-system", issue_number=88, branch="develop",
            base_sha="offline", expected_head="offline",
        )
        self.store.transition(self.job.job_id, "local-smoke-operator", "queued", "running")

    def tearDown(self):
        self.temp.cleanup()

    def _state(self):
        return self.store.read(self.job.job_id, "local-smoke-operator").status

    def test_cleanup_before_marking_timed_out(self):
        name = "solverit-issue88-" + "a" * 32
        with patch("local_recovery.os.geteuid", return_value=1004), \
             patch("local_recovery.Path.exists", return_value=True), \
             patch("local_recovery.subprocess.run", side_effect=[
                 Mock(stdout=name + "\n"), Mock(stdout="")
             ]), patch("local_recovery.cleanup_container") as cleanup:
            recovered = recover_local_jobs(self.path)
        self.assertEqual(recovered, 1)
        cleanup.assert_called_once()
        self.assertEqual(self._state(), "timed_out")

    def test_failed_cleanup_preserves_running_state(self):
        name = "solverit-issue88-" + "b" * 32
        with patch("local_recovery.os.geteuid", return_value=1004), \
             patch("local_recovery.Path.exists", return_value=True), \
             patch("local_recovery.subprocess.run", return_value=Mock(stdout=name + "\n")), \
             patch("local_recovery.cleanup_container", side_effect=RuntimeError("cleanup failed")), self.assertRaises(RuntimeError):
            recover_local_jobs(self.path)
        self.assertEqual(self._state(), "running")

    def test_enumeration_error_preserves_running_state(self):
        import subprocess
        with patch("local_recovery.os.geteuid", return_value=1004), \
             patch("local_recovery.Path.exists", return_value=True), \
             patch("local_recovery.subprocess.run", side_effect=subprocess.CalledProcessError(1, "docker")), self.assertRaises(subprocess.CalledProcessError):
            recover_local_jobs(self.path)
        self.assertEqual(self._state(), "running")

    def test_invalid_identity_denied(self):
        with patch("local_recovery.os.geteuid", return_value=0), self.assertRaises(PermissionError):
                recover_local_jobs(self.path)
        self.assertEqual(self._state(), "running")

if __name__ == "__main__":
    unittest.main()
