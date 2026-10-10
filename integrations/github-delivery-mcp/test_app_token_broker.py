"""Broker authorization unit tests; no actual PEM or GitHub network calls."""
import json
import unittest
from unittest.mock import patch

import app_token_broker as broker


class BrokerTests(unittest.TestCase):
    def test_unauthorized_request_never_reads_key(self):
        with patch.object(broker, "_make_jwt") as sign, self.assertRaises(PermissionError):
                broker.mint_token(repository="crgasparoto-br/training-system",
                                  operation="read-issue")
            sign.assert_not_called()

    def test_other_repository_rejected(self):
        with patch.object(broker, "_make_jwt") as sign, self.assertRaises(PermissionError):
                broker.mint_token(repository="crgasparoto-br/solverfin",
                                  operation="read-issue", server_authorized=True)
            sign.assert_not_called()

    def test_unknown_operation_rejected(self):
        with patch.object(broker, "_make_jwt") as sign, self.assertRaises(PermissionError):
                broker.mint_token(repository="crgasparoto-br/training-system",
                                  operation="admin", server_authorized=True)
            sign.assert_not_called()

    def test_wrong_process_identity_rejected(self):
        with patch.object(broker.os, "geteuid", return_value=1004), \
             patch.object(broker, "_make_jwt") as sign:
            with self.assertRaises(PermissionError):
                broker.mint_token(repository="crgasparoto-br/training-system",
                                  operation="read-issue", server_authorized=True)
            sign.assert_not_called()

    def test_minimal_read_token(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({
                    "repositories": [{"full_name": "crgasparoto-br/training-system"}],
                    "permissions": {"contents": "read", "metadata": "read"},
                    "token": "mock-token",
                }).encode()
        # A read-issue operation must NOT accept a token with contents permission.
        with patch.object(broker.os, "geteuid", return_value=997), \
             patch.object(broker, "_make_jwt", return_value="jwt"), \
             patch.object(broker.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaises(RuntimeError):
                broker.mint_token(repository="crgasparoto-br/training-system",
                                  operation="read-issue", server_authorized=True)

    def test_scoped_token_returned_without_logging(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return json.dumps({
                    "repositories": [{"full_name": "crgasparoto-br/training-system"}],
                    "permissions": {"issues": "read", "metadata": "read"},
                    "token": "mock-secret",
                }).encode()
        with patch.object(broker.os, "geteuid", return_value=997), \
             patch.object(broker, "_make_jwt", return_value="jwt"), \
             patch.object(broker.urllib.request, "urlopen", return_value=Response()):
            token = broker.mint_token(repository="crgasparoto-br/training-system",
                                      operation="read-issue", server_authorized=True)
        self.assertEqual(token, "mock-secret")


if __name__ == "__main__":
    unittest.main()
