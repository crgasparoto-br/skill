"""Negative HTTP boundary checks without GitHub calls."""
import unittest
from test_mcp_http_local import HTTPMCPTests

class HTTPBoundaryTests(unittest.TestCase):
    setUpClass = classmethod(HTTPMCPTests.setUpClass.__func__)
    tearDownClass = classmethod(HTTPMCPTests.tearDownClass.__func__)
    request = HTTPMCPTests.request
    rpc = HTTPMCPTests.rpc
    headers = HTTPMCPTests.headers
    def test_browser_origin_rejected(self):
        status, _ = self.request(self.rpc(),
            {**self.headers(), "Origin": "https://example.invalid"})
        self.assertEqual(status, 403)

    def test_invalid_host_rejected(self):
        self.server.allow_ephemeral_host = False
        try:
            status, _ = self.request(self.rpc(), {**self.headers(), "Host": "attacker.example"})
            self.assertEqual(status, 403)
        finally:
            self.server.allow_ephemeral_host = True

if __name__ == "__main__":
    unittest.main()
