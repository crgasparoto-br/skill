"""Exclusive controller lock and pinned SHA are prerequisites to execution."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_evidence import CheckEvidenceStore
from controller_lock import controller_lock
from locked_check_dispatch import dispatch_locked_checks


class LockedDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.db = str(base / "jobs.sqlite3")
        self.lock = str(base / "controller.lock")
        self.snapshot = base / "snapshot"
        self.snapshot.mkdir()
        self.store = CheckEvidenceStore(self.db)
        job = self.store.jobs.create(
            actor="operator", key="k", payload_hash=hashlib.sha256(b"x").hexdigest(),
            repo="crgasparoto-br/skill", issue_number=88,
            branch="feat/88-test", base_sha="a"*40, expected_head="a"*40,
        )
        self.id = job.job_id
        self.args = dict(database_path=self.db, lock_path=self.lock,
                         job_id=self.id, actor="operator",
                         snapshot_dir=str(self.snapshot))
        (self.snapshot / ".solverit-expected-sha").write_text("a"*40 + "\n")
        self.store.jobs.transition(self.id, "operator", "queued", "running")
        self.store.jobs.transition(self.id, "operator", "running", "prepared")

    def test_dispatch_holds_exclusive_lock(self):
        def check(**kwargs):
            with self.assertRaises(RuntimeError):
                with controller_lock(self.lock):
                    pass
            return ("verified",)
        with patch("locked_check_dispatch.os.geteuid", return_value=1004), patch(
            "locked_check_dispatch.run_and_record_checks", side_effect=check
        ) as run:
            self.assertEqual(dispatch_locked_checks(**self.args), ("verified",))
            run.assert_called_once()

    def test_wrong_marker_denied_before_run(self):
        (self.snapshot / ".solverit-expected-sha").write_text("b"*40)
        with patch("locked_check_dispatch.os.geteuid", return_value=1004), patch(
            "locked_check_dispatch.run_and_record_checks"
        ) as run:
            with self.assertRaises(PermissionError):
                dispatch_locked_checks(**self.args)
            run.assert_not_called()

    def test_actor_denied(self):
        with patch("locked_check_dispatch.os.geteuid", return_value=1004), patch(
            "locked_check_dispatch.run_and_record_checks"
        ) as run:
            with self.assertRaises(KeyError):
                dispatch_locked_checks(**(self.args | {"actor":"other"}))
            run.assert_not_called()

    def test_unprepared_denied(self):
        self.store.jobs.transition(self.id, "operator", "prepared", "failed")
        with patch("locked_check_dispatch.os.geteuid", return_value=1004), patch(
            "locked_check_dispatch.run_and_record_checks"
        ) as run:
            with self.assertRaises(PermissionError):
                dispatch_locked_checks(**self.args)
            run.assert_not_called()

    def test_non_worker_denied(self):
        with patch("locked_check_dispatch.os.geteuid", return_value=1000):
            with self.assertRaises(PermissionError):
                dispatch_locked_checks(**self.args)
