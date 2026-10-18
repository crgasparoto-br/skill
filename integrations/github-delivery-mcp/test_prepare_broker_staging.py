"""Static safety regression for VPS staging: NEVER run the root bootstrap in CI."""
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "ops" / "prepare-broker-staging.sh"


class BrokerBootstrapContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contents = SCRIPT.read_text(encoding="utf-8")

    def test_bash_syntax(self):
        if not shutil.which("bash"):
            self.skipTest("bash not installed on this test runner")
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True,
                                text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_full_suite_requires_mcp_sdk_not_skipped(self):
        self.assertIn("requirements-sdk-pilot.txt", self.contents)
        self.assertIn("mcp.server.fastmcp", self.contents)
        self.assertIn("unittest discover", self.contents)
        self.assertNotIn("test_mcp_sdk_pilot.py' -v", self.contents)
        self.assertNotIn("skipTest", self.contents)

    def test_all_dependencies_are_isolated_from_production_python(self):
        self.assertIn('"$STAGE/.venv"', self.contents)
        self.assertIn('"$STAGE/.venv/bin/python"', self.contents)
        self.assertIn('"$STAGE/dependencies.log"', self.contents)
        self.assertNotIn("sudo pip ", self.contents)
        self.assertNotIn("pip install --break-system-packages", self.contents)

    def test_failed_subshell_propagates_nonzero_exit_status(self):
        self.assertIn("RC=$?", self.contents)
        self.assertIn('test "$RC" -eq 0', self.contents)
        self.assertIn("TERMINAL PRESERVADO", self.contents)
        self.assertNotIn("exec bash", self.contents)
        self.assertNotIn("systemctl restart", self.contents)
        self.assertNotIn("systemctl start", self.contents)
        self.assertNotIn("systemctl enable", self.contents)

    def test_checks_run_before_any_system_account_changes(self):
        tests = self.contents.index("unittest discover")
        groupadd = self.contents.index("sudo -n groupadd")
        useradd = self.contents.index("sudo -n useradd")
        install = self.contents.index("sudo -n install -d")
        self.assertLess(tests, groupadd)
        self.assertLess(tests, useradd)
        self.assertLess(tests, install)

    def test_sudo_password_prompts_are_impossible(self):
        """Even a stale sudo credential must not request input from the operator."""
        self.assertNotIn("sudo -v", self.contents)
        self.assertIn('sudo -n /usr/bin/id -u', self.contents)
        self.assertIn('Autorizacao sudo', self.contents)
        self.assertLess(self.contents.index('sudo -n /usr/bin/id -u'),
                        self.contents.index('sudo -n groupadd'))
        for line in self.contents.splitlines():
            command = line.strip()
            if command.startswith("sudo "):
                self.assertTrue(command.startswith("sudo -n "), command)

    def test_staging_refuses_active_broker_and_existing_ipc_socket(self):
        self.assertIn("systemctl is-active --quiet solverit-issue88-github-broker.service",
                      self.contents)
        self.assertIn("BLOQUEADO: broker ativo", self.contents)
        self.assertIn("BLOQUEADO: socket preexistente", self.contents)
        self.assertIn('sudo -n /usr/bin/test -L "$TARGET"', self.contents)
        self.assertLess(self.contents.index("BLOQUEADO: broker ativo"),
                        self.contents.index('sudo -n install -d -o root -g root'))

    def test_staged_commit_marker_written_after_postcopy_checks(self):
        self.assertIn('broker_oauth.DELIVERY_CLIENT == "solverit-chatgpt-mcp"',
                      self.contents)
        self.assertLess(self.contents.index("=== 6. ATTESTANDO"),
                        self.contents.index('sudo -n tee "$TARGET/STAGED_COMMIT"'))
        self.assertIn('sudo -n -u solverit-github-auth env PYTHONDONTWRITEBYTECODE=1',
                      self.contents)

    def test_source_commit_is_verified_before_extracting_and_provisioning(self):
        self.assertIn('ACTUAL="$(git -C "$WORK" rev-parse FETCH_HEAD)"', self.contents)
        self.assertIn('if [ "$ACTUAL" != "$EXPECTED" ]; then', self.contents)
        self.assertIn('git -C "$WORK" archive "$EXPECTED"', self.contents)


if __name__ == "__main__":
    unittest.main()
