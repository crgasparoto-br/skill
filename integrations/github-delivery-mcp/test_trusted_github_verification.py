"""Verification uses persisted binding instead of an MCP-provided PR number."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobs import JobStore
from pr_binding import PRBindingStore
from trusted_github_verification import verify_bound_job, verify_with_github_app


class TrustedVerificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = str(Path(self.temp.name) / "jobs.sqlite3")
        self.jobs = JobStore(self.database)
        self.job = self.jobs.create(
            actor="operator", key="attempt", payload_hash=hashlib.sha256(b"request").hexdigest(),
            repo="crgasparoto-br/skill", issue_number=88, branch="feat/88-controlled",
            base_sha="a"*40, expected_head="b"*40,
        )
        self.args = {"database_path": self.database, "job_id": self.job.job_id,
                         "actor": "operator", "token": "read-token",
                         "required_checks": frozenset({"Validate repository"})}

    def prepare(self):
        self.jobs.transition(self.job.job_id, "operator", "queued", "running")
        self.jobs.transition(self.job.job_id, "operator", "running", "prepared")

    def test_missing_binding_denied_before_network(self):
        self.prepare()
        with patch("trusted_github_verification.fetch_and_validate_github") as fetch:
            with self.assertRaises(KeyError):
                verify_bound_job(**self.args)
            fetch.assert_not_called()

    def test_reads_persisted_pr_number(self):
        self.prepare()
        PRBindingStore(self.database).bind_published_pr(
            job_id=self.job.job_id, actor="operator", pr_number=89, head_sha="b"*40)
        with patch("trusted_github_verification.fetch_and_validate_github",
                   return_value="b"*40) as fetch:
            self.assertEqual(verify_bound_job(**self.args), "b"*40)
            self.assertEqual(fetch.call_args.kwargs["pr_number"], 89)
            self.assertEqual(fetch.call_args.kwargs["binding"].job_id, self.job.job_id)

    def test_other_actor_denied(self):
        self.prepare()
        with patch("trusted_github_verification.fetch_and_validate_github") as fetch:
            with self.assertRaises(KeyError):
                verify_bound_job(**(self.args | {"actor": "intruder"}))
            fetch.assert_not_called()

    def test_unprepared_denied(self):
        with patch("trusted_github_verification.fetch_and_validate_github") as fetch:
            with self.assertRaises(PermissionError):
                verify_bound_job(**self.args)
            fetch.assert_not_called()

class AppBrokerIntegrationTests(unittest.TestCase):
    setUp = TrustedVerificationTests.setUp
    prepare = TrustedVerificationTests.prepare
    def test_disallowed_repo_does_not_mint_token(self):
        self.prepare()
        with patch("trusted_github_verification.mint_token") as mint:
            with self.assertRaises(PermissionError):
                verify_with_github_app(**{k: v for k, v in self.args.items()
                                          if k != "token"})
            mint.assert_not_called()

    def test_broker_token_is_used_only_after_persisted_binding(self):
        self.prepare()
        PRBindingStore(self.database).bind_published_pr(
            job_id=self.job.job_id, actor="operator", pr_number=89, head_sha="b"*40)
        with patch("trusted_github_verification.ALLOWED_REPOSITORIES",
                   frozenset({"crgasparoto-br/skill"})), patch(
                       "trusted_github_verification.mint_token",
                       return_value="short-lived-token") as mint, patch(
                       "trusted_github_verification.fetch_and_validate_github",
                       return_value="b"*40) as fetch:
            args = {k: v for k, v in self.args.items() if k != "token"}
            self.assertEqual(verify_with_github_app(**args), "b"*40)
            mint.assert_called_once_with(
                repository="crgasparoto-br/skill", operation="read-checks",
                server_authorized=True)
            self.assertEqual(fetch.call_args.kwargs["token"], "short-lived-token")

    def test_missing_binding_prevents_mint(self):
        self.prepare()
        with patch("trusted_github_verification.ALLOWED_REPOSITORIES",
                   frozenset({"crgasparoto-br/skill"})), patch(
                       "trusted_github_verification.mint_token") as mint:
            args = {k: v for k, v in self.args.items() if k != "token"}
            with self.assertRaises(KeyError):
                verify_with_github_app(**args)
            mint.assert_not_called()
