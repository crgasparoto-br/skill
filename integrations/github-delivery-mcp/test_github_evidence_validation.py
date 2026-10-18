"""GitHub checks are only matching data, never authorization to finalize."""
import unittest
from types import SimpleNamespace

from github_evidence_validation import (
    GitHubEvidenceRejected,
    require_github_evidence,
)


class GitHubEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.base = "a" * 40
        self.head = "b" * 40
        self.job = SimpleNamespace(
            repo="crgasparoto-br/skill", branch="feat/88-delivery",
            issue_number=88, base_sha=self.base, expected_head=self.head)
        self.pr = {"repository": self.job.repo, "head_branch": self.job.branch,
                       "base_branch": "develop", "state": "open", "merged": False,
                       "issue_number": 88, "head_sha": self.head}
        self.required = frozenset({"Validate repository", "Tests"})
        self.runs = [{"name": name, "head_sha": self.head, "status": "completed",
                          "conclusion": "success", "source": "github-check-runs"}
                     for name in sorted(self.required)]

    def check(self, **changes):
        args = {"job": self.job, "pull_request": self.pr,
                    "check_runs": self.runs, "required_checks": self.required}
        args.update(changes)
        return require_github_evidence(**args)

    def test_exact_head_passes_data_validation_only(self):
        self.assertEqual(self.check(), self.head)

    def test_wrong_base_rejected(self):
        with self.assertRaises(GitHubEvidenceRejected):
            self.check(pull_request=self.pr | {"base_branch": "main"})

    def test_wrong_issue_rejected(self):
        with self.assertRaises(GitHubEvidenceRejected):
            self.check(pull_request=self.pr | {"issue_number": 99})

    def test_stale_check_rejected(self):
        runs = [self.runs[0] | {"head_sha": self.base}, self.runs[1]]
        with self.assertRaises(GitHubEvidenceRejected):
            self.check(check_runs=runs)

    def test_pending_or_failed_rejected(self):
        for status, conclusion in (("in_progress", None), ("completed", "failure")):
            with self.subTest(status=status, conclusion=conclusion):
                with self.assertRaises(GitHubEvidenceRejected):
                    self.check(check_runs=[self.runs[0] | {
                        "status": status, "conclusion": conclusion}, self.runs[1]])

    def test_missing_check_rejected(self):
        with self.assertRaises(GitHubEvidenceRejected):
            self.check(check_runs=self.runs[:1])

    def test_duplicate_check_rejected(self):
        with self.assertRaises(GitHubEvidenceRejected):
            self.check(check_runs=[*self.runs, self.runs[0]])

    def test_empty_required_check_policy_rejected(self):
        with self.assertRaises(GitHubEvidenceRejected):
            self.check(required_checks=frozenset())

    def test_same_base_and_head_rejected(self):
        with self.assertRaises(GitHubEvidenceRejected):
            self.check(job=SimpleNamespace(**(vars(self.job) | {"base_sha": self.head})))
