"""Trusted ref lookup: repository allowlist, exact develop ref and failures."""
import io
import json
import unittest
from unittest.mock import Mock

from github_develop_resolver import GitHubDevelopResolver
from policy import PolicyDeniedError


class Response:
    status = 200

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size):
        return json.dumps(self.data).encode()[:size]


class DevelopResolverTests(unittest.TestCase):
    def setUp(self):
        self.document = {"ref": "refs/heads/develop",
                         "object": {"type": "commit", "sha": "a" * 40}}
        self.opener = Mock(side_effect=lambda req, timeout: Response(self.document))
        self.resolver = GitHubDevelopResolver(
            token="fake-local-token",
            allowed_repositories=frozenset({"crgasparoto-br/training-system"}),
            opener=self.opener,
        )

    def test_exact_api_ref_and_sha(self):
        self.assertEqual(self.resolver("crgasparoto-br/training-system"), "a" * 40)
        request = self.opener.call_args.args[0]
        self.assertEqual(request.full_url,
                         "https://api.github.com/repos/crgasparoto-br/training-system/git/ref/heads/develop")
        self.assertEqual(request.get_header("Authorization"), "Bearer fake-local-token")
        self.assertEqual(self.opener.call_args.kwargs["timeout"], 10)

    def test_unlisted_repo_never_network(self):
        with self.assertRaises(PolicyDeniedError):
            self.resolver("attacker/unknown")
        self.opener.assert_not_called()

    def test_invalid_response_ref_denied(self):
        self.document["ref"] = "refs/heads/main"
        with self.assertRaises(RuntimeError):
            self.resolver("crgasparoto-br/training-system")

    def test_invalid_sha_denied(self):
        self.document["object"]["sha"] = "not-sha"
        with self.assertRaises(RuntimeError):
            self.resolver("crgasparoto-br/training-system")

    def test_non_commit_ref_denied(self):
        self.document["object"]["type"] = "tag"
        with self.assertRaises(RuntimeError):
            self.resolver("crgasparoto-br/training-system")

    def test_network_failure_denied(self):
        self.opener.side_effect = TimeoutError()
        with self.assertRaises(RuntimeError):
            self.resolver("crgasparoto-br/training-system")

    def test_no_token_denied(self):
        with self.assertRaises(ValueError):
            GitHubDevelopResolver(token="", allowed_repositories=frozenset({"a/b"}))
