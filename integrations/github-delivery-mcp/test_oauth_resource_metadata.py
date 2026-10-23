"""OAuth protected-resource metadata contract tests; no secrets or network."""
import unittest

from oauth_resource_metadata import authenticate_challenge, resource_metadata


class MetadataTests(unittest.TestCase):
    def test_metadata_points_to_distinct_authorization_server(self):
        result = resource_metadata(
            resource_url="https://delivery.example.test/mcp",
            issuer_url="https://identity.example.test",
        )
        self.assertEqual(result["resource"], "https://delivery.example.test/mcp")
        self.assertEqual(result["authorization_servers"], ["https://identity.example.test"])
        self.assertEqual(result["bearer_methods_supported"], ["header"])

    def test_localhost_http_cannot_be_advertised_publicly(self):
        with self.assertRaises(ValueError):
            resource_metadata(resource_url="http://127.0.0.1:8769/mcp",
                              issuer_url="https://identity.example.test")

    def test_missing_issuer_rejected(self):
        with self.assertRaises(ValueError):
            resource_metadata(resource_url="https://delivery.example.test/mcp",
                              issuer_url="")

    def test_credentials_in_issuer_rejected(self):
        with self.assertRaises(ValueError):
            resource_metadata(resource_url="https://delivery.example.test/mcp",
                              issuer_url="https://user:pass@identity.example.test")

    def test_valid_challenge(self):
        self.assertEqual(
            authenticate_challenge(resource_metadata_url=
                "https://delivery.example.test/.well-known/oauth-protected-resource"),
            'Bearer resource_metadata="https://delivery.example.test/.well-known/oauth-protected-resource"',
        )

    def test_insecure_challenge_rejected(self):
        with self.assertRaises(ValueError):
            authenticate_challenge(resource_metadata_url=
                "http://delivery.example.test/.well-known/oauth-protected-resource")

if __name__ == "__main__":
    unittest.main()
