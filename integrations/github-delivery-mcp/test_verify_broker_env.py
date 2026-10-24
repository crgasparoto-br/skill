"""Offline security tests for non-disclosing broker.env verification."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent / "ops" / "verify-broker-env.py"
SPEC = importlib.util.spec_from_file_location("verify_broker_env", SCRIPT)
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)

GOOD_SUB = "b2cc6dc2-d3a1-4bbc-8b39-5d038e6a5b80"


def make_raw(subject: str = GOOD_SUB) -> bytes:
    lines = [f"{key}={value}" for key, value in verify.FIXED.items()]
    lines.append(f"{verify.SUBJECT_KEY}={subject}")
    return ("\n".join(lines) + "\n").encode("ascii")


class BrokerEnvReadbackTests(unittest.TestCase):
    def test_exact_policy_accepted(self):
        self.assertIsNone(verify.check_contents(make_raw()))

    def test_unknown_and_duplicate_keys_denied(self):
        for raw in (make_raw() + b"UNEXPECTED=true\n",
                    make_raw() + b"SOLVERIT_BROKER_CONTROLLER_UID=1\n",
                    make_raw().replace(b"SOLVERIT_BROKER_SOCKET_GID=984\n", b"")):
            with self.subTest(rawlen=len(raw)), self.assertRaises(verify.InvalidBrokerPolicyError):
                verify.check_contents(raw)

    def test_wrong_issuer_audience_or_group_denied(self):
        for original, replacement in (
            (b"auth.solveritconsultoria.com.br", b"untrusted.invalid"),
            (b"mcp.solveritconsultoria.com.br", b"attacker.invalid"),
            (b"SOLVERIT_BROKER_SOCKET_GID=984", b"SOLVERIT_BROKER_SOCKET_GID=0"),
        ):
            with self.subTest(original=original), self.assertRaises(verify.InvalidBrokerPolicyError):
                verify.check_contents(make_raw().replace(original, replacement))

    def test_bad_subject_and_payload_injection_denied(self):
        for sub in ("admin", "", GOOD_SUB.upper(),
                    "00000000-0000-0000-0000-000000000000",
                    GOOD_SUB + "\nEXTRA=malicious"):
            with self.subTest(sub=sub), self.assertRaises(verify.InvalidBrokerPolicyError):
                verify.check_contents(make_raw(sub))

    def test_unsafe_syntax_and_size_denied(self):
        for raw in (b"", b"A=" * 3000, make_raw() + b"\xff",
                    make_raw().rstrip(b"\n"), make_raw().replace(b"=995", b"==995")):
            with self.subTest(length=len(raw)), self.assertRaises(verify.InvalidBrokerPolicyError):
                verify.check_contents(raw)

    def test_nonroot_refused_without_reading_config(self):
        with patch.object(verify.os, "geteuid", return_value=1004), patch.object(verify.os, "lstat") as lstat:
            with self.assertRaises(verify.InvalidBrokerPolicyError):
                verify.inspect(Path("/etc/solverit/issue-delivery/broker.env"))
            lstat.assert_not_called()

    def test_error_output_never_prints_user_identifier(self):
        from contextlib import redirect_stdout
        from io import StringIO
        for result in (None, verify.InvalidBrokerPolicyError("redacted")):
            output = StringIO()
            with patch.object(verify, "inspect", side_effect=result), redirect_stdout(output):
                code = verify.main()
            self.assertEqual(code, 0 if result is None else 1)
            self.assertNotIn(GOOD_SUB, output.getvalue())
            self.assertNotIn("SOLVERIT_MCP_DELIVERY_SUBJECTS=", output.getvalue())

    def test_no_service_activation_or_credentials(self):
        code = SCRIPT.read_text(encoding="utf-8")
        for needle in ("systemctl start", "systemctl enable",
                       "systemctl restart", "getpass(", "subprocess.run",
                       "requests.post", "print(fields["):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, code)


if __name__ == "__main__":
    unittest.main()
