"""Fail-closed tests for rootless read-only snapshot inspection."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workspace_container_check import inspect_workspace_in_container


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "snapshot"
        self.dir.mkdir(mode=0o755)
        self.sha = "a" * 40

    def test_unknown_check_denied_before_docker(self):
        with self.assertRaises(ValueError):
            inspect_workspace_in_container(str(self.dir), self.sha, check="sh -c evil")

    def test_fixed_shell_check_command(self):
        from workspace_container_check import _FIXED_CHECKS
        self.assertIn("sh -n", _FIXED_CHECKS["posix-shell-syntax-v1"])
        self.assertIn("find /workspace", _FIXED_CHECKS["posix-shell-syntax-v1"])
        self.assertIn("case", _FIXED_CHECKS["posix-shell-syntax-v1"])

    def test_bash_check_not_falsely_supported(self):
        with self.assertRaises(ValueError):
            inspect_workspace_in_container(str(self.dir), self.sha, check="shell-syntax-v1")

    def test_reject_worker_mismatch(self):
        with patch("workspace_container_check.os.geteuid", return_value=1000):
            with self.assertRaises(PermissionError):
                inspect_workspace_in_container(str(self.dir), self.sha)

    def test_reject_sha(self):
        with patch("workspace_container_check.os.geteuid", return_value=1004):
            with self.assertRaises(ValueError):
                inspect_workspace_in_container(str(self.dir), "develop")

    def test_reject_symlink(self):
        link = Path(self.tmp.name) / "alias"
        link.symlink_to(self.dir, target_is_directory=True)
        with patch("workspace_container_check.os.geteuid", return_value=1004):
            with self.assertRaises(PermissionError):
                inspect_workspace_in_container(str(link), self.sha)

    def test_reject_worker_private_directory(self):
        self.dir.chmod(0o700)
        with patch("workspace_container_check.os.geteuid", return_value=1004), patch(
            "workspace_container_check.Path.stat"
        ) as stat:
            stat.return_value.st_uid = 1004
            stat.return_value.st_mode = 0o40700
            with self.assertRaises(PermissionError):
                inspect_workspace_in_container(str(self.dir), self.sha)
