"""Server-side identity verification tests; no external network calls."""
import json
import unittest
import urllib.error
from unittest.mock import patch

from github_oauth_identity import verify_github_user_token, IdentityVerificationError

TOKEN = "opaque-test-bearer-123456789"

class FakeResponse:
    def __init__(self, obj):
        self.data = json.dumps(obj).encode()
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self):
        return self.data

class IdentityTests(unittest.TestCase):
    def test_valid_verified_identity(self):
        with patch("github_oauth_identity.urllib.request.urlopen",
                   return_value=FakeResponse({"id": 123, "login": "tester"})) as http:
            principal = verify_github_user_token(TOKEN, allowed_github_ids=frozenset({123}))
        self.assertEqual(principal.subject, "github:123")
        self.assertTrue(principal.oauth_verified)
        self.assertIn("entregar-issue", principal.profiles)
        self.assertEqual(http.call_args.args[0].full_url, "https://api.github.com/user")

    def test_user_not_allowlisted(self):
        with patch("github_oauth_identity.urllib.request.urlopen",
                   return_value=FakeResponse({"id": 999})):
            with self.assertRaises(IdentityVerificationError):
                verify_github_user_token(TOKEN, allowed_github_ids=frozenset({123}))

    def test_no_allowlist_prevents_network(self):
        with patch("github_oauth_identity.urllib.request.urlopen") as http:
            with self.assertRaises(IdentityVerificationError):
                verify_github_user_token(TOKEN, allowed_github_ids=frozenset())
            http.assert_not_called()

    def test_invalid_token_prevents_network(self):
        with patch("github_oauth_identity.urllib.request.urlopen") as http:
            with self.assertRaises(IdentityVerificationError):
                verify_github_user_token("has spaces in bearer token", allowed_github_ids=frozenset({123}))
            http.assert_not_called()

    def test_http_authentication_failure(self):
        with patch("github_oauth_identity.urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError("https://api.github.com/user", 401, "unauthorized", {}, None)):
            with self.assertRaises(IdentityVerificationError):
                verify_github_user_token(TOKEN, allowed_github_ids=frozenset({123}))

    def test_boolean_user_id_rejected(self):
        with patch("github_oauth_identity.urllib.request.urlopen",
                   return_value=FakeResponse({"id": True})):
            with self.assertRaises(IdentityVerificationError):
                verify_github_user_token(TOKEN, allowed_github_ids=frozenset({123}))

if __name__ == "__main__":
    unittest.main()
