"""Read-only trusted GitHub intake in the credential-isolated broker.

The approved Keycloak actor is already verified by the Unix-socket dispatch.
No persistence, checkout or GitHub mutation is performed in this operation.
"""
from __future__ import annotations

from app_token_broker import ALLOWED_REPOSITORIES, mint_token
from github_develop_resolver import GitHubDevelopResolver
from github_issue_reader import ISSUE_LIMIT, require_open_issue
from trusted_github_http import safe_open

PILOT_REPOSITORY = "crgasparoto-br/training-system"


class IntakeDeniedError(PermissionError):
    """Never include user input, token, HTTP response body or remote issue text."""


def inspect_issue_develop(*, actor: str, repository: str, issue_number: int) -> dict[str, object]:
    if (not isinstance(actor, str) or not actor or len(actor) > 256
            or repository != PILOT_REPOSITORY or repository not in ALLOWED_REPOSITORIES
            or type(issue_number) is not int or not 1 <= issue_number <= ISSUE_LIMIT):
        raise IntakeDeniedError("issue preparation not authorized")
    # The only GitHub capability used is repository-scoped issues:read and
    # contents:read. The bearer remains inside the authenticator process.
    token = mint_token(repository=repository, operation="inspect-issue-develop",
                       server_authorized=True)
    require_open_issue(repository=repository, issue_number=issue_number, token=token)
    resolver = GitHubDevelopResolver(token=token, allowed_repositories=frozenset({repository}),
                                     opener=safe_open)
    sha = resolver(repository)
    return {"ok": True, "repository": repository, "issue_number": issue_number,
            "develop_sha": sha, "verified_actor": actor}
