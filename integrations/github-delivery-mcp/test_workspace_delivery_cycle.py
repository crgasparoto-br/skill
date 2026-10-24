"""Offline end-to-end worker cycle: trusted develop mirror -> edit -> Git commit.

No SSH, network, GitHub token, hosted CI or MCP exposure. This validates only
worker filesystem and SQLite contracts, not Issue 88 production acceptance.
"""
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobs import JobStore
from worker_workspace_dispatch import dispatch_queued_workspace
from workspace_commit import commit_prepared_workspace
from workspace_file_edit import apply_prepared_file_edit


class OfflineDeliveryCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.upstream = self.path / "source"
        self.upstream.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "develop", str(self.upstream)], check=True)
        (self.upstream / "README.md").write_bytes(b"original\n")
        subprocess.run(["git", "-C", str(self.upstream), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.upstream), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "base"], check=True)
        self.mirror = self.path / "mirror.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.upstream),
                        str(self.mirror)], check=True)
        self.mirror.chmod(0o700)
        self.root = self.path / "jobs"
        self.root.mkdir(mode=0o700)
        self.root.chmod(0o700)
        self.sha = subprocess.check_output(
            ["git", "--git-dir", str(self.mirror),
             "rev-parse", "refs/heads/develop"], text=True,
        ).strip()
        self.actor = "approved-user"
        self.database = str(self.path / "jobs.sqlite3")
        self.lock = str(self.path / "controller.lock")
        self.store = JobStore(self.database)
        self.job = self.store.create(
            actor=self.actor, key="cycle-1", payload_hash=hashlib.sha256(b"request").hexdigest(),
            repo="crgasparoto-br/training-system", issue_number=499,
            branch="feat/499-delivery", base_sha=self.sha, expected_head=self.sha,
        )
        self.worker = patch("workspace_file_edit.WORKER_UID", os.geteuid())
        self.worker.start()
        self.addCleanup(self.worker.stop)

    def prepare(self):
        actual_stat = Path.stat

        def synthetic_worker_owner(path, *args, **kwargs):
            info = actual_stat(path, *args, **kwargs)
            if Path(path) not in (self.mirror, self.root):
                return info

            class OwnedStat:
                st_uid = 1004
                st_mode = info.st_mode

            return OwnedStat()

        # Only the worker UID and directory ownership are simulated; Git and
        # SQLite are real. A remote network or shell execution is not simulated.
        with (patch("worker_workspace_dispatch.os.geteuid", return_value=1004),
              patch("offline_workspace.os.geteuid", return_value=1004),
              patch("offline_workspace.Path.stat", autospec=True,
                    side_effect=synthetic_worker_owner)):
            return dispatch_queued_workspace(
                database_path=self.database, job_id=self.job.job_id, actor=self.actor,
                repository=self.job.repo, mirror_path=str(self.mirror),
                workspace_root=str(self.root),
            )

    def test_real_offline_cycle_and_idempotent_reentry(self):
        prepared = self.prepare()
        self.assertEqual(prepared.status, "prepared")
        workspace = Path(prepared.workspace)
        self.assertTrue(workspace.is_dir())
        self.assertEqual(subprocess.check_output(
            ["git", "-C", str(workspace), "symbolic-ref", "--short", "HEAD"],
            text=True,
        ).strip(), self.job.branch)
        edited = apply_prepared_file_edit(
            database_path=self.database, lock_path=self.lock,
            workspace_root=str(self.root), job_id=self.job.job_id,
            actor=self.actor, relative_path="README.md", expected_head=self.sha,
            expected_sha256=hashlib.sha256(b"original\n").hexdigest(),
            content=b"changed\n",
        )
        self.assertTrue(edited.changed)
        commit = commit_prepared_workspace(
            database_path=self.database, lock_path=self.lock,
            workspace_root=str(self.root), job_id=self.job.job_id,
            actor=self.actor, expected_head=self.sha,
            approved_files={"README.md": edited.new_sha256},
        )
        self.assertNotEqual(commit.head_sha, self.sha)
        self.assertFalse(commit.replayed)
        self.assertEqual(self.store.read(self.job.job_id, self.actor).expected_head,
                         commit.head_sha)
        self.assertEqual(self.store.read(self.job.job_id, self.actor).status, "prepared")
        self.assertEqual((workspace / "README.md").read_bytes(), b"changed\n")
        self.assertEqual(subprocess.check_output(
            ["git", "-C", str(workspace), "rev-parse", "HEAD^"],
            text=True,
        ).strip(), self.sha)
        self.assertTrue(commit_prepared_workspace(
            database_path=self.database, lock_path=self.lock,
            workspace_root=str(self.root), job_id=self.job.job_id,
            actor=self.actor, expected_head=self.sha,
            approved_files={"README.md": edited.new_sha256},
        ).replayed)

    def test_divergent_trusted_mirror_ref_denies_workspace(self):
        # The controller's persisted develop SHA is no longer the mirror HEAD.
        (self.upstream / "README.md").write_bytes(b"other base\n")
        subprocess.run(["git", "-C", str(self.upstream), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.upstream), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "new"], check=True)
        subprocess.run(["git", "--git-dir", str(self.mirror), "fetch", "-q",
                        str(self.upstream), "develop:develop"], check=True)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.store.read(self.job.job_id, self.actor).status, "failed")
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
