"""Recovery loop is serial, stoppable and refuses non-worker execution."""
import threading
import unittest
from unittest.mock import patch

from controller_loop import run_recovery_loop


class RecoveryLoopTests(unittest.TestCase):
    def test_reconciles_under_exclusive_lock_and_stops(self):
        stop = threading.Event()
        observations = []
        def recover(db):
            observations.append(("recover", db))
            stop.set()
            return 2
        with patch("controller_loop.os.geteuid", return_value=1004), patch(
                "controller_loop.controller_lock") as lock, patch(
                "controller_loop.recover_local_jobs", side_effect=recover):
            run_recovery_loop(database_path="jobs.db", lock_path="controller.lock",
                              interval_seconds=10, stop_event=stop,
                              on_cycle=lambda n: observations.append(("count", n)))
        lock.assert_called_once_with("controller.lock")
        self.assertEqual(observations, [("recover", "jobs.db"), ("count", 2)])

    def test_refuses_other_identity(self):
        with patch("controller_loop.os.geteuid", return_value=1000), patch(
                "controller_loop.recover_local_jobs") as recover:
            with self.assertRaises(PermissionError):
                run_recovery_loop(database_path="db", lock_path="lock",
                                  stop_event=threading.Event())
            recover.assert_not_called()

    def test_rejects_unsafe_poll_frequency(self):
        with patch("controller_loop.os.geteuid", return_value=1004):
            with self.assertRaises(ValueError):
                run_recovery_loop(database_path="db", lock_path="lock",
                                  interval_seconds=0)

    def test_does_not_reconcile_after_stop(self):
        stop = threading.Event()
        stop.set()
        with patch("controller_loop.os.geteuid", return_value=1004), patch(
                "controller_loop.recover_local_jobs") as recover:
            run_recovery_loop(database_path="db", lock_path="lock",
                              stop_event=stop)
            recover.assert_not_called()
