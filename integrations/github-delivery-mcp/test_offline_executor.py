"""Unit tests for fixed offline execution contract (no Docker required)."""
import unittest
from unittest.mock import patch, Mock
import offline_executor as executor

class OfflineExecutorTests(unittest.TestCase):
    def test_rejects_unlisted_check_before_side_effects(self):
        with patch.object(executor.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                executor.run_allowed_check("sh -c 'cat /etc/shadow'")
            run.assert_not_called()

    def test_rejects_wrong_identity(self):
        with patch.object(executor.os, "geteuid", return_value=0):
            with self.assertRaises(PermissionError):
                executor.run_allowed_check("smoke-v1")

    def test_fixed_profile_and_bounded_output(self):
        result = Mock(returncode=0, stdout="a" * 5000, stderr="")
        with patch.object(executor.os, "geteuid", return_value=1004), \
             patch.object(executor.os.path, "exists", return_value=True), \
             patch.object(executor.subprocess, "run", return_value=result) as run:
            outcome = executor.run_allowed_check("smoke-v1")
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual(len(outcome.stdout), 4096)
        args = run.call_args.args[0]
        for required in ("--network", "none", "--cap-drop", "ALL",
                         "--read-only", "--pids-limit", "64",
                         "--user", "65532:65532"):
            self.assertIn(required, args)
        self.assertEqual(run.call_args.kwargs["timeout"], 60)
        self.assertNotIn("/var/run/docker.sock", " ".join(args))

    def test_timeout_is_not_misreported_as_success(self):
        import subprocess
        with patch.object(executor.os, "geteuid", return_value=1004), \
             patch.object(executor.os.path, "exists", return_value=True), \
             patch.object(executor.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired(["docker"], 60)):
            outcome = executor.run_allowed_check("smoke-v1")
        self.assertTrue(outcome.timed_out)
        self.assertEqual(outcome.exit_code, 124)

if __name__ == "__main__":
    unittest.main()
