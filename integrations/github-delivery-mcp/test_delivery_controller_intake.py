"""Authenticated controller intake -> broker inspection -> durable SQLite intent."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import delivery_controller_intake as controller
from jobs import JobConflictError, JobStore
from policy import PolicyDeniedError, VerifiedPrincipal

REPO = "crgasparoto-br/training-system"
SUB = "approved-keycloak-sub"
SHA = "a" * 40


class ControllerIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "jobs.sqlite3")
        self.params = {
            "database_path": self.db,
            "principal": VerifiedPrincipal(SUB, frozenset({"entregar-issue"}), True),
            "allowed_subjects": frozenset({SUB}), "repository": REPO,
            "issue_number": 499, "idempotency_key": "request-499",
            "mcp_access_token": "signed-delivery-token",
        }

    def test_broker_verified_develop_enqueues_only_once_without_execution(self):
        with patch.object(controller, "inspect_authorized_issue", return_value=SHA) as inspect:
            first = controller.enqueue_verified_delivery(**self.params)
            second = controller.enqueue_verified_delivery(**self.params)
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertEqual(first["status"], "queued")
        self.assertEqual(first["base_sha"], SHA)
        self.assertEqual(first["branch"], "feat/499-delivery")
        inspect.assert_called_with(
            repository=REPO, issue_number=499,
            verified_actor=SUB, mcp_access_token="signed-delivery-token")
        self.assertEqual(JobStore(self.db).read(first["job_id"], SUB).status, "queued")
        self.assertNotIn("signed-delivery-token", repr(first))

    def test_forged_identity_missing_profile_and_repo_never_reach_broker(self):
        with patch.object(controller, "inspect_authorized_issue") as inspect:
            for different in (
                {"principal": None},
                {"principal": VerifiedPrincipal(SUB, frozenset({"entregar-issue"}), False)},
                {"principal": VerifiedPrincipal("attacker", frozenset({"entregar-issue"}), True)},
                {"principal": VerifiedPrincipal(SUB, frozenset(), True)},
                {"allowed_subjects": frozenset()},
                {"repository": "crgasparoto-br/solverfin"},
                {"issue_number": True},
                {"issue_number": 0},
                {"idempotency_key": ""},
            ):
                with self.subTest(different=different), self.assertRaises(PolicyDeniedError):
                    controller.enqueue_verified_delivery(**(self.params | different))
            inspect.assert_not_called()
            self.assertFalse(Path(self.db).exists())

    def test_broker_denial_does_not_create_job(self):
        with patch.object(controller, "inspect_authorized_issue",
                          side_effect=PermissionError("broker rejected token")):
            with self.assertRaises(PermissionError):
                controller.enqueue_verified_delivery(**self.params)
        self.assertFalse(Path(self.db).exists())

    def test_reused_key_after_branch_head_change_fails_closed(self):
        with patch.object(controller, "inspect_authorized_issue",
                          side_effect=[SHA, "b" * 40]):
            controller.enqueue_verified_delivery(**self.params)
            with self.assertRaises(JobConflictError):
                controller.enqueue_verified_delivery(**self.params)


if __name__ == "__main__":
    unittest.main()
