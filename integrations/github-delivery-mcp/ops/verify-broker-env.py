#!/usr/bin/env python3
"""Issue 88: independently verify staged broker policy without exposing it.

Read-only, root-only. Does not start services, authenticate users,
read Keycloak tokens, or print the approved OIDC subject.
"""
from __future__ import annotations

import os
import stat
import sys
import uuid
from pathlib import Path

POLICY = Path("/etc/solverit/issue-delivery/broker.env")
FIXED = {
    "SOLVERIT_BROKER_CONTROLLER_UID": "995",
    "SOLVERIT_BROKER_SOCKET_GID": "984",
    "SOLVERIT_OAUTH_ISSUER_URL":
        "https://auth.solveritconsultoria.com.br/realms/solverit-delivery",
    "SOLVERIT_OAUTH_JWKS_URI":
        "https://auth.solveritconsultoria.com.br/realms/solverit-delivery/protocol/openid-connect/certs",
    "SOLVERIT_MCP_RESOURCE_URL":
        "https://mcp.solveritconsultoria.com.br/mcp",
}
SUBJECT_KEY = "SOLVERIT_MCP_DELIVERY_SUBJECTS"
MAX_BYTES = 2048


class InvalidBrokerPolicyError(ValueError):
    pass


def canonical_subject(value: str) -> bool:
    if not isinstance(value, str) or not value.isascii() or len(value) != 36:
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.int != 0 and str(parsed) == value


def check_contents(raw: bytes) -> None:
    """Validate exact keys and policy literals without emitting any value."""
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise InvalidBrokerPolicyError("invalid size")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise InvalidBrokerPolicyError("invalid encoding") from exc
    if not text.endswith("\n"):
        raise InvalidBrokerPolicyError("missing final newline")
    lines = text.splitlines()
    fields: dict[str, str] = {}
    for line in lines:
        if line.count("=") != 1:
            raise InvalidBrokerPolicyError("invalid policy syntax")
        key, value = line.split("=", 1)
        if not key or key in fields:
            raise InvalidBrokerPolicyError("duplicate or empty field")
        fields[key] = value
    if set(fields) != set(FIXED) | {SUBJECT_KEY}:
        raise InvalidBrokerPolicyError("unexpected environment keys")
    if any(fields[key] != expected for key, expected in FIXED.items()):
        raise InvalidBrokerPolicyError("policy mismatch")
    if not canonical_subject(fields[SUBJECT_KEY]):
        raise InvalidBrokerPolicyError("invalid authorized subject")


def inspect(path: Path = POLICY) -> None:
    if os.geteuid() != 0:
        raise InvalidBrokerPolicyError("root required")
    for part in (path.parent, *path.parent.parents):
        mode = os.lstat(part)
        if (not stat.S_ISDIR(mode.st_mode)
                or mode.st_uid != 0 or mode.st_mode & 0o022):
            raise InvalidBrokerPolicyError("unsafe parent directory")
    st = os.lstat(path)
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != 0
            or st.st_gid != 0 or stat.S_IMODE(st.st_mode) != 0o600):
        raise InvalidBrokerPolicyError("unsafe file ownership or permissions")
    # Open without symlink traversal and check identity again to reduce races.
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev != st.st_dev or opened.st_ino != st.st_ino
                or opened.st_uid != 0 or opened.st_gid != 0
                or stat.S_IMODE(opened.st_mode) != 0o600):
            raise InvalidBrokerPolicyError("file identity changed")
        raw = os.read(fd, MAX_BYTES + 1)
        check_contents(raw)
    finally:
        os.close(fd)


def main() -> int:
    try:
        inspect()
    except (OSError, InvalidBrokerPolicyError):
        print("RESULT: BLOCKED — private broker environment failed verification")
        return 1
    print("RESULT: PASS — broker.env owner root:root, mode 0600, exact policy keys")
    print("RESULT: PASS — immutable OIDC subject format (value not printed)")
    print("PENDING: real signed-token validation and negative IPC security tests")
    print("Broker remains inactive; no service activation performed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
