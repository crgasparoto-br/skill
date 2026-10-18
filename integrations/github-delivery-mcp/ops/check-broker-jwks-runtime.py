#!/usr/bin/env python3
"""Issue 88: non-mutating, real Keycloak JWKS startup preflight under broker UID.

Load root-only broker.env without printing it, validate with independent
staging verifier, drop all privileges to UID997, then fetch Keycloak's
real public JWKS and verify that untrusted unsigned access tokens fail.
This does NOT prove acceptance of a real signed bearer access token.
Never starts a daemon, binds a Unix socket, mints a GitHub token, or writes
an env file. Run only with sudo -n on the VPS after reviewing the HEAD.
"""
from __future__ import annotations

import importlib.util
import os
import pwd
import sys
from pathlib import Path

CODE_DIR = Path("/opt/solverit/issue-delivery")
ENV = Path("/etc/solverit/issue-delivery/broker.env")
AUTH_USER = "solverit-github-auth"
AUTH_UID = 997
AUTH_GID = 986


class RuntimeDenied(RuntimeError):
    pass


def read_trusted_policy() -> dict[str, str]:
    """Validate with root-only policy reader and parse exact controlled keys."""
    if os.geteuid() != 0:
        raise RuntimeDenied("root required to attest protected config")
    spec = importlib.util.spec_from_file_location(
        "issue88_independent_policy", Path(__file__).with_name("verify-broker-env.py")
    )
    if spec is None or spec.loader is None:
        raise RuntimeDenied("independent policy verifier missing")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    try:
        verifier.inspect(ENV)
        with ENV.open("rb") as fp:
            data = fp.read(verifier.MAX_BYTES + 1)
        verifier.check_contents(data)
        return dict(line.split("=", 1) for line in data.decode("ascii").splitlines())
    except (OSError, ValueError) as exc:
        raise RuntimeDenied("protected config invalid") from exc


def drop_to_authenticator() -> None:
    try:
        identity = pwd.getpwnam(AUTH_USER)
        if identity.pw_uid != AUTH_UID or identity.pw_gid != AUTH_GID:
            raise RuntimeDenied("unexpected authenticator identity")
        os.setgroups([])
        os.setgid(AUTH_GID)
        os.setuid(AUTH_UID)
    except OSError as exc:
        raise RuntimeDenied("unable to drop privileges") from exc
    if (os.geteuid() != AUTH_UID or os.getegid() != AUTH_GID
            or os.getgroups()):
        raise RuntimeDenied("broker identity not established")


def verify_public_jwks_runtime(policy: dict[str, str]) -> None:
    sys.dont_write_bytecode = True
    if str(CODE_DIR) not in sys.path:
        sys.path.insert(0, str(CODE_DIR))
    try:
        from broker_oauth import (
            BrokerOAuthDenied,
            build_broker_verifier,
            verified_actor,
        )
        validator = build_broker_verifier(policy)  # HTTPS JWKS, RS256 public keys
        for fake in ("unsigned.payload.fake", "Bearer", "solverit:read"):
            try:
                verified_actor(fake, verifier=validator)
            except BrokerOAuthDenied:
                continue
            raise RuntimeDenied("invalid bearer unexpectedly accepted")
    except RuntimeDenied:
        raise
    except Exception as exc:
        # No JWTs, JWT claims, OIDC subjects or network responses in errors.
        raise RuntimeDenied("Keycloak JWKS or negative token check failed") from exc


def main() -> int:
    print("=== ISSUE88: BROKER JWKS STARTUP CHECK, NO SERVICE ACTIVATION ===")
    try:
        policy = read_trusted_policy()
        print("PASS: protected root-owned broker policy verified, identity withheld")
        drop_to_authenticator()
        print("PASS: privileged runner dropped to broker UID 997 / GID 986")
        verify_public_jwks_runtime(policy)
        print("PASS: signed OAuth verifier loaded real Keycloak JWKS under UID 997")
        print("PASS: invalid unsigned bearer tokens rejected")
        print("PENDING: positive real signed JWT, scope/subject negative JWT matrix")
        print("PENDING: broker Unix-socket and controller security integration")
        print("NO SERVICES STARTED; NO CONFIGURATION MODIFIED")
        return 0
    except (RuntimeDenied, ValueError, OSError) as exc:
        print("BLOCKED: " + str(exc))
        print("BROKER MUST REMAIN STOPPED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
