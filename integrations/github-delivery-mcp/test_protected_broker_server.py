"""Negative authorization and protected read-path regressions for Issue #88.

Offline only: all GitHub calls and installation-token minting are mocked.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import protected_broker_server as broker
from jobs import JobStore
from pr_binding import PRBindingStore

HEAD = "b" * 40


class FakeConnection:
    def __init__(self, request: bytes, *, uid: int = 2500):
        self.request = request
        self.uid = uid
        self.sent = bytearray()
        self.reads = 0

    def getsockopt(self, *_):
        return struct.pack("3i", 1234, self.uid, 2500)

    def settimeout(self, _seconds):
        pass

    def recv(self, _length):
        self.reads += 1
        request, self.request = self.request, b""
        return request

    def sendall(self, data):
        self.sent.extend(data)

    def response(self):
        return json.loads(self.sent.decode("utf-8"))


class ProtectedBrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "jobs.sqlite3"
        self.store = JobStore(str(self.db))
        self.job = self.store.create(
            actor="oauth-subject", key="first", payload_hash=hashlib.sha256(b"intent").hexdigest(),
            repo="crgasparoto-br/training-system", issue_number=88,
            branch="feat/88-delivery", base_sha="a" * 40,
            expected_head=HEAD,
        )
        self.request = {"version": 1, "operation": "verify_bound_ci",
                        "job_id": self.job.job_id,
                        "mcp_access_token": "test-signed-mcp-token"}
        self.verifier = object()
        oauth_patch = patch.object(broker, "verified_actor", return_value="oauth-subject")
        oauth_patch.start()
        self.addCleanup(oauth_patch.stop)

    def prepare_and_bind(self):
        self.store.transition(self.job.job_id, "oauth-subject", "queued", "running")
        self.store.transition(self.job.job_id, "oauth-subject", "running", "prepared")
        PRBindingStore(str(self.db)).bind_published_pr(
            job_id=self.job.job_id, actor="oauth-subject",
            pr_number=77, head_sha=HEAD,
        )

    def read_protected(self):
        return patch.multiple(broker, DATABASE=self.db, _protected_path=lambda *_a, **_k: None)

    def test_caller_must_be_exact_authenticated_controller_uid(self):
        with patch.object(broker, "verify_bound_ci") as verify:
            for uid in (0, 997, 1004, 2501):
                with self.subTest(uid=uid), self.assertRaises(broker.BrokerDenied):
                    broker.dispatch(self.request, peer_uid=uid, controller_uid=2500, verifier=self.verifier)
            verify.assert_not_called()

    def test_cannot_configure_worker_or_authenticator_as_controller(self):
        with patch.object(broker, "verify_bound_ci") as verify:
            for uid in (0, 997, 1004):
                with self.subTest(uid=uid), self.assertRaises(broker.BrokerDenied):
                    broker.dispatch(self.request, peer_uid=uid, controller_uid=uid, verifier=self.verifier)
            verify.assert_not_called()

    def test_only_fixed_read_operation_is_supported(self):
        with patch.object(broker, "verify_bound_ci") as verify:
            for op in ("mint_token", "publish-pr", "merge", "delete", "write", "open_pull_request"):
                with self.subTest(op=op), self.assertRaises(broker.BrokerDenied):
                    broker.dispatch({**self.request, "operation": op},
                                    peer_uid=2500, controller_uid=2500, verifier=self.verifier)
            verify.assert_not_called()

    def test_rejects_caller_supplied_identity_repository_pr_and_token(self):
        with patch.object(broker, "verify_bound_ci") as verify:
            for field in ("actor", "repository", "pr_number", "token",
                          "required_checks", "branch", "server_authorized"):
                with self.subTest(field=field), self.assertRaises(broker.BrokerDenied):
                    broker.dispatch({**self.request, field: "attacker"},
                                    peer_uid=2500, controller_uid=2500, verifier=self.verifier)
            verify.assert_not_called()

    def test_protocol_version_is_mandatory_and_exact(self):
        with patch.object(broker, "verify_bound_ci") as verify:
            for invalid in (None, 0, 2, True, "1"):
                with self.subTest(version=invalid), self.assertRaises(broker.BrokerDenied):
                    broker.dispatch({**self.request, "version": invalid},
                                    peer_uid=2500, controller_uid=2500, verifier=self.verifier)
            with self.assertRaises(broker.BrokerDenied):
                broker.dispatch({"operation": "verify_bound_ci", "job_id": self.job.job_id},
                                peer_uid=2500, controller_uid=2500, verifier=self.verifier)
            verify.assert_not_called()

    def test_rejects_invalid_job_ids(self):
        with patch.object(broker, "verify_bound_ci") as verify:
            for bad in (None, 1, "../tmp", "not-a-uuid", self.job.job_id.upper()):
                with self.subTest(bad=bad), self.assertRaises(broker.BrokerDenied):
                    broker.dispatch({**self.request, "job_id": bad},
                                    peer_uid=2500, controller_uid=2500, verifier=self.verifier)
            verify.assert_not_called()

    def test_rejects_worker_peer_before_reading_frame(self):
        fake = FakeConnection(b'{"operation":"verify_bound_ci"}\n', uid=1004)
        with patch.object(broker, "_read_frame") as reader:
            broker.serve_one(fake, controller_uid=2500, verifier=self.verifier)
            reader.assert_not_called()
        self.assertEqual(fake.reads, 0)
        self.assertEqual(fake.response(), {"ok": False, "error": "denied"})

    def test_server_redacts_internal_errors_and_tokens(self):
        fake = FakeConnection((json.dumps(self.request) + "\n").encode())
        with patch.object(broker, "verify_bound_ci",
                          side_effect=RuntimeError("SECRET_TOKEN_PRIVATE")):
            broker.serve_one(fake, controller_uid=2500, verifier=self.verifier)
        self.assertEqual(fake.response(), {"ok": False, "error": "denied"})
        self.assertNotIn(b"SECRET_TOKEN_PRIVATE", fake.sent)

    def test_rejects_oversized_and_multiple_request_frames(self):
        with patch.object(broker, "verify_bound_ci") as verify:
            for raw in (b"{" + b"x" * 2048 + b"}\n", b"{}\n{}\n"):
                fake = FakeConnection(raw)
                broker.serve_one(fake, controller_uid=2500, verifier=self.verifier)
                self.assertEqual(fake.response(), {"ok": False, "error": "denied"})
            verify.assert_not_called()

    def test_wrong_signed_subject_cannot_read_another_actors_job(self):
        self.prepare_and_bind()
        with self.read_protected(), patch.object(broker.os, "geteuid", return_value=997), \\
                patch.object(broker, "verified_actor", return_value="different-subject"), \\
                patch.object(broker, "mint_token") as mint:
            with self.assertRaises(broker.BrokerDenied):
                broker.dispatch(self.request, peer_uid=2500, controller_uid=2500,
                                verifier=self.verifier)
            mint.assert_not_called()

    def test_invalid_signed_token_rejected_before_database_read(self):
        with patch.object(broker, "verified_actor", side_effect=broker.BrokerDenied("invalid")), \\
                patch.object(broker, "verify_bound_ci") as verify:
            with self.assertRaises(broker.BrokerDenied):
                broker.dispatch(self.request, peer_uid=2500, controller_uid=2500,
                                verifier=self.verifier)
            verify.assert_not_called()

    def test_no_binding_does_not_mint_token(self):
        self.store.transition(self.job.job_id, "oauth-subject", "queued", "running")
        self.store.transition(self.job.job_id, "oauth-subject", "running", "prepared")
        with self.read_protected(), patch.object(broker.os, "geteuid", return_value=997), \
                patch.object(broker, "mint_token") as mint:
            with self.assertRaises(broker.BrokerDenied):
                broker.verify_bound_ci(self.job.job_id, actor="oauth-subject")
            mint.assert_not_called()

    def test_no_prepared_state_does_not_mint_token(self):
        with self.read_protected(), patch.object(broker.os, "geteuid", return_value=997), \
                patch.object(broker, "mint_token") as mint:
            with self.assertRaises(broker.BrokerDenied):
                broker.verify_bound_ci(self.job.job_id, actor="oauth-subject")
            mint.assert_not_called()

    def test_successful_read_exposes_no_installation_credential(self):
        self.prepare_and_bind()
        with self.read_protected(), patch.object(broker.os, "geteuid", return_value=997), \
                patch.object(broker, "mint_token", return_value="SECRET_TOKEN_PRIVATE") as mint, \
                patch.object(broker, "fetch_and_validate_github", return_value=HEAD) as fetch:
            result = broker.dispatch(self.request, peer_uid=2500, controller_uid=2500, verifier=self.verifier)
        mint.assert_called_once_with(
            repository="crgasparoto-br/training-system", operation="read-checks",
            server_authorized=True)
        self.assertEqual(fetch.call_args.kwargs["binding"].pr_number, 77)
        self.assertEqual(fetch.call_args.kwargs["required_checks"],
                         frozenset({"Validate repository"}))
        self.assertEqual(fetch.call_args.kwargs["token"], "SECRET_TOKEN_PRIVATE")
        self.assertEqual(result["verified_head"], HEAD)
        self.assertFalse(result["audit_verified"])
        self.assertNotIn("SECRET_TOKEN_PRIVATE", json.dumps(result))

    def test_different_verified_head_never_returns_success(self):
        self.prepare_and_bind()
        with self.read_protected(), patch.object(broker.os, "geteuid", return_value=997), \
                patch.object(broker, "mint_token", return_value="token"), \
                patch.object(broker, "fetch_and_validate_github", return_value="c" * 40):
            with self.assertRaises(broker.BrokerDenied):
                broker.verify_bound_ci(self.job.job_id, actor="oauth-subject")

    def test_store_is_read_only_and_never_created_on_missing_db(self):
        missing = Path(self.temp.name) / "missing.sqlite3"
        with patch.multiple(broker, DATABASE=missing, _protected_path=lambda *_a, **_k: None):
            with self.assertRaises(broker.BrokerDenied):
                broker._read_persisted_binding(self.job.job_id, actor="oauth-subject")
        self.assertFalse(missing.exists())

    def test_untrusted_temp_storage_rejected_before_sqlite(self):
        # /tmp ancestors are world writable; a temporary DB cannot impersonate
        # root-controlled production state.
        with patch.object(broker, "DATABASE", self.db), \
                patch.object(broker, "mint_token") as mint:
            with self.assertRaises(broker.BrokerDenied):
                broker._read_persisted_binding(self.job.job_id, actor="oauth-subject")
            mint.assert_not_called()


if __name__ == "__main__":
    unittest.main()
