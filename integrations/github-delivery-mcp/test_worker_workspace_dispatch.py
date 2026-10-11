"""Dispatch lifecycle tests; filesystem execution is stubbed, never run."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobs import JobStore
from worker_workspace_dispatch import dispatch_queued_workspace


class WorkspaceDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "jobs.sqlite3")
        self.store = JobStore(self.database)
        self.job = self.store.create(
            actor="operator", key="test", payload_hash=hashlib.sha256(b"request").hexdigest(),
            repo="crgasparoto-br/training-system", issue_number=499,
            branch="feat/499-delivery", base_sha="a"*40, expected_head="a"*40,
        )
        self.args = dict(database_path=self.database, job_id=self.job.job_id,
                         actor="operator", repository="crgasparoto-br/training-system",
                         mirror_path="/unavailable/mirror", workspace_root="/unavailable/jobs")

    def test_worker_only(self):
        with patch("worker_workspace_dispatch.os.geteuid", return_value=1000):
            with self.assertRaises(PermissionError):
                dispatch_queued_workspace(**self.args)
        self.assertEqual(self.store.read(self.job.job_id, "operator").status, "queued")

    def test_success_transitions_and_replay_no_op(self):
        with patch("worker_workspace_dispatch.os.geteuid", return_value=1004), patch(
            "worker_workspace_dispatch.prepare_offline_workspace", return_value="/safe/workspace"
        ) as prepare:
            result = dispatch_queued_workspace(**self.args)
            replay = dispatch_queued_workspace(**self.args)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.workspace, "/safe/workspace")
        self.assertEqual(replay.status, "succeeded")
        self.assertIsNone(replay.workspace)
        prepare.assert_called_once()

    def test_failed_workspace_does_not_replay(self):
        with patch("worker_workspace_dispatch.os.geteuid", return_value=1004), patch(
            "worker_workspace_dispatch.prepare_offline_workspace", side_effect=RuntimeError("offline failure")
        ) as prepare:
            with self.assertRaises(RuntimeError):
                dispatch_queued_workspace(**self.args)
            result = dispatch_queued_workspace(**self.args)
        self.assertEqual(result.status, "failed")
        prepare.assert_called_once()

    def test_cross_repository_denied(self):
        with patch("worker_workspace_dispatch.os.geteuid", return_value=1004):
            with self.assertRaises(PermissionError):
                dispatch_queued_workspace(**(self.args | {"repository":"other/unknown"}))
        self.assertEqual(self.store.read(self.job.job_id, "operator").status, "queued")

    def test_missing_db_denied_without_creation(self):
        missing = str(Path(self.temp.name) / "missing.db")
        with patch("worker_workspace_dispatch.os.geteuid", return_value=1004):
            with self.assertRaises(FileNotFoundError):
                dispatch_queued_workspace(**(self.args | {"database_path":missing}))
        self.assertFalse(Path(missing).exists())
