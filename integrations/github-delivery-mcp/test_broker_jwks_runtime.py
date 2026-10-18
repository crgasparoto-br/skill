"""Issue 88: no-service broker runtime security preflight tests."""
import importlib.util
import sys
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parent / "ops" / "check-broker-jwks-runtime.py"
SPEC = importlib.util.spec_from_file_location("issue88_broker_runtime", SCRIPT)
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class BrokerRuntimeTests(unittest.TestCase):
    def test_nonroot_refused_before_policy_is_read(self):
        with patch.object(runtime.os, "geteuid", return_value=1000), self.assertRaises(runtime.RuntimeDenied):
            runtime.read_trusted_policy()

    def test_uid_gid_and_supplementary_groups_restricted(self):
        account = Mock(pw_uid=997, pw_gid=986)
        with (patch.object(runtime.pwd, "getpwnam", return_value=account),
              patch.object(runtime.os, "setgroups") as setgroups,
              patch.object(runtime.os, "setgid") as setgid,
              patch.object(runtime.os, "setuid") as setuid,
              patch.object(runtime.os, "geteuid", return_value=997),
              patch.object(runtime.os, "getegid", return_value=986),
              patch.object(runtime.os, "getgroups", return_value=[])):
            runtime.drop_to_authenticator()
            setgroups.assert_called_once_with([])
            setgid.assert_called_once_with(986)
            setuid.assert_called_once_with(997)

    def test_unexpected_authenticator_identity_fails_closed(self):
        account = Mock(pw_uid=1004, pw_gid=986)
        with patch.object(runtime.pwd, "getpwnam", return_value=account):
            with self.assertRaises(runtime.RuntimeDenied):
                runtime.drop_to_authenticator()

    def test_invalid_tokens_must_be_rejected_under_public_jwks(self):
        fake = types.ModuleType("broker_oauth")
        class Denied(PermissionError):
            pass
        fake.BrokerOAuthDenied = Denied
        fake.build_broker_verifier = Mock(return_value=object())
        fake.verified_actor = Mock(side_effect=Denied("fake rejected"))
        with patch.dict(sys.modules, {"broker_oauth": fake}):
            runtime.verify_public_jwks_runtime({"nonsecret": "value"})
        self.assertEqual(fake.verified_actor.call_count, 3)
        self.assertEqual(fake.verified_actor.call_args_list[0].args[0],
                         "unsigned.payload.fake")
        fake.build_broker_verifier.assert_called_once_with({"nonsecret": "value"})

    def test_fake_bearer_never_accepted(self):
        fake = types.ModuleType("broker_oauth")
        fake.BrokerOAuthDenied = PermissionError
        fake.build_broker_verifier = Mock(return_value=object())
        fake.verified_actor = Mock(return_value="unexpected")
        with patch.dict(sys.modules, {"broker_oauth": fake}):
            with self.assertRaises(runtime.RuntimeDenied):
                runtime.verify_public_jwks_runtime({})

    def test_success_does_not_log_subject_or_activate_service(self):
        output = StringIO()
        secret = "DO-NOT-ECHO-THIS-IDENTITY"
        with (patch.object(runtime, "read_trusted_policy",
                           return_value={"SOLVERIT_MCP_DELIVERY_SUBJECTS": secret}),
              patch.object(runtime, "drop_to_authenticator"),
              patch.object(runtime, "verify_public_jwks_runtime")):
            with redirect_stdout(output):
                self.assertEqual(runtime.main(), 0)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn("NO SERVICES STARTED", output.getvalue())

    def test_jwks_outage_fails_without_leaking_details(self):
        output = StringIO()
        with (patch.object(runtime, "read_trusted_policy", return_value={}),
              patch.object(runtime, "drop_to_authenticator"),
              patch.object(runtime, "verify_public_jwks_runtime",
                           side_effect=runtime.RuntimeDenied("Keycloak JWKS or negative token check failed"))):
            with redirect_stdout(output):
                self.assertEqual(runtime.main(), 1)
        self.assertIn("BROKER MUST REMAIN STOPPED", output.getvalue())

    def test_script_does_not_modify_service_or_config(self):
        code = SCRIPT.read_text(encoding="utf-8")
        for needle in ("systemctl start", "systemctl restart", "systemctl enable",
                       "subprocess.run", "subprocess.Popen", "mint_token(", "socket.bind(",
                       "getpass(", "os.environ.update(", "client_secret", "read-issue"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, code)


if __name__ == "__main__":
    unittest.main()
