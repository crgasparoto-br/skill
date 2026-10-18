"""Offline fail-closed regressions for the Issue #88 live OAuth preflight."""
import importlib.util
import sys
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).parent / 'ops/check-broker-live-access.py'
SPEC = importlib.util.spec_from_file_location('issue88_live_access', SCRIPT)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

POLICY = {
    'SOLVERIT_MCP_DELIVERY_SUBJECTS': 'approved-uuid',
    'SOLVERIT_OAUTH_ISSUER_URL': 'https://id.example/realm',
    'SOLVERIT_OAUTH_JWKS_URI': 'https://id.example/realm/certs',
    'SOLVERIT_MCP_RESOURCE_URL': 'https://mcp.example/mcp',
}


class LiveAccessPreflightTests(unittest.TestCase):
    def test_requires_exact_pinned_sha(self):
        with patch.dict(probe.os.environ, {}, clear=True), self.assertRaises(probe.LiveProbeError):
            probe.validate_staging()

    def test_untrusted_operator_checkout_cannot_be_live_preflight(self):
        with (patch.dict(probe.os.environ, {'ISSUE88_EXPECTED_SHA': 'a' * 40}),
              patch.object(probe, 'HERE', Path('/home/ubuntu/projetos/issue88-probe/ops')),
              self.assertRaises(probe.LiveProbeError)):
            probe.validate_staging()

    def test_no_noninteractive_secret_input(self):
        with (patch.object(probe.sys.stdin, 'isatty', return_value=False),
              self.assertRaises(probe.LiveProbeError)):
            probe.private_token('hidden')

    def test_verifies_positive_then_both_negatives(self):
        fake = types.ModuleType('broker_oauth')
        class DeniedError(Exception):
            pass
        fake.BrokerOAuthError = DeniedError
        fake.build_broker_verifier = Mock(return_value='verifier')
        fake.verified_actor = Mock(side_effect=['approved-uuid', DeniedError(), DeniedError()])
        with (patch.dict(sys.modules, {'broker_oauth': fake}),
              patch.object(probe, 'validated_signed_claims', side_effect=[
                  {'sub': 'approved-uuid', 'scope': 'openid solverit:read'},
                  {'sub': 'another-uuid', 'scope': 'openid solverit:read'}])):
            probe.check_signed_tokens(POLICY, 'positive', 'readonly', 'other')
        self.assertEqual(fake.verified_actor.call_count, 3)

    def test_wrong_scope_negative_not_accepted_as_evidence(self):
        fake = types.ModuleType('broker_oauth')
        fake.BrokerOAuthError = PermissionError
        fake.build_broker_verifier = Mock(return_value='verifier')
        fake.verified_actor = Mock(return_value='approved-uuid')
        with (patch.dict(sys.modules, {'broker_oauth': fake}),
              patch.object(probe, 'validated_signed_claims', return_value={
                  'sub': 'approved-uuid', 'scope': 'openid solverit:deliver'}),
              self.assertRaises(probe.LiveProbeError)):
            probe.check_signed_tokens(POLICY, 'positive', 'readonly', 'other')

    def test_wrong_subject_negative_not_accepted_as_evidence(self):
        fake = types.ModuleType('broker_oauth')
        fake.BrokerOAuthError = PermissionError
        fake.build_broker_verifier = Mock(return_value='verifier')
        fake.verified_actor = Mock(side_effect=['approved-uuid', PermissionError()])
        with (patch.dict(sys.modules, {'broker_oauth': fake}),
              patch.object(probe, 'validated_signed_claims', side_effect=[
                  {'sub': 'approved-uuid', 'scope': 'openid'},
                  {'sub': 'approved-uuid', 'scope': 'openid'}]),
              self.assertRaises(probe.LiveProbeError)):
            probe.check_signed_tokens(POLICY, 'positive', 'readonly', 'other')

    def test_negative_broker_acceptance_is_fatal(self):
        fake = types.ModuleType('broker_oauth')
        fake.BrokerOAuthError = PermissionError
        fake.build_broker_verifier = Mock(return_value='verifier')
        fake.verified_actor = Mock(return_value='approved-uuid')
        with (patch.dict(sys.modules, {'broker_oauth': fake}),
              patch.object(probe, 'validated_signed_claims', return_value={
                  'sub': 'approved-uuid', 'scope': 'openid'}),
              self.assertRaises(probe.LiveProbeError)):
            probe.check_signed_tokens(POLICY, 'positive', 'readonly', 'other')

    def test_unsigned_negative_control_cannot_pass(self):
        fakejwt = types.ModuleType('jwt')
        fakejwt.decode = Mock(return_value={'sub': 'another', 'scope': 'openid'})
        fakejwks = types.ModuleType('mcp_jwks_verifier')
        fakejwks.JWKSVerifierPolicy = Mock(return_value=object())
        verifier = Mock()
        verifier.verify.side_effect = PermissionError('invalid signature')
        fakejwks.CachedJWKSVerifier = Mock(return_value=verifier)
        with (patch.dict(sys.modules, {'jwt': fakejwt, 'mcp_jwks_verifier': fakejwks}),
              self.assertRaises(PermissionError)):
            probe.validated_signed_claims('fake.unsigned.jwt', POLICY)

    def test_main_never_logs_token_or_exception(self):
        output = StringIO()
        secret = 'SECRET-BEARER-NO-OUTPUT'
        with (patch.object(probe.os, 'geteuid', return_value=0),
              patch.object(probe, 'validate_staging'),
              patch.object(probe.importlib.util, 'spec_from_file_location', side_effect=ValueError(secret)),
              redirect_stdout(output)):
            self.assertEqual(probe.main(), 1)
        self.assertNotIn(secret, output.getvalue())
        self.assertIn('BROKER MUST STAY STOPPED', output.getvalue().upper())

    def test_script_has_no_provision_or_service_start(self):
        source = SCRIPT.read_text(encoding='utf-8')
        for forbidden in ('systemctl start', 'systemctl enable', 'systemctl restart',
                          'mint_token(', 'socket.bind(', 'shell=True', 'os.system(',
                          'traceback.print_exc', 'print(claims', 'print(token'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
