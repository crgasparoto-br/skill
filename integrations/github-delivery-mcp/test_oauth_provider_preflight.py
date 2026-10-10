"""Static authorization server readiness checks (no network or credentials)."""
import unittest

from oauth_provider_preflight import validate_authorization_server_metadata

ISSUER = "https://auth.example.org/realms/solverit"
VALID = {
    "issuer": ISSUER,
    "authorization_endpoint": ISSUER + "/protocol/openid-connect/auth",
    "token_endpoint": ISSUER + "/protocol/openid-connect/token",
    "jwks_uri": ISSUER + "/protocol/openid-connect/certs",
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "response_types_supported": ["code"],
    "code_challenge_methods_supported": ["S256"],
    "registration_endpoint": ISSUER + "/clients-registrations/openid-connect",
}


class OAuthProviderReadinessTests(unittest.TestCase):
    def test_metadata_with_dcr_is_eligible_for_live_testing(self):
        self.assertEqual(validate_authorization_server_metadata(VALID, expected_issuer=ISSUER), [])

    def test_issuer_mismatch_blocks(self):
        self.assertIn("issuer mismatch", validate_authorization_server_metadata(
            VALID, expected_issuer="https://other.example.org"))

    def test_missing_pkce_blocks(self):
        metadata = {**VALID, "code_challenge_methods_supported": ["plain"]}
        self.assertTrue(any("PKCE" in issue for issue in
                            validate_authorization_server_metadata(metadata, expected_issuer=ISSUER)))

    def test_absent_registration_strategy_blocks(self):
        metadata = {key: value for key, value in VALID.items() if key != "registration_endpoint"}
        self.assertTrue(any("registration" in issue for issue in
                            validate_authorization_server_metadata(metadata, expected_issuer=ISSUER)))
        self.assertEqual(validate_authorization_server_metadata(
            metadata, expected_issuer=ISSUER, pre_registered_client=True), [])

    def test_non_https_metadata_endpoint_blocks(self):
        metadata = {**VALID, "token_endpoint": "http://localhost/token"}
        self.assertTrue(any("token_endpoint" in issue for issue in
                            validate_authorization_server_metadata(metadata, expected_issuer=ISSUER)))

    def test_malformed_discovery_arrays_block_without_crashing(self):
        for invalid in (None, "authorization_code", 42, {"code": True}, ["S256", 4]):
            for field in ("grant_types_supported", "response_types_supported", "code_challenge_methods_supported"):
                with self.subTest(field=field, invalid=invalid):
                    metadata = {**VALID, field: invalid}
                    self.assertTrue(validate_authorization_server_metadata(
                        metadata, expected_issuer=ISSUER)))

    def test_missing_refresh_grant_blocks_chatgpt_readiness(self):
        metadata = {**VALID, "grant_types_supported": ["authorization_code"]}
        self.assertTrue(any("refresh_token" in issue for issue in
                            validate_authorization_server_metadata(metadata, expected_issuer=ISSUER)))


if __name__ == "__main__":
    unittest.main()
