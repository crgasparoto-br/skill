"""Bounded snapshot export denies unsafe Git trees and verifies pinned HEAD."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from snapshot_export import export_pinned_snapshot


class SnapshotExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "src"
        self.source.mkdir()
        self.root = self.base / "snapshots"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "develop", str(self.source)], check=True)
        self.write("readme.txt", "Hello\n")
        self.commit()
        self.mirror = self.base / "mirror.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(self.source),
                        str(self.mirror)], check=True)
        # Git bare clone inherits umask and may create a group-writable mirror.
        # Match the production contract without weakening its permission check.
        self.mirror.chmod(0o700)
        self.root.chmod(0o700)

    def write(self, name, value):
        target = self.source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def commit(self):
        subprocess.run(["git", "-C", str(self.source), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.source), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid", "commit", "-qm", "test"], check=True)

    def sha(self):
        return subprocess.check_output(["git", "--git-dir", str(self.mirror),
                                        "rev-parse", "refs/heads/develop"], text=True).strip()

    def export(self, **overrides):
        args = dict(mirror_path=str(self.mirror), root_path=str(self.root),
                    expected_sha=self.sha())
        args.update(overrides)
        # Test uses a real local Git mirror; only filesystem identity is simulated.
        original = Path.stat
        with patch("snapshot_export.os.geteuid", return_value=1004), patch(
            "snapshot_export.Path.stat", autospec=True
        ) as stat:
            def fake_stat(path, *a, **k):
                value = original(path, *a, **k)
                # Avoid mutating cached os.stat_result; use a minimal proxy.
                class Proxy:
                    st_uid = 1004
                    st_mode = value.st_mode
                return Proxy()
            stat.side_effect = fake_stat
            return export_pinned_snapshot(**args)

    def test_pinned_export(self):
        exported = Path(self.export())
        self.assertEqual((exported / "readme.txt").read_text(), "Hello\n")
        self.assertEqual((exported / ".solverit-expected-sha").read_text().strip(), self.sha())

    def test_wrong_sha_denied(self):
        with self.assertRaises(ValueError):
            self.export(expected_sha="a" * 40)

    def test_symlink_denied(self):
        self.write("link", "placeholder")
        (self.source / "link").unlink()
        (self.source / "link").symlink_to("readme.txt")
        self.commit()
        subprocess.run(["git", "--git-dir", str(self.mirror), "fetch", "-q",
                        str(self.source), "develop:develop"], check=True)
        with self.assertRaises(ValueError):
            self.export()

    def test_hidden_paths_denied(self):
        self.write(".env", "SECRET=not-real")
        self.commit()
        subprocess.run(["git", "--git-dir", str(self.mirror), "fetch", "-q",
                        str(self.source), "develop:develop"], check=True)
        with self.assertRaises(ValueError):
            self.export()

    def refresh(self):
        subprocess.run(["git", "--git-dir", str(self.mirror), "fetch", "-q",
                        str(self.source), "develop:develop"], check=True)

    def test_reviewed_dotfiles_are_exported(self):
        self.write(".gitignore", "node_modules/\\n")
        self.write("src/.editorconfig", "root=true\\n")
        self.commit()
        self.refresh()
        exported = Path(self.export())
        self.assertEqual((exported / ".gitignore").read_text(), "node_modules/\\n")
        self.assertEqual((exported / "src/.editorconfig").read_text(), "root=true\\n")

    def test_hidden_directory_denied(self):
        self.write(".cache/data.txt", "not-a-secret")
        self.commit()
        self.refresh()
        with self.assertRaises(ValueError):
            self.export()

    def test_credential_name_denied(self):
        self.write("config/.npmrc", "//registry:password=example")
        self.commit()
        self.refresh()
        with self.assertRaises(ValueError):
            self.export()

    def test_invalid_sha_denied(self):
        with self.assertRaises(ValueError):
            self.export(expected_sha="../develop")
