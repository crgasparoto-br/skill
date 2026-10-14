"""Static contract for the non-mutating Issue 88 VPS readiness probe."""
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "ops" / "verify-broker-staging.sh"


class BrokerReadinessContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_shell_syntax(self):
        if not shutil.which("bash"):
            self.skipTest("bash unavailable")
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True,
                                text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_sudo_never_prompts_for_password(self):
        self.assertIn("sudo -n /usr/bin/id -u", self.source)
        for line in self.source.splitlines():
            stripped = line.strip()
            if stripped.startswith("sudo "):
                self.assertTrue(stripped.startswith("sudo -n "), stripped)
        self.assertNotIn("sudo -v", self.source)

    def test_no_unsafe_writes_or_activation(self):
        for command in ("systemctl start", "systemctl restart",
                        "systemctl enable", " usermod ", " useradd ",
                        " groupadd ", " chown ", " chmod ",
                        " pip install", "docker run", "systemctl daemon-reload"):
            with self.subTest(command=command):
                self.assertNotIn(command, self.source)
        self.assertNotIn("broker.env\n", self.source)
        self.assertIn("BROKER", self.source)

    def test_segregation_private_file_and_service_python_required(self):
        self.assertIn("id -u solverit-controller", self.source)
        self.assertIn("id -u solverit-worker", self.source)
        self.assertIn("id -u solverit-github-auth", self.source)
        self.assertIn('META" = "997:986:600:regular file"', self.source)
        self.assertIn("/usr/bin/python3 -B -c", self.source)
        self.assertIn("PYTHONDONTWRITEBYTECODE=1", self.source)
        self.assertIn("import jwt, cryptography", self.source)
        self.assertIn("systemctl -q is-active solverit-issue88-github-broker.service", self.source)

    def test_terminal_preserved_and_failures_propagated(self):
        self.assertIn("RC=$?", self.source)
        self.assertIn('test "$RC" -eq 0', self.source)
        self.assertIn("TERMINAL PRESERVADO", self.source)
        self.assertNotIn("exec bash", self.source)


if __name__ == "__main__":
    unittest.main()
