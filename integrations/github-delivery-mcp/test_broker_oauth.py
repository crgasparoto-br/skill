"""Issue 88: independent signed OAuth enforcement at private broker."""
import unittest
from unittest.mock import patch, Mock

import broker_oauth as auth
from mcp_jwks_verifier import CachedJWKSVerifier, JWKSVerifierPolicy
from mcp_jwt_verifier import MCPTokenRejectedError

POLICY = {
    "SOLVERIT_MCP_RESOURCE_URL": "https://delivery.example.test/mcp",
    "SOLVERIT_OAUTH_ISSUER_URL": "https://auth.example.test/realms/delivery",
    "SOLVERIT_OAUTH_JWKS_URI": "https://auth.example.test/realms/delivery/protocol/openid-connect/certs",
    "SOLVERIT_MCP_DELIVERY_SUBJECTS": "permitted-subject",
}


class BrokerOAuthTests(unittest.TestCase):
    def verifier(self):
        return CachedJWKSVerifier(JWKSVerifierPolicy(
            issuer=POLICY["SOLVERIT_OAUTH_ISSUER_URL"],
            audience=POLICY["SOLVERIT_MCP_RESOURCE_URL"],
            jwks_uri=POLICY["SOLVERIT_OAUTH_JWKS_URI"],
            allowed_subjects=frozenset({"permitted-subject"}),
            required_scope=auth.DELIVERY_SCOPE,
        ))

    def test_missing_config_fails_closed(self):
        for field in POLICY:
            with self.subTest(field=field):
                bad = dict(POLICY)
                bad.pop(field)
                with self.assertRaises(auth.BrokerOAuthDenied):
                    auth.build_broker_verifier(bad)

    def test_must_be_mcp_resource_and_pinned_issuer_jwks(self):
        for bad_value in ("https://delivery.example.test/anything", "http://delivery.example.test/mcp"):
            with self.subTest(bad_value=bad_value):
                with self.assertRaises((ValueError, auth.BrokerOAuthDenied)):
                    auth.build_broker_verifier({**POLICY, "SOLVERIT_MCP_RESOURCE_URL": bad_value})
        with self.assertRaises(ValueError):
            auth.build_broker_verifier({
                **POLICY, "SOLVERIT_OAUTH_JWKS_URI": "https://attacker.example.test/keys",
            })

    def test_delivery_scope_is_mandatory(self):
        with patch.object(CachedJWKSVerifier, "refresh", return_value=None):
            verified = auth.build_broker_verifier(POLICY)
        self.assertEqual(verified.policy.required_scope, "solverit:deliver")
        self.assertEqual(verified.policy.authorized_party, "solverit-chatgpt-mcp")
        self.assertEqual(verified.policy.allowed_subjects, frozenset({"permitted-subject"}))
        self.assertEqual(verified.policy.audience, POLICY["SOLVERIT_MCP_RESOURCE_URL"])

    def test_invalid_or_absent_access_tokens_fail_before_verify(self):
        verifier = self.verifier()
        with patch.object(verifier, "verify") as check:
            for token in (None, 1, "", "short", "a b c", "x" * 8193, "x\n" * 100,
                          "\u2603" * 200):
                with self.subTest(value=repr(token)[:40]):
                    with self.assertRaises(auth.BrokerOAuthDenied):
                        auth.verified_actor(token, verifier=verifier)
            check.assert_not_called()

    def test_wrong_verifier_type_denied(self):
        with self.assertRaises(auth.BrokerOAuthDenied):
            auth.verified_actor("validity-can-be-checked", verifier=Mock())

    def test_invalid_signature_subject_expiry_or_scope_fails_closed(self):
        verifier = self.verifier()
        with patch.object(verifier, "verify", side_effect=MCPTokenRejectedError("bad")):
            with self.assertRaises(auth.BrokerOAuthDenied):
                auth.verified_actor("signed-looking-token", verifier=verifier)

    def test_verified_subject_returned_only_after_crypto_verification(self):
        verifier = self.verifier()
        with patch.object(verifier, "verify", return_value="permitted-subject") as check:
            actor = auth.verified_actor("signed-looking-token", verifier=verifier)
            self.assertEqual(actor, "permitted-subject")
            check.assert_called_once_with("signed-looking-token")


if __name__ == "__main__":
    unittest.main()
