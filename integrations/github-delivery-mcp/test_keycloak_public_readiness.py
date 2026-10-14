"""Offline contract tests for the public OIDC readiness diagnostics."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent / "ops" / "check-keycloak-public-readiness.py"
SPEC = importlib.util.spec_from_file_location("check_keycloak_public_readiness", SCRIPT)
readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(readiness)


def good_discovery():
    return {
        "issuer": readiness.ISSUER,
        "jwks_uri": readiness.ISSUER + "/protocol/openid-connect/certs",
        "authorization_endpoint": readiness.ISSUER + "/protocol/openid-connect/auth",
        "token_endpoint": readiness.ISSUER + "/protocol/openid-connect/token",
        "code_challenge_methods_supported": ["S256", "plain"],
        "scopes_supported": ["openid", "solverit:read"],
    }


def good_jwks():
    return {"keys": [{"kid": "key1", "kty": "RSA", "use": "sig",
                      "alg": "RS256", "n": "base64url-modulus", "e": "AQAB"}]}


class PublicReadinessTests(unittest.TestCase):
    def test_baseline_checks_public_metadata_but_does_not_approve_write(self):
        result = readiness.validate_document(good_discovery(), good_jwks())
        self.assertEqual(result["issuer"], readiness.ISSUER)
        self.assertEqual(result["pkce_s256"], "supported")
        self.assertEqual(result["rs256_public_key_count"], 1)
        self.assertEqual(result["deliver_scope_advertised"], "no")
        self.assertNotIn("broker_enabled", result)
        self.assertNotIn("authorized_subjects", result)

    def test_wrong_issuer_refused(self):
        doc = good_discovery()
        doc["issuer"] = "https://attacker.invalid"
        with self.assertRaises(readiness.ReadinessError):
            readiness.validate_document(doc, good_jwks())

    def test_external_jwks_uri_refused(self):
        doc = good_discovery()
        doc["jwks_uri"] = "https://outside.invalid/keys"
        with self.assertRaises(readiness.ReadinessError):
            readiness.validate_document(doc, good_jwks())

    def test_missing_pkce_refused(self):
        doc = good_discovery()
        doc["code_challenge_methods_supported"] = ["plain"]
        with self.assertRaises(readiness.ReadinessError):
            readiness.validate_document(doc, good_jwks())

    def test_malformed_or_duplicate_rsa_keys_refused(self):
        for jwks in ({"keys": []}, {"keys": "bad"},
                     {"keys": [good_jwks()["keys"][0]] * 2}):
            with self.subTest(jwks=jwks), self.assertRaises(readiness.ReadinessError):
                readiness.validate_document(good_discovery(), jwks)

    def test_broken_endpoint_or_response_denied(self):
        doc = good_discovery()
        doc["token_endpoint"] = "http://auth.example.test/token"
        with self.assertRaises(readiness.ReadinessError):
            readiness.validate_document(doc, good_jwks())

    def test_real_network_not_needed_for_unit_tests(self):
        with patch.object(readiness, "fetch_json", side_effect=[
            good_discovery(), good_jwks(),
        ]) as fetch:
            evidence = readiness.inspect_public_endpoints()
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(evidence["deliver_scope_advertised"], "no")

    def test_advertised_scope_does_not_count_as_grant(self):
        doc = good_discovery()
        doc["scopes_supported"].append("solverit:deliver")
        evidence = readiness.validate_document(doc, good_jwks())
        self.assertEqual(evidence["deliver_scope_advertised"], "yes")
        self.assertNotIn("authorized_subjects", evidence)


if __name__ == "__main__":
    unittest.main()
