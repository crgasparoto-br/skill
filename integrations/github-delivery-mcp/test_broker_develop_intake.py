"""Broker intake validates OAuth-bound actor and issue before GitHub develop lookup."""
import unittest
from unittest.mock import Mock, patch

import broker_develop_intake as intake

REPO = "crgasparoto-br/training-system"
SHA = "a" * 40


class BrokerDevelopIntakeTests(unittest.TestCase):
    def test_authorized_read_does_not_return_installation_token(self):
        with (patch.object(intake, "mint_token", return_value="SECRET_GITHUB_TOKEN") as mint,
              patch.object(intake, "require_open_issue") as check,
              patch.object(intake, "GitHubDevelopResolver") as resolver):
            resolver.return_value = Mock(return_value=SHA)
            result = intake.inspect_issue_develop(
                actor="approved-uuid", repository=REPO, issue_number=499)
        self.assertEqual(result, {
            "ok": True, "repository": REPO, "issue_number": 499,
            "develop_sha": SHA, "verified_actor": "approved-uuid",
        })
        self.assertNotIn("SECRET_GITHUB_TOKEN", str(result))
        mint.assert_called_once_with(
            repository=REPO, operation="inspect-issue-develop", server_authorized=True)
        check.assert_called_once_with(
            repository=REPO, issue_number=499, token="SECRET_GITHUB_TOKEN")
        resolver.assert_called_once_with(
            token="SECRET_GITHUB_TOKEN", allowed_repositories=frozenset({REPO}))

    def test_repo_actor_number_rejected_before_secret_read(self):
        with patch.object(intake, "mint_token") as mint:
            for changes in (
                {"actor": ""}, {"actor": "x" * 257},
                {"repository": "other/repo"}, {"issue_number": True},
                {"issue_number": -1}, {"issue_number": "499"},
            ):
                with self.subTest(changes=changes), self.assertRaises(intake.IntakeDeniedError):
                    intake.inspect_issue_develop(**({
                        "actor": "approved-uuid", "repository": REPO,
                        "issue_number": 499,
                    } | changes))
            mint.assert_not_called()

    def test_invalid_issue_stops_before_git_ref_read(self):
        with (patch.object(intake, "mint_token", return_value="SECRET"),
              patch.object(intake, "require_open_issue", side_effect=ValueError("bad")),
              patch.object(intake, "GitHubDevelopResolver") as resolver,
              self.assertRaises(ValueError)):
            intake.inspect_issue_develop(
                actor="approved-uuid", repository=REPO, issue_number=499)
            resolver.assert_not_called()


if __name__ == "__main__":
    unittest.main()
