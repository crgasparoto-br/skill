"""Static unit assertions: no services are started by these tests."""
import unittest
from pathlib import Path

import configparser

HERE = Path(__file__).resolve().parent
UNIT = HERE / "systemd/solverit-issue-delivery.service"
OVERRIDE = HERE / "systemd/10-rootless.conf"



def section(path):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(path)
    return config

class SystemdContractTests(unittest.TestCase):
    def test_recovery_is_manual_oneshot_without_automatic_dispatch(self):
        service = section(UNIT)["Service"]
        self.assertEqual(service["Type"], "oneshot")
        self.assertEqual(service["User"], "solverit-worker")
        self.assertNotIn("--smoke-key", service["ExecStart"])
        self.assertIn("local_controller.py", service["ExecStart"])
        self.assertIn("NoNewPrivileges", service)
        self.assertEqual(service["NoNewPrivileges"], "yes")
        self.assertEqual(service["ProtectSystem"], "strict")
        self.assertEqual(service["ProtectHome"], "read-only")

    def test_docker_socket_precondition(self):
        override = section(OVERRIDE)
        self.assertEqual(override["Service"]["ExecStartPre"],
                         "/usr/bin/test -S /run/user/1004/docker.sock")
        self.assertIn("user@1004.service", override["Unit"]["Requires"])

    def test_no_secrets_or_untrusted_network_ports(self):
        unit_text = UNIT.read_text()
        self.assertNotIn("github-app.pem", unit_text)
        self.assertNotIn("ListenStream", unit_text)
        self.assertNotIn("ExecStartPost", unit_text)

if __name__ == "__main__":
    unittest.main()
