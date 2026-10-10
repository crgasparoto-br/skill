"""Authorization boundary for an authenticated MCP transport.

The transport must verify OAuth access tokens using a trusted provider and
construct VerifiedPrincipal server-side. Never accept identities or profiles
from MCP tool parameters, issue text, or client-supplied headers.

This module issues no GitHub token. It returns a narrowly scoped *decision*
that cannot be serialized as a bearer credential.
"""
from dataclasses import dataclass

from policy import DeliveryPolicy, PolicyDeniedError, VerifiedPrincipal

PILOT_REPOSITORY = "crgasparoto-br/training-system"



@dataclass(frozen=True)
class AuthorizedOperation:
    subject: str
    repository: str
    action: str
    branch: str
    expected_head: str

def authorize_operation(*, principal: VerifiedPrincipal, action: str,
                        repository: str, branch: str, expected_head: str,
                        allowed_subjects: frozenset[str]) -> AuthorizedOperation:
    if not allowed_subjects:
        raise PolicyDeniedError("no authorized users configured")
    policy = DeliveryPolicy(
        allowed_users=allowed_subjects,
        allowed_repos=frozenset({PILOT_REPOSITORY}),
    )
    policy.authorize(principal, action, repository, branch,
                     expected_head=expected_head)
    return AuthorizedOperation(principal.subject, repository, action,
                               branch, expected_head)

def authorize_token_operation(decision: AuthorizedOperation, *,
                              requested_operation: str) -> None:
    """Explicit action mapping prevents converting read decisions to write."""
    required_action = {
        "read-issue": "prepare_workspace",
        "read-checks": "run_allowed_checks",
        "publish-pr": "open_pull_request",
    }.get(requested_operation)
    if required_action is None or decision.action != required_action:
        raise PolicyDeniedError("requested token exceeds authorized operation")
