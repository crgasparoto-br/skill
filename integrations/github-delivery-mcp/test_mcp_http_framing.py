"""HTTP request smuggling hardening checks using real loopback TCP."""
import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer

from mcp_http_local import MCPHandler

class HTTPFramingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MCPHandler)
        cls.server.allow_ephemeral_host = True
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=3)

    def send(self, extra):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=3)
        connection.putrequest("POST", "/mcp", skip_host=True)
        connection.putheader("Host", "127.0.0.1")
        for key, val in extra:
            connection.putheader(key, val)
        connection.endheaders(b"{}" if ("Content-Length", "2") in extra else None)
        response = connection.getresponse()
        status = response.status
        response.read()
        connection.close()
        return status

    def test_duplicate_host_denied(self):
        self.assertEqual(self.send([("Host", "attacker.invalid")]), 403)

    def test_duplicate_content_length_denied(self):
        self.assertEqual(self.send([("Content-Type", "application/json"),
                                    ("Content-Length", "0"),
                                    ("Content-Length", "0")]), 400)

    def test_transfer_encoding_denied(self):
        self.assertEqual(self.send([("Transfer-Encoding", "chunked"),
                                    ("Content-Length", "0")]), 400)

    def test_normal_frame_still_reaches_auth_guard(self):
        self.assertEqual(self.send([("Content-Type", "application/json"),
                                    ("Content-Length", "2")]), 503)

if __name__ == "__main__":
    unittest.main()
