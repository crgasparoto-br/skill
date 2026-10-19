"""Real-Git negative and positive tests for the worker-only patch boundary."""
import hashlib
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from jobs import JobStore
from policy import PolicyDeniedError
from workspace_file_edit import apply_prepared_file_edit


class PreparedFileEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.work = self.root / "work"
        self.work.mkdir(mode=0o700)
        self.work.chmod(0o700)
        self.db = str(self.root / "jobs.sqlite3")
        self.lock = str(self.root / "controller.lock")
        self.actor = "authorized-operator"
        self.store = JobStore(self.db)
        self.job_id = str(uuid.uuid4())
        self.workspace = self.work / ("solverit-issue88-" + uuid.UUID(self.job_id).hex)
        self.workspace.mkdir(mode=0o700)
        self.workspace.chmod(0o700)
        subprocess.run(["git", "init", "-q", "-b", "feat/499-delivery", str(self.workspace)],
                       check=True)
        self.file = self.workspace / "README.md"
        self.file.write_bytes(b"initial\\n")
        subprocess.run(["git", "-C", str(self.workspace), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
        self.sha = subprocess.check_output(
            ["git", "-C", str(self.workspace), "rev-parse", "HEAD"], text=True).strip()
        self.job = self.store.create(
            actor=self.actor, key="attempt-1", payload_hash=hashlib.sha256(b"request").hexdigest(),
            repo="crgasparoto-br/training-system", issue_number=499,
            branch="feat/499-delivery", base_sha=self.sha, expected_head=self.sha,
        )
        # Stable fixture identity must match the persisted job, not an independent UUID.
        self.workspace.rename(self.work / ("solverit-issue88-" + self.job.job_id.replace("-", "")))
        self.workspace = self.work / ("solverit-issue88-" + self.job.job_id.replace("-", ""))
        self.file = self.workspace / "README.md"
        self.store.transition(self.job.job_id, self.actor, "queued", "running")
        self.store.transition(self.job.job_id, self.actor, "running", "prepared")
        self.kwargs = {
            "database_path": self.db, "lock_path": self.lock,
            "workspace_root": str(self.work), "job_id": self.job.job_id,
            "actor": self.actor, "relative_path": "README.md",
            "expected_head": self.sha,
            "expected_sha256": hashlib.sha256(b"initial\\n").hexdigest(),
            "content": b"changed\\n",
        }
        self.worker = patch("workspace_file_edit.WORKER_UID", os.geteuid())
        self.worker.start()
        self.addCleanup(self.worker.stop)

    def edit(self, **changes):
        return apply_prepared_file_edit(**(self.kwargs | changes))

    def test_real_edit_and_idempotent_repeat(self):
        result = self.edit()
        self.assertTrue(result.changed)
        self.assertEqual(self.file.read_bytes(), b"changed\\n")
        self.assertEqual(result.new_sha256, hashlib.sha256(b"changed\\n").hexdigest())
        replay = self.edit()
        self.assertFalse(replay.changed)
        self.assertEqual(self.file.read_bytes(), b"changed\\n")
        self.assertEqual(list(self.workspace.glob(".issue88-replacement-*")), [])

    def test_concurrent_change_rejected_without_overwrite(self):
        self.file.write_bytes(b"third-party\\n")
        with self.assertRaises(PermissionError):
            self.edit()
        self.assertEqual(self.file.read_bytes(), b"third-party\\n")

    def test_changed_head_rejected(self):
        subprocess.run(["git", "-C", str(self.workspace), "switch", "-q", "-c",
                        "feat/500-delivery"], check=True)
        with self.assertRaises(PermissionError):
            self.edit()
        self.assertEqual(self.file.read_bytes(), b"initial\\n")

    def test_same_branch_but_new_commit_rejected(self):
        self.file.write_bytes(b"new commit\\n")
        subprocess.run(["git", "-C", str(self.workspace), "add", "README.md"], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "other"], check=True)
        with self.assertRaises(PermissionError):
            self.edit()

    def test_wrong_job_owner_denied(self):
        with self.assertRaises(KeyError):
            self.edit(actor="different")
        self.assertEqual(self.file.read_bytes(), b"initial\\n")

    def test_not_prepared_denied(self):
        self.store.transition(self.job.job_id, self.actor, "prepared", "cancelled")
        with self.assertRaises(PermissionError):
            self.edit()

    def test_symlink_file_denied(self):
        self.file.unlink()
        self.file.symlink_to(self.root / "other-file")
        with self.assertRaises(PermissionError):
            self.edit()

    def test_hardlinked_file_denied(self):
        os.link(self.file, self.root / "other-hardlink")
        with self.assertRaises(PermissionError):
            self.edit()

    def test_untracked_file_denied(self):
        (self.workspace / "extra.txt").write_text("unchanged")
        with self.assertRaises(PermissionError):
            self.edit(relative_path="extra.txt")

    def test_policy_paths_denied_before_effect(self):
        for path in ("../escape", ".github/workflows/ci.yml", ".env", "src/../../README.md",
                     "/etc/passwd", "src\\\\foo.py"):
            with self.subTest(path=path), self.assertRaises(PolicyDeniedError):
                self.edit(relative_path=path)
        self.assertEqual(self.file.read_bytes(), b"initial\\n")

    def test_limits_and_bad_sha_denied(self):
        for overrides in ({"content": b"x" * 262145}, {"content": "text"},
                          {"expected_sha256": "a" * 40}):
            with self.subTest(overrides=str(overrides)[:70]), self.assertRaises(ValueError):
                self.edit(**overrides)

    def commit(self, **changes):
        from workspace_commit import commit_prepared_workspace
        intent = {
            "database_path": self.db, "lock_path": self.lock,
            "workspace_root": str(self.work), "job_id": self.job.job_id,
            "actor": self.actor, "expected_head": self.sha,
            "approved_files": {"README.md": hashlib.sha256(b"changed\\n").hexdigest()},
        }
        return commit_prepared_workspace(**(intent | changes))

    def test_real_local_commit_updates_persisted_head_and_replays(self):
        self.edit()
        committed = self.commit()
        self.assertFalse(committed.replayed)
        self.assertNotEqual(committed.head_sha, self.sha)
        self.assertEqual(self.store.read(self.job.job_id, self.actor).expected_head,
                         committed.head_sha)
        self.assertTrue(self.commit().replayed)
        self.assertEqual(subprocess.check_output([
            "git", "-C", str(self.workspace), "rev-parse", "HEAD"
        ], text=True).strip(), committed.head_sha)

    def test_commit_rejects_extra_unapproved_edits(self):
        self.edit()
        (self.workspace / "unexpected").write_text("untracked", encoding="utf-8")
        with self.assertRaises(PermissionError):
            self.commit()
        self.assertEqual(self.store.read(self.job.job_id, self.actor).expected_head, self.sha)

    def test_commit_rejects_stale_file_bytes_without_git_effect(self):
        self.edit()
        with self.assertRaises(PermissionError):
            self.commit(approved_files={"README.md": "a" * 64})
        self.assertEqual(self.store.read(self.job.job_id, self.actor).expected_head, self.sha)

    def test_commit_rejects_unapproved_staged_changes(self):
        self.edit()
        (self.workspace / "other.txt").write_text("other", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "other.txt"], check=True)
        with self.assertRaises(PermissionError):
            self.commit()

    def test_commit_recovers_crash_between_git_and_database_cas(self):
        from jobs import JobStore as Store
        original = Store.record_local_head
        with patch.object(Store, "record_local_head", side_effect=RuntimeError("offline crash")):
            self.edit()
            with self.assertRaises(RuntimeError):
                self.commit()
        self.assertEqual(self.store.read(self.job.job_id, self.actor).expected_head, self.sha)
        recovered = self.commit()
        self.assertTrue(recovered.replayed)
        self.assertEqual(self.store.read(self.job.job_id, self.actor).expected_head,
                         recovered.head_sha)

    def test_edit_after_commit_uses_current_persisted_head(self):
        self.edit()
        published = self.commit()
        result = self.edit(
            expected_head=published.head_sha,
            expected_sha256=hashlib.sha256(b"changed\\n").hexdigest(),
            content=b"second\\n",
        )
        self.assertTrue(result.changed)
        self.assertEqual(self.file.read_bytes(), b"second\\n")

    def test_worker_uid_enforced_before_write(self):
        with patch("workspace_file_edit.WORKER_UID", 999999), self.assertRaises(PermissionError):
            self.edit()
        self.assertEqual(self.file.read_bytes(), b"initial\\n")


if __name__ == "__main__":
    unittest.main()
