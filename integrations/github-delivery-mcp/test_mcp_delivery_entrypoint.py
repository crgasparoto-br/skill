"""Deliver-only HTTP MCP tool registration and middleware authorization gates."""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import mcp_delivery_entrypoint as delivery
from policy import PolicyDeniedError

SUB = "approved-subject"
REPO = "crgasparoto-br/training-system"
TOKEN = "signed-keycloak-access-token"
ENV = {
    "SOLVERIT_MCP_RESOURCE_URL": "https://mcp.example.com/mcp",
    "SOLVERIT_OAUTH_ISSUER_URL": "https://auth.example.com/realms/delivery",
    "SOLVERIT_OAUTH_JWKS_URI": "https://auth.example.com/realms/delivery/certs",
    "SOLVERIT_MCP_DELIVERY_SUBJECTS": SUB,
}


class MCPDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "jobs.sqlite3"
        self.db.touch(mode=0o600)
        self.root.chmod(0o700)
        self.db.chmod(0o600)

    def auth(self, **overrides):
        defaults = {
            "subject": SUB, "client_id": delivery.DELIVERY_CLIENT,
            "scopes": [delivery.DELIVERY_SCOPE], "token": TOKEN,
        }
        return SimpleNamespace(**(defaults | overrides))

    def test_requires_http_context_even_with_publicly_valid_args(self):
        with (patch.object(delivery, "get_access_token", return_value=None),
              patch.object(delivery, "_database_guard") as guard,
              patch.object(delivery, "enqueue_verified_delivery") as queue,
              self.assertRaises(PolicyDeniedError)):
            delivery.prepare_authenticated_workspace(
                repository=REPO, issue_number=499,
                idempotency_key="request", allowed_subjects=frozenset({SUB}))
            guard.assert_not_called()
            queue.assert_not_called()

    def test_missing_role_wrong_client_and_wrong_subject_never_touch_db(self):
        for changes in (
            {"subject": "unknown"}, {"client_id": "auditor-client"},
            {"scopes": ["solverit:read"]}, {"scopes": []},
            {"subject": None}, {"token": None},
        ):
            with (self.subTest(changes=changes),
                  patch.object(delivery, "get_access_token",
                               return_value=self.auth(**changes)),
                  patch.object(delivery, "_database_guard") as guard,
                  self.assertRaises(PolicyDeniedError)):
                delivery.prepare_authenticated_workspace(
                    repository=REPO, issue_number=499,
                    idempotency_key="req", allowed_subjects=frozenset({SUB}))
                guard.assert_not_called()

    def test_valid_http_context_binds_identity_from_middleware_not_parameters(self):
        result = {"job_id": "test-uuid", "status": "queued"}
        with (patch.object(delivery, "get_access_token", return_value=self.auth()),
              patch.object(delivery, "_database_guard", return_value=str(self.db)),
              patch.object(delivery, "enqueue_verified_delivery", return_value=result) as queue):
            returned = delivery.prepare_authenticated_workspace(
                repository=REPO, issue_number=499,
                idempotency_key="retry-499", allowed_subjects=frozenset({SUB}))
        self.assertEqual(returned, result)
        kwargs = queue.call_args.kwargs
        self.assertEqual(kwargs["principal"].subject, SUB)
        self.assertTrue(kwargs["principal"].oauth_verified)
        self.assertEqual(kwargs["mcp_access_token"], TOKEN)
        self.assertEqual(kwargs["database_path"], str(self.db))

    def test_private_database_requires_exact_owner_and_permissions(self):
        with patch.object(delivery, "CONTROLLER_DB_DIRECTORY", self.root), patch.object(
            delivery, "CONTROLLER_DATABASE", self.db
        ):
            if os.geteuid() in (0, 997, 1004):
                with self.assertRaises(PermissionError):
                    delivery._database_guard()  # noqa: SLF001 - security boundary tests
            else:
                self.assertEqual(delivery._database_guard(), str(self.db))  # noqa: SLF001 - security boundary tests
            self.db.chmod(0o644)
            with self.assertRaises(PermissionError):
                delivery._database_guard()  # noqa: SLF001 - security boundary tests

    async def test_only_two_bounded_tools_registered(self):
        config = ENV | {"SOLVERIT_CONTROLLER_DATABASE_PATH": str(delivery.CONTROLLER_DATABASE)}
        with (patch.object(delivery, "_database_guard", return_value=str(self.db)),
              patch.object(delivery, "CachedJWKSVerifier") as verifier):
            server = delivery.build_delivery_server(env=config)
        tools = await server.list_tools()
        self.assertEqual([t.name for t in tools], ["prepare_workspace", "get_job_status"])
        self.assertEqual(verifier.call_args.args[0].required_scope, "solverit:deliver")
        self.assertEqual(verifier.call_args.args[0].authorized_party,
                         "solverit-chatgpt-mcp")

    async def test_malformed_or_missing_configuration_is_refused(self):
        with self.assertRaises(RuntimeError):
            delivery.build_delivery_server(env={})

    async def test_invalid_bearer_not_accepted_as_subject(self):
        fake = SimpleNamespace(
            verify=lambda _token: (_ for _ in ()).throw(
                delivery.MCPTokenRejectedError("signature invalid")),
            policy=SimpleNamespace(issuer="https://id.example"),
        )
        verifier = delivery.DeliveryOAuthVerifier(fake, "https://mcp.example/mcp")
        self.assertIsNone(await verifier.verify_token("unsigned-invalid-bearer"))


if __name__ == "__main__":
    unittest.main()
