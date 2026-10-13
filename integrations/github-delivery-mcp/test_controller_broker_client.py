"""Local IPC client never trusts Unix socket path or unsourced CI evidence."""
import json
import socket
import struct
import unittest
from unittest.mock import patch

import controller_broker_client as client

JOB = "11111111-1111-4111-8111-111111111111"
GOOD = {"ok": True, "job_id": JOB, "verified_head": "b"*40,
        "ci_verified": True, "audit_verified": False}


class SocketStub:
    def __init__(self, response, uid=997):
        self.response = response
        self.uid = uid
        self.sent = []
        self.reads = 0
        self.connect_path = None
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def settimeout(self, duration):
        assert duration > 0
    def connect(self, path):
        self.connect_path = path
    def getsockopt(self, *args):
        return struct.pack("3i", 15, self.uid, 10)
    def sendall(self, data):
        self.sent.append(data)
    def recv(self, size):
        self.reads += 1
        data, self.response = self.response, b""
        return data


class ControllerBrokerClientTests(unittest.TestCase):
    def check(self, response, uid=997):
        sock = SocketStub(response, uid)
        with patch.object(client.socket, "socket", return_value=sock):
            result = client.check_job_ci(
                job_id=JOB, mcp_access_token="signed-keycloak-access")
        return result, sock

    def test_success_returns_only_unprivileged_evidence(self):
        result, sock = self.check(json.dumps(GOOD).encode() + b"\n")
        self.assertEqual(result, GOOD)
        self.assertEqual(sock.connect_path, str(client.SOCKET))
        data = json.loads(sock.sent[0].decode())
        self.assertEqual(data["operation"], "verify_bound_ci")
        self.assertEqual(data["mcp_access_token"], "signed-keycloak-access")
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["job_id"], JOB)
        self.assertNotIn("token", result)

    def test_other_peer_uid_refused_before_request_sends(self):
        sock = SocketStub(json.dumps(GOOD).encode() + b"\n", uid=1004)
        with patch.object(client.socket, "socket", return_value=sock):
            with self.assertRaises(client.BrokerClientError):
                client.check_job_ci(job_id=JOB, mcp_access_token="signed-keycloak-access")
        self.assertEqual(sock.sent, [])

    def test_ambiguous_invalid_or_missing_reply_rejected(self):
        samples = [b"", b"{}\n", b"{invalid}\n",
                   json.dumps({**GOOD, "audit_verified": True}).encode()+b"\n",
                   json.dumps({**GOOD, "job_id": "22222222-2222-4222-8222-222222222222"}).encode()+b"\n",
                   json.dumps({**GOOD, "verified_head": "x"*40}).encode()+b"\n",
                   json.dumps({**GOOD, "token": "SECRETS"}).encode()+b"\n",
                   json.dumps(GOOD).encode()+b"\n{}\n",
                   b"a"*5000+b"\n"]
        for raw in samples:
            with self.subTest(value=raw[:30]), self.assertRaises(client.BrokerClientError):
                self.check(raw)

    def test_bad_user_inputs_refused_before_socket_connect(self):
        with patch.object(client.socket, "socket") as open_socket:
            for job in ("", "not-a-job", JOB.upper(), "../../../passwd"):
                with self.subTest(job=job), self.assertRaises(client.BrokerClientError):
                    client.check_job_ci(job_id=job, mcp_access_token="signed-keycloak-access")
            for token in (None, "", "short", "bad token", "x"*8193):
                with self.subTest(token=repr(token)[:20]), self.assertRaises(client.BrokerClientError):
                    client.check_job_ci(job_id=JOB, mcp_access_token=token)
            open_socket.assert_not_called()


if __name__ == "__main__":
    unittest.main()
