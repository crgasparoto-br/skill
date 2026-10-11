"""Fail-closed tests for offline pinned workspace staging."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from offline_workspace import prepare_offline_workspace


class OfflineWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mirror = self.root / "mirror.git"
        self.mirror.mkdir()
        self.work = self.root / "jobs"
        self.work.mkdir()
        self.params = dict(
            repository="crgasparoto-br/training-system",
            expected_sha="a" * 40,
            mirror_path=str(self.mirror),
            workspace_root=str(self.work),
        )

    def test_refuses_non_worker_identity(self):
        with patch("offline_workspace.os.geteuid", return_value=1000):
            with self.assertRaises(PermissionError):
                prepare_offline_workspace(**self.params)

    def test_refuses_invalid_repo_before_fs(self):
        with patch("offline_workspace.os.geteuid", return_value=1004):
            with self.assertRaises(ValueError):
                prepare_offline_workspace(**(self.params | {"repository": "../unsafe"}))

    def test_refuses_non_commit_sha(self):
        with patch("offline_workspace.os.geteuid", return_value=1004):
            with self.assertRaises(ValueError):
                prepare_offline_workspace(**(self.params | {"expected_sha": "develop"}))

    def test_refuses_non_worker_owned_root(self):
        with patch("offline_workspace.os.geteuid", return_value=1004):
            with self.assertRaises(PermissionError):
                prepare_offline_workspace(**self.params)

    def test_refuses_symlink_mirror(self):
        alias = self.root / "alias.git"
        alias.symlink_to(self.mirror, target_is_directory=True)
        with patch("offline_workspace.os.geteuid", return_value=1004):
            with self.assertRaises(PermissionError):
                prepare_offline_workspace(**(self.params | {"mirror_path": str(alias)}))
