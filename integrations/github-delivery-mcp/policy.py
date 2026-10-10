"""Fail-closed policy boundary for the issue-delivery control plane.

This module does not authenticate requests. Callers MUST provide a verified principal
from server-side OAuth middleware, never from an MCP tool argument or issue text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import FrozenSet

_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH = re.compile(r"^feat/[0-9]+-[a-z0-9][a-z0-9-]{0,70}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_FORBIDDEN_NAMES = frozenset({".env", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"})
_FORBIDDEN_SEGMENTS = frozenset({".github", ".git", ".ssh", "secrets"})
_WRITE_ACTIONS = frozenset({
    "prepare_workspace", "inspect_workspace", "apply_patch",
    "run_allowed_checks", "get_job_status", "get_job_logs",
    "publish_branch", "open_pull_request"
})


class PolicyDenied(PermissionError):
    """Safe error; never include credentials or repository file content."""


@dataclass(frozen=True)
class VerifiedPrincipal:
    """Created ONLY by trusted OAuth verification middleware."""
    subject: str
    profiles: FrozenSet[str]
    oauth_verified: bool


@dataclass(frozen=True)
class DeliveryPolicy:
    allowed_users: FrozenSet[str]
    allowed_repos: FrozenSet[str]
    max_file_bytes: int = 262_144

    def authorize(self, principal: VerifiedPrincipal | None, action: str, repo: str,
                  branch: str, *, path: str | None = None,
                  expected_head: str | None = None, size: int | None = None) -> None:
        if (principal is None or not principal.oauth_verified
                or principal.subject not in self.allowed_users
                or "entregar-issue" not in principal.profiles):
            raise PolicyDenied("write profile not authorized")
        if action not in _WRITE_ACTIONS:
            raise PolicyDenied("operation not allowed")
        if not _REPO.fullmatch(repo) or repo not in self.allowed_repos:
            raise PolicyDenied("repository not allowed")
        if not _BRANCH.fullmatch(branch):
            raise PolicyDenied("work branch not allowed")
        if expected_head is None or not _SHA.fullmatch(expected_head):
            raise PolicyDenied("verified HEAD SHA required")
        if path is not None:
            self.validate_path(path)
        if size is not None and (size < 0 or size > self.max_file_bytes):
            raise PolicyDenied("content size exceeds limit")

    @staticmethod
    def validate_path(path: str) -> None:
        if not path or "\\" in path or "\x00" in path or path.startswith("/"):
            raise PolicyDenied("invalid repository path")
        parts = PurePosixPath(path).parts
        if (any(segment in ("", ".", "..") for segment in path.split("/"))
                or any(segment.lower() in _FORBIDDEN_SEGMENTS for segment in parts)
                or parts[-1].lower() in _FORBIDDEN_NAMES
                or parts[-1].lower().endswith((".pem", ".key", ".p12", ".pfx"))
                or len(path) > 240):
            raise PolicyDenied("repository path forbidden")


def require_unchanged_head(expected_head: str, observed_head: str) -> None:
    """Invoke immediately before publication, within an atomic compare-and-swap."""
    if not _SHA.fullmatch(expected_head) or observed_head != expected_head:
        raise PolicyDenied("concurrent HEAD update detected")
