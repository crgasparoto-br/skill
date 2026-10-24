#!/usr/bin/env python3
"""Issue 88: gated, write-once, root-owned staging broker policy.

This creates ONLY /etc/solverit/issue-delivery/broker.env. No systemd
actions, no Keycloak admin writes, no tokens, and no GitHub credentials.
Requires operator-reviewed positive/negative Keycloak Evaluate evidence.
Does not replace independent verification using a signed access token.
"""
from __future__ import annotations

import argparse
import getpass
import grp
import os
import pwd
import stat
import sys
import uuid
from pathlib import Path

ENV_DIR = Path("/etc/solverit/issue-delivery")
ENV_PATH = ENV_DIR / "broker.env"
CONTROLLER_UID = 995
AUTH_UID = 997
WORKER_UID = 1004
BROKER_GID = 984
ISSUER = "https://auth.solveritconsultoria.com.br/realms/solverit-delivery"
RESOURCE = "https://mcp.solveritconsultoria.com.br/mcp"
JWKS = ISSUER + "/protocol/openid-connect/certs"
APPROVAL = "CONFIRMADO"


class ProvisionDeniedError(ValueError):
    """Generic failure: never include the sensitive approved subject."""


def subject_is_canonical(value: str) -> bool:
    """Keycloak subject must be a canonical UUID, not a login or email."""
    if not isinstance(value, str) or not value.isascii() or len(value) != 36:
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return str(parsed) == value and parsed.int != 0


def assert_unchanged_service_identities() -> None:
    expected = {
        "solverit-controller": CONTROLLER_UID,
        "solverit-github-auth": AUTH_UID,
        "solverit-worker": WORKER_UID,
    }
    for name, uid in expected.items():
        if pwd.getpwnam(name).pw_uid != uid:
            raise ProvisionDeniedError("service UID mismatch")
    group = grp.getgrnam("solverit-delivery-control")
    if group.gr_gid != BROKER_GID or set(group.gr_mem) != {
        "solverit-controller", "solverit-github-auth"
    }:
        raise ProvisionDeniedError("broker group mismatch")
    app_group = grp.getgrnam("solverit-app-key")
    if ("solverit-controller" in app_group.gr_mem
            or "solverit-worker" in app_group.gr_mem):
        raise ProvisionDeniedError("untrusted account in application key group")


def assert_secure_dir(path: Path) -> None:
    """Root-owned, no symlink or group/world write on path and ancestors."""
    if not path.is_absolute():
        raise ProvisionDeniedError("env directory must be absolute")
    for ancestor in (path, *path.parents):
        try:
            mode = os.lstat(ancestor)
        except OSError as exc:
            raise ProvisionDeniedError("environment directory unavailable") from exc
        if (not stat.S_ISDIR(mode.st_mode) or mode.st_uid != 0
                or mode.st_mode & 0o022):
            raise ProvisionDeniedError("unsafe environment directory")


def make_content(subject: str) -> bytes:
    if not subject_is_canonical(subject):
        raise ProvisionDeniedError("approved OIDC subject must be canonical UUID")
    lines = (
        f"SOLVERIT_BROKER_CONTROLLER_UID={CONTROLLER_UID}",
        f"SOLVERIT_BROKER_SOCKET_GID={BROKER_GID}",
        f"SOLVERIT_OAUTH_ISSUER_URL={ISSUER}",
        f"SOLVERIT_OAUTH_JWKS_URI={JWKS}",
        f"SOLVERIT_MCP_RESOURCE_URL={RESOURCE}",
        f"SOLVERIT_MCP_DELIVERY_SUBJECTS={subject}",
    )
    return ("\n".join(lines) + "\n").encode("ascii")


def write_exclusive(path: Path, content: bytes) -> None:
    """Fail closed if a policy file exists, including symlinks."""
    if os.geteuid() != 0:
        raise ProvisionDeniedError("root identity required")
    assert_secure_dir(path.parent)
    fd = None
    made = False
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        made = True
        os.fchmod(fd, 0o600)
        os.fchown(fd, 0, 0)
        with os.fdopen(fd, "wb") as output:
            fd = None
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        if fd is not None:
            os.close(fd)
        if made:
            path.unlink()
        raise ProvisionDeniedError("broker environment creation refused") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stage Keycloak broker policy only (never start service)"
    )
    parser.add_argument("--apply", action="store_true",
                        help="require operator approvals and write file exactly once")
    args = parser.parse_args(argv)

    try:
        if os.geteuid() != 0:
            raise ProvisionDeniedError("run with sudo -n after review")
        assert_unchanged_service_identities()
        assert_secure_dir(ENV_DIR)
        if os.path.lexists(ENV_PATH):
            raise ProvisionDeniedError("broker.env already exists; refusing overwrite")
        if not args.apply:
            print("PASS: root-owned directory, separate identities, env absent")
            print("PENDING: positive and negative Keycloak Evaluate evidence")
            print("PENDING: --apply with the approved Keycloak immutable user ID")
            print("Broker remains stopped; no files modified")
            return 0

        print("Confirm Keycloak Evaluate using the OAuth delivery client:")
        print("  approved user: deliver scope present and correct MCP audience")
        print("  other user without role: deliver scope ABSENT")
        print("  delivery scope: Optional, not Default")
        print("  existing auditor and read scope unchanged")
        if input("Were BOTH user evaluations checked? Type CONFIRMADO: ").strip() != APPROVAL:
            raise ProvisionDeniedError("authorization evaluation not confirmed")
        subject = getpass.getpass("Approved Keycloak User ID (sub, hidden): ")
        if not subject_is_canonical(subject):
            raise ProvisionDeniedError("invalid immutable Keycloak user ID")
        # Run validation before any write; no direct keys/tokens go to env.
        content = make_content(subject)
        write_exclusive(ENV_PATH, content)
        print("PASS: root-owned 0600 broker.env staged without printing identity")
        print("PENDING: signed-token positive/negative tests and security review")
        print("Broker NOT started; no services changed")
        return 0
    except (KeyError, ProvisionDeniedError, EOFError, KeyboardInterrupt) as exc:
        # No sensitive values are interpolated into error messages.
        print("BLOCKED: " + (str(exc) if not isinstance(exc, KeyError)
                              else "identity unavailable"))
        return 1


if __name__ == "__main__":
    sys.exit(main())
