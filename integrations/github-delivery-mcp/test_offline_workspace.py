"""Fail-closed tests for offline pinned workspace staging."""
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from offline_workspace import prepare_offline_workspace
from policy import PolicyDeniedError


class OfflineWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mirror = self.root / "mirror.git"
        self.mirror.mkdir()
        self.work = self.root / "jobs"
        self.work.mkdir()
        self.params = {
            "repository": "crgasparoto-br/training-system",
            "expected_sha": "a" * 40,
            "mirror_path": str(self.mirror),
            "workspace_root": str(self.work),
            "job_id": str(uuid.uuid4()),
            "branch": "feat/499-delivery",
        }

    def test_refuses_invalid_branch_before_any_git_operation(self):
        with patch("offline_workspace.os.geteuid", return_value=1004):
            for branch in ("develop", "main", "feat/../danger", "feat/499-delivery;whoami"):
                with self.subTest(branch=branch), self.assertRaises(PolicyDeniedError):
                    prepare_offline_workspace(**(self.params | {"branch": branch}))

    def test_refuses_noncanonical_job_identity(self):
        with patch("offline_workspace.os.geteuid", return_value=1004):
            for job_id in ("../other", str(uuid.uuid4()).upper(), str(uuid.uuid1()), "", 9):
                with self.subTest(job_id=job_id), self.assertRaises(ValueError):
                    prepare_offline_workspace(**(self.params | {"job_id": job_id}))

    def test_real_bare_mirror_creates_pinned_job_branch_without_network(self):
        source = self.root / "upstream"
        source.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "develop", str(source)], check=True)
        (source / "file.txt").write_text("original\\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(source), "add", "file.txt"], check=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=Test",
                        "-c", "user.email=test@example.invalid",
                        "commit", "-qm", "base"], check=True)
        subprocess.run(["git", "clone", "-q", "--bare", str(source), str(self.mirror / "bare.git")],
                       check=True)
        mirror = self.mirror / "bare.git"
        mirror.chmod(0o700)
        self.work.chmod(0o700)
        base_sha = subprocess.check_output(["git", "--git-dir", str(mirror),
                                             "rev-parse", "refs/heads/develop"], text=True).strip()
        params = self.params | {"mirror_path": str(mirror), "expected_sha": base_sha}
        original_stat = Path.stat
        def pretend_worker_owned(path, *args, **kwargs):
            stat_result = original_stat(path, *args, **kwargs)
            if Path(path) in (mirror, self.work):
                class WorkerStat:
                    st_uid = 1004
                    st_mode = stat_result.st_mode
                return WorkerStat()
            return stat_result
        with patch("offline_workspace.os.geteuid", return_value=1004), patch(
            "offline_workspace.Path.stat", autospec=True, side_effect=pretend_worker_owned
        ):
            workspace = prepare_offline_workspace(**params)
            with self.assertRaises(FileExistsError):
                prepare_offline_workspace(**params)
        folder = Path(workspace)
        self.assertEqual(folder.name, "solverit-issue88-" + uuid.UUID(params["job_id"]).hex)
        self.assertEqual(subprocess.check_output(["git", "-C", workspace,
                            "symbolic-ref", "--short", "HEAD"], text=True).strip(), params["branch"])
        self.assertEqual(subprocess.check_output(["git", "-C", workspace,
                            "rev-parse", "HEAD"], text=True).strip(), base_sha)
        self.assertEqual((folder / "file.txt").read_text(encoding="utf-8"), "original\\n")

    def test_refuses_non_worker_identity(self):
        with patch("offline_workspace.os.geteuid", return_value=1000), self.assertRaises(PermissionError):
            prepare_offline_workspace(**self.params)

    def test_refuses_invalid_repo_before_fs(self):
        with patch("offline_workspace.os.geteuid", return_value=1004), self.assertRaises(ValueError):
            prepare_offline_workspace(**(self.params | {"repository": "../unsafe"}))

    def test_refuses_dot_path_components(self):
        with patch("offline_workspace.os.geteuid", return_value=1004):
            for value in ("../unsafe", "./unsafe", "owner/..", "owner/."):
                with self.subTest(repository=value), self.assertRaises(ValueError):
                    prepare_offline_workspace(**(self.params | {"repository": value}))

    def test_refuses_non_commit_sha(self):
        with patch("offline_workspace.os.geteuid", return_value=1004), self.assertRaises(ValueError):
            prepare_offline_workspace(**(self.params | {"expected_sha": "develop"}))

    def test_refuses_non_worker_owned_root(self):
        with patch("offline_workspace.os.geteuid", return_value=1004), self.assertRaises(PermissionError):
            prepare_offline_workspace(**self.params)

    def test_refuses_symlink_mirror(self):
        alias = self.root / "alias.git"
        alias.symlink_to(self.mirror, target_is_directory=True)
        with patch("offline_workspace.os.geteuid", return_value=1004), self.assertRaises(PermissionError):
            prepare_offline_workspace(**(self.params | {"mirror_path": str(alias)}))
