"""GitHub reader denies redirects, environment proxies and foreign hosts."""
import urllib.error
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request

import trusted_github_http as transport


class TrustedGitHubHTTPTests(unittest.TestCase):
    def test_only_fixed_api_github_get_is_allowed(self):
        for url, method in (
            ("http://api.github.com/repos/a/b", "GET"),
            ("https://evil.example/repos/a/b", "GET"),
            ("https://api.github.com.evil.example/repos/a/b", "GET"),
            ("https://api.github.com/repos/a/b", "POST"),
        ):
            with self.subTest(url=url, method=method), self.assertRaises(ValueError):
                transport.safe_open(Request(url, method=method), timeout=10)

    def test_redirect_handler_never_constructs_forwarded_request(self):
        handler = transport.NoRedirect()
        self.assertIsNone(handler.redirect_request(
            Request("https://api.github.com/repos/a/b",
                    headers={"Authorization": "Bearer temporary"}),
            None, 302, "Found", {}, "https://attacker.example/steal",
        ))

    def test_transport_installs_no_proxy_and_redirect_denial(self):
        fake = Mock()
        with patch.object(transport.urllib.request, "build_opener",
                          return_value=fake) as build:
            req = Request("https://api.github.com/repos/a/b")
            transport.safe_open(req, timeout=8)
        self.assertEqual(build.call_args.args[0].proxies, {})
        self.assertIsInstance(build.call_args.args[1], transport.NoRedirect)
        fake.open.assert_called_once_with(req, timeout=8)


if __name__ == "__main__":
    unittest.main()
