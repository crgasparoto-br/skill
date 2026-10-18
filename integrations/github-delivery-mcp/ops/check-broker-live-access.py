#!/usr/bin/env python3
"""Read-only, fail-closed Keycloak access-token proof before broker activation.

Issue #88: collect three real OAuth access tokens via a no-echo TTY (not
arguments, environment or files), verify their RS256 signatures against the
real Keycloak JWKS under UID 997, and attest scoped allow/deny outcomes.
Never starts a daemon, creates a GitHub token, or prints token claims.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import termios

HERE = Path(__file__).resolve().parent
SOURCE = Path('/opt/solverit/issue-delivery')
MARKER = SOURCE / 'STAGED_COMMIT'
SOCKET = Path('/run/solverit-issue88-broker/broker.sock')
SERVICE = 'solverit-issue88-github-broker.service'
SHA = re.compile(r'[0-9a-f]{40}\Z')
MAX_TOKEN = 8192


class LiveProbeDenied(RuntimeError):
    pass


def validate_staging() -> None:
    """Ensure inactive, root-owned, exact-HEAD code; never change services."""
    expected = os.getenv('ISSUE88_EXPECTED_SHA', '')
    if not SHA.fullmatch(expected):
        raise LiveProbeDenied('pinned SHA required')
    for path, is_file in ((SOURCE, False), (MARKER, True)):
        metadata = os.lstat(path)
        if (metadata.st_uid != 0 or metadata.st_gid != 0
                or metadata.st_mode & 0o022 or
                (not path.is_file() if is_file else not path.is_dir()) or
                path.is_symlink()):
            raise LiveProbeDenied('untrusted staging identity')
    if MARKER.read_text(encoding='ascii').strip() != expected:
        raise LiveProbeDenied('staging SHA does not match reviewed HEAD')
    if os.path.lexists(SOCKET):
        raise LiveProbeDenied('broker socket exists')
    try:
        check = subprocess.run(
            ['systemctl', 'show', SERVICE, '--property=ActiveState', '--value'],
            capture_output=True, text=True, timeout=5, check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LiveProbeDenied('broker service state unavailable') from exc
    if check.stdout.strip() != 'inactive':
        raise LiveProbeDenied('broker service not inactive')


def private_token(label: str) -> str:
    """TTY-only bounded input with echo disabled, no getpass fallback."""
    if not sys.stdin.isatty():
        raise LiveProbeDenied('interactive TTY required')
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        changed = previous.copy()
        changed[3] &= ~termios.ECHO
        termios.tcsetattr(fd, termios.TCSADRAIN, changed)
        print(label + ': ', end='', flush=True)
        raw = sys.stdin.buffer.readline(MAX_TOKEN + 2)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)
        print('', flush=True)
    if not raw.endswith(b'\n') or len(raw) > MAX_TOKEN + 1:
        raise LiveProbeDenied('invalid private token input')
    try:
        token = raw.rstrip(b'\r\n').decode('ascii')
    except UnicodeDecodeError as exc:
        raise LiveProbeDenied('invalid private token encoding') from exc
    if not 10 <= len(token) <= MAX_TOKEN or any(c.isspace() for c in token):
        raise LiveProbeDenied('invalid private token format')
    return token


def validated_signed_claims(token: str, policy: dict[str, str]) -> dict:
    """Authenticate signed negative controls without granting broker access.

    Unverified fields only select a *temporary negative-control policy*.
    Their values are never trusted until the SAME token passes signature,
    issuer, audience, azp, expiry and nonce/time checks against real JWKS.
    """
    import jwt
    from mcp_jwks_verifier import CachedJWKSVerifier, JWKSVerifierPolicy
    claims = jwt.decode(token, options={'verify_signature': False})
    if not isinstance(claims, dict):
        raise LiveProbeDenied('invalid signed control claims')
    subject = claims.get('sub')
    scopes = claims.get('scope')
    if (not isinstance(subject, str) or not subject or len(subject) > 256
            or not isinstance(scopes, str)):
        raise LiveProbeDenied('invalid signed control claims')
    present = scopes.split()
    neutral = next((s for s in ('solverit:read', 'openid') if s in present), None)
    if neutral is None:
        raise LiveProbeDenied('negative token missing baseline scope')
    relaxed = JWKSVerifierPolicy(
        issuer=policy['SOLVERIT_OAUTH_ISSUER_URL'],
        audience=policy['SOLVERIT_MCP_RESOURCE_URL'],
        jwks_uri=policy['SOLVERIT_OAUTH_JWKS_URI'],
        allowed_subjects=frozenset({subject}), required_scope=neutral,
        authorized_party='solverit-chatgpt-mcp',
    )
    verifier = CachedJWKSVerifier(relaxed)
    verifier.refresh()
    if verifier.verify(token) != subject:
        raise LiveProbeDenied('negative token signature policy failed')
    return claims


def check_signed_tokens(policy: dict[str, str], positive: str,
                        scope_negative: str, subject_negative: str) -> None:
    """Verify genuine positive and two independently meaningful negatives."""
    if str(SOURCE) not in sys.path:
        sys.path.insert(0, str(SOURCE))
    from broker_oauth import BrokerOAuthDenied, build_broker_verifier, verified_actor
    approved = policy['SOLVERIT_MCP_DELIVERY_SUBJECTS']
    verifier = build_broker_verifier(policy)
    if verified_actor(positive, verifier=verifier) != approved:
        raise LiveProbeDenied('approved signed token was not bound to owner')
    for token, reason in ((scope_negative, 'scope'),
                          (subject_negative, 'subject')):
        claims = validated_signed_claims(token, policy)
        scopes = claims['scope'].split()
        if reason == 'scope':
            if claims['sub'] != approved or 'solverit:deliver' in scopes:
                raise LiveProbeDenied('scope-negative control is not comparable')
        else:
            if claims['sub'] == approved:
                raise LiveProbeDenied('subject-negative control is not comparable')
        try:
            verified_actor(token, verifier=verifier)
        except BrokerOAuthDenied:
            continue
        raise LiveProbeDenied('negative signed token was accepted')


def main() -> int:
    print('=== ISSUE88: REAL KEYCLOAK TOKEN PREFLIGHT (READ-ONLY) ===')
    try:
        if os.geteuid() != 0:
            raise LiveProbeDenied('run with sudo -n on the VPS')
        validate_staging()
        spec = importlib.util.spec_from_file_location(
            'issue88_jwks_preflight', HERE / 'check-broker-jwks-runtime.py')
        if spec is None or spec.loader is None:
            raise LiveProbeDenied('trusted JWKS preflight missing')
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        policy = runtime.read_trusted_policy()
        print('PASS: pinned staging, inactive broker and private policy')
        print('Provide genuine short-lived OAuth ACCESS tokens; input is hidden.')
        positive = private_token('Approved subject with solverit:deliver')
        scope_negative = private_token('Same subject WITHOUT solverit:deliver')
        subject_negative = private_token('Other subject, without delivery access')
        if len({positive, scope_negative, subject_negative}) != 3:
            raise LiveProbeDenied('distinct OAuth tokens required')
        runtime.drop_to_authenticator()
        check_signed_tokens(policy, positive, scope_negative, subject_negative)
        print('PASS: genuine signed authorized OAuth token accepted')
        print('PASS: genuine signed insufficient-scope OAuth token rejected')
        print('PASS: genuine signed unauthorized-subject OAuth token rejected')
        print('PENDING: Unix-socket peer authorization and full MCP end-to-end')
        print('NO SERVICES STARTED; NO CREDENTIALS SAVED')
        return 0
    except Exception:
        # Never emit exception text, traceback, token, subject or JWT claims.
        print('BLOCKED: live OAuth preflight failed; broker must stay stopped')
        return 1


if __name__ == '__main__':
    sys.exit(main())
