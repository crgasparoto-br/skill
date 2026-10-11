"""Read-only adapter must reject missing authoritative issue linkage."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from github_evidence_reader import (
    GitHubEvidenceRejected, fetch_and_validate_github, _get_json,
)


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.job = SimpleNamespace(repo="crgasparoto-br/skill",
                                   branch="feat/88-delivery", issue_number=88,
                                   base_sha="a"*40, expected_head="b"*40)
        self.pr = {
            "number": 89, "state": "open", "merged": False,
            "head": {"sha": "b"*40, "ref": "feat/88-delivery",
                     "repo": {"full_name": "crgasparoto-br/skill"}},
            "base": {"ref": "develop", "repo": {"full_name": "crgasparoto-br/skill"}},
        }
        self.checks = {"total_count": 1, "check_runs": [
            {"name": "Validate repository", "head_sha": "b"*40,
             "status": "completed", "conclusion": "success"}]}

    def test_unverified_issue_relation_denied_even_with_green_ci(self):
        with patch("github_evidence_reader._get_json",
                   side_effect=[self.pr, self.checks]) as get:
            with self.assertRaisesRegex(GitHubEvidenceRejected, "PR identity"):
                fetch_and_validate_github(
                    job=self.job, pr_number=89, token="read-only-token",
                    required_checks=frozenset({"Validate repository"}))
            self.assertEqual(get.call_count, 2)

    def test_missing_token_denied_before_network(self):
        with self.assertRaises(GitHubEvidenceRejected):
            _get_json(token="", repo="crgasparoto-br/skill", suffix="/pulls/89")

    def test_invalid_pr_id_denied_before_network(self):
        with patch("github_evidence_reader._get_json") as get:
            with self.assertRaises(GitHubEvidenceRejected):
                fetch_and_validate_github(job=self.job, pr_number=True,
                                          token="token", required_checks=frozenset({"x"}))
            get.assert_not_called()

    def test_cross_repository_pr_denied(self):
        pr = json.loads(json.dumps(self.pr))
        pr["head"]["repo"]["full_name"] = "other/fork"
        with patch("github_evidence_reader._get_json", return_value=pr) as get:
            with self.assertRaisesRegex(GitHubEvidenceRejected, "repository"):
                fetch_and_validate_github(job=self.job, pr_number=89,
                                          token="token", required_checks=frozenset({"x"}))
            get.assert_called_once()

    def test_incomplete_check_pagination_denied(self):
        with patch("github_evidence_reader._get_json",
                   side_effect=[self.pr, {"total_count": 101, "check_runs": []}]):
            with self.assertRaisesRegex(GitHubEvidenceRejected, "pagination"):
                fetch_and_validate_github(job=self.job, pr_number=89,
                                          token="token", required_checks=frozenset({"x"}))
