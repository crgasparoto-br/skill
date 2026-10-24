"""Static safe-op proof for read-only Issue 88 controller staging preflight."""
import shutil
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "ops/verify-controller-staging.sh"


class ControllerStagingPreflightTests(unittest.TestCase):
    def test_bash_syntax_and_terminal_preservation(self):
        if shutil.which("bash") is None:
            self.skipTest("bash interpreter unavailable")
        check = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True,
                               text=True, check=False, timeout=10)
        self.assertEqual(check.returncode, 0, check.stderr)
        data = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("TERMINAL PRESERVADO", data)
        self.assertIn('test "$RC" -eq 0', data)

    def test_no_mutation_or_activation_or_secret_export(self):
        data = SCRIPT.read_text(encoding="utf-8")
        for denied in ("systemctl start", "systemctl enable", "systemctl restart",
                       "sudo -n install ", "sudo -n chown ", "sudo -n chmod ",
                       "git clone", "git push", "git fetch",
                       "curl -", "oauth.env", "broker.env", "tee ", "rm -",
                       "cat /etc/solverit", "openssh"):
            with self.subTest(denied=denied):
                self.assertNotIn(denied, data)

    def test_exact_sha_segregation_sqlite_and_no_service(self):
        data = SCRIPT.read_text(encoding="utf-8")
        for required in (
            "ISSUE88_EXPECTED_SHA", "STAGED_COMMIT",
            "solverit-controller", "solverit-github-auth", "solverit-worker",
            "issue88-controller/jobs.sqlite3", "997:986:600:regular file",
            "700:directory", "600:regular file",
            "mode=ro", "systemctl is-active --quiet",
            "mcp.server.fastmcp", "mcp_delivery_entrypoint.py",
            "trusted_github_http.py", "broker_develop_intake.py",
        ):
            with self.subTest(required=required):
                self.assertIn(required, data)


if __name__ == "__main__":
    unittest.main()
