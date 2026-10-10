"""Local controller concurrency tests, without real Docker."""
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import local_controller
from controller_lock import controller_lock

class ControllerLockTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.lock = os.path.join(self.directory.name, "controller.lock")
        self.db = os.path.join(self.directory.name, "jobs.sqlite3")

    def tearDown(self):
        self.directory.cleanup()

    def test_second_controller_rejected_while_first_holds_lock(self):
        with controller_lock(self.lock):
            with self.assertRaisesRegex(RuntimeError, "another controller"):
                with controller_lock(self.lock):
                    pass

    def test_lock_can_be_reacquired(self):
        with controller_lock(self.lock):
            pass
        with controller_lock(self.lock):
            pass

    def test_unsafe_lock_mode_rejected(self):
        with open(self.lock, "w", encoding="utf-8") as lock:
            lock.write("")
        os.chmod(self.lock, 0o666)
        with self.assertRaises(PermissionError):
            with controller_lock(self.lock):
                pass

    def test_recovery_before_dispatch_under_same_lock(self):
        events = []

        @contextmanager
        def fake_lock(path):
            self.assertEqual(path, self.lock)
            events.append("lock_enter")
            try:
                yield
            finally:
                events.append("lock_exit")

        def recover(path):
            self.assertEqual(path, self.db)
            events.append("recover")
            return 0

        def dispatch(*args, **kwargs):
            events.append("dispatch")
            from local_job_runner import LocalJobOutcome
            return LocalJobOutcome("id", "succeeded", 0, "CHECK_OK")

        # This tests orchestration, not filesystem ownership.
        # Actual flock/permission behavior is tested in the other tests.
        with patch.object(local_controller.os, "geteuid", return_value=1004), \
             patch.object(local_controller, "controller_lock", side_effect=fake_lock), \
             patch.object(local_controller, "recover_local_jobs", side_effect=recover), \
             patch.object(local_controller, "submit_offline_smoke", side_effect=dispatch), \
             patch.object(sys, "argv", ["local_controller", "--database", self.db, "--lock", self.lock, "--smoke-key", "k"]):
            local_controller.main()

        self.assertEqual(events, ["lock_enter", "recover", "dispatch", "lock_exit"])


if __name__ == "__main__":
    unittest.main()
