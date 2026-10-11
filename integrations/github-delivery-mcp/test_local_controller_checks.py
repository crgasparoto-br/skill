"""CLI only exposes local job checks under the existing dispatch lock."""
import io
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from local_controller import main


class ControllerChecksTests(unittest.TestCase):
    def test_dispatch_after_recovery_without_nested_lock(self):
        argv = ["controller", "--database", "/tmp/jobs.sqlite3",
                "--lock", "/tmp/controller.lock", "--check-job", "job-id",
                "--check-actor", "local-operator", "--check-snapshot", "/tmp/snapshot"]
        sample = SimpleNamespace(check="integrity-v1", passed=True, timed_out=False)
        with patch.object(sys, "argv", argv), patch(
                "local_controller.os.geteuid", return_value=1004), patch(
                "local_controller.controller_lock") as lock, patch(
                "local_controller.recover_local_jobs", return_value=0), patch(
                "local_controller.dispatch_locked_checks", return_value=(sample,)) as dispatch:
            with redirect_stdout(io.StringIO()) as output:
                main()
            self.assertIn('"passed": true', output.getvalue())
            lock.assert_called_once_with("/tmp/controller.lock")
            dispatch.assert_called_once_with(
                database_path="/tmp/jobs.sqlite3", lock_path="/tmp/controller.lock",
                job_id="job-id", actor="local-operator", snapshot_dir="/tmp/snapshot")

    def test_partial_arguments_rejected(self):
        argv = ["controller", "--database", "/tmp/db", "--lock", "/tmp/lock",
                "--check-job", "job-id"]
        with patch.object(sys, "argv", argv), patch(
                "local_controller.dispatch_locked_checks") as dispatch:
            with self.assertRaises(SystemExit):
                main()
            dispatch.assert_not_called()

    def test_smoke_and_checks_mutually_exclusive(self):
        argv = ["controller", "--database", "/tmp/db", "--lock", "/tmp/lock",
                "--check-job", "job-id", "--check-actor", "operator",
                "--check-snapshot", "/tmp/snapshot", "--smoke-key", "k"]
        with patch.object(sys, "argv", argv), patch(
                "local_controller.dispatch_locked_checks") as dispatch:
            with self.assertRaises(SystemExit):
                main()
            dispatch.assert_not_called()
