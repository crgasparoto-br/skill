"""Negative HTTP boundary checks without GitHub calls."""
import json
import unittest
from unittest.mock import patch
from test_mcp_http_local import HTTPMCPTests

class HTTPBoundaryTests(HTTPMCPTests):
    def test_browser_origin_rejected(self):
        with patch("mcp_read_dispatch.authorize_http_request") as authorize:
            status, _ = self.request(self.rpc(),
                {**self.headers(), "Origin": "https://example.invalid"})
        self.assertEqual(status, 403)
        authorize.assert_not_called()

    def test_invalid_host_rejected(self):
        HTTPMCPTests.server.allow_ephemeral_host = False
        try:
            status, _ = self.request(self.rpc(), self.headers())
            self.assertEqual(status, 403)
        finally:
            HTTPMCPTests.server.allow_ephemeral_host = True

if __name__ == "__main__":
    unittest.main()
