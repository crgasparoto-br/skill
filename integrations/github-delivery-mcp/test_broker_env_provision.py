"""Offline acceptance for broker.env staging; never modify real /etc."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = (Path(__file__).resolve().parent / "ops" /
          "provision-broker-env.py")
SPEC = importlib.util.spec_from_file_location("provision_broker_env", SCRIPT)
provision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provision)

GOOD_SUB = "b2cc6dc2-d3a1-4bbc-8b39-5d038e6a5b80"


class BrokerEnvProvisionTests(unittest.TestCase):
    def test_canonical_oidc_subject_rejects_names_and_control_chars(self):
        self.assertTrue(provision.subject_is_canonical(GOOD_SUB))
        for subject in ("", "joe@example.test", "john", "0" * 36,
                        "00000000-0000-0000-0000-000000000000",
                        GOOD_SUB.upper(), GOOD_SUB + "\nROOT=0", None):
            with self.subTest(value=repr(subject)):
                self.assertFalse(provision.subject_is_canonical(subject))

    def test_env_contains_only_fixed_pinned_settings_and_subject(self):
        output = provision.make_content(GOOD_SUB).decode("ascii")
        lines = output.splitlines()
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0], "SOLVERIT_BROKER_CONTROLLER_UID=995")
        self.assertEqual(lines[1], "SOLVERIT_BROKER_SOCKET_GID=984")
        self.assertIn("SOLVERIT_MCP_DELIVERY_SUBJECTS=" + GOOD_SUB, lines)
        self.assertIn("SOLVERIT_MCP_RESOURCE_URL=https://mcp.solveritconsultoria.com.br/mcp", lines)
        self.assertNotIn("PEM", output)
        self.assertNotIn("GITHUB_TOKEN", output)
        self.assertNotIn("ACCESS_TOKEN", output)

    def test_bad_subject_does_not_create_content(self):
        for bad in ("realmadmin", "abc\nSOLVERIT_BROKER_CONTROLLER_UID=0"):
            with self.assertRaises(provision.ProvisionDenied):
                provision.make_content(bad)

    def test_secure_dir_rejects_world_or_group_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(provision.ProvisionDenied):
                provision.assert_secure_dir(Path(tmp))
            # Any temporary tree under /tmp is not root-owned by default.
            with patch.object(provision.os, "lstat") as get_stat:
                get_stat.return_value.st_uid = 0
                get_stat.return_value.st_mode = 0o40777
                with self.assertRaises(provision.ProvisionDenied):
                    provision.assert_secure_dir(Path(tmp))

    def test_non_root_refused_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(provision.os, "geteuid", return_value=1000):
                with self.assertRaises(provision.ProvisionDenied):
                    provision.write_exclusive(Path(tmp) / "broker.env", b"x")

    def test_atomic_create_no_overwrite_and_no_symlink_follow(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broker.env"
            with (patch.object(provision.os, "geteuid", return_value=0),
                  patch.object(provision, "assert_secure_dir", return_value=None),
                  patch.object(provision.os, "fchown", return_value=None)):
                provision.write_exclusive(path, provision.make_content(GOOD_SUB))
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertIn(GOOD_SUB.encode(), path.read_bytes())
                with self.assertRaises(provision.ProvisionDenied):
                    provision.write_exclusive(path, b"different")
            self.assertEqual(path.read_bytes(), provision.make_content(GOOD_SUB))

    def test_main_preview_does_not_prompt_or_write(self):
        with (patch.object(provision.os, "geteuid", return_value=0),
              patch.object(provision, "assert_unchanged_service_identities"),
              patch.object(provision, "assert_secure_dir"),
              patch.object(provision.os.path, "lexists", return_value=False),
              patch("builtins.input", side_effect=AssertionError("unexpected prompt")),
              patch.object(provision, "write_exclusive") as write):
            self.assertEqual(provision.main([]), 0)
            write.assert_not_called()

    def test_main_apply_denied_without_operator_evidence(self):
        with (patch.object(provision.os, "geteuid", return_value=0),
              patch.object(provision, "assert_unchanged_service_identities"),
              patch.object(provision, "assert_secure_dir"),
              patch.object(provision.os.path, "lexists", return_value=False),
              patch("builtins.input", return_value="NAO"),
              patch.object(provision.getpass, "getpass") as getsub,
              patch.object(provision, "write_exclusive") as write):
            self.assertEqual(provision.main(["--apply"]), 1)
            getsub.assert_not_called()
            write.assert_not_called()

    def test_main_apply_never_logs_or_prints_approved_subject(self):
        from contextlib import redirect_stdout
        from io import StringIO
        out = StringIO()
        with (patch.object(provision.os, "geteuid", return_value=0),
              patch.object(provision, "assert_unchanged_service_identities"),
              patch.object(provision, "assert_secure_dir"),
              patch.object(provision.os.path, "lexists", return_value=False),
              patch("builtins.input", return_value="CONFIRMADO"),
              patch.object(provision.getpass, "getpass", return_value=GOOD_SUB),
              patch.object(provision, "write_exclusive") as write):
            with redirect_stdout(out):
                self.assertEqual(provision.main(["--apply"]), 0)
            write.assert_called_once()
        self.assertNotIn(GOOD_SUB, out.getvalue())


if __name__ == "__main__":
    unittest.main()
