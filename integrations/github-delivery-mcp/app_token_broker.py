"""Scope-only GitHub App broker. Never expose token to an MCP caller or worker.

This module is a library, not a network service. A separately authenticated,
authorized publisher must call it from the dedicated solverit-github-auth
identity. Tokens should remain in publisher memory; no logging or persistence.
"""
import base64
import json
import os
import subprocess
import time
import urllib.request

APP_ID = 5258291
INSTALLATION_ID = 169803130
KEY = "/etc/solverit/issue-delivery/secrets/github-app.pem"
ALLOWED_REPOSITORIES = frozenset({"crgasparoto-br/training-system"})
OPERATION_PERMISSIONS = {
    "read-issue": {"issues": "read"},
    "read-checks": {"checks": "read", "actions": "read"},
    "publish-pr": {"contents": "write", "pull_requests": "write"},
}

def _encode(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

def _make_jwt():
    now = int(time.time())
    header = _encode(b'{"alg":"RS256","typ":"JWT"}')
    payload = _encode(json.dumps(
        {"iat": now - 60, "exp": now + 540, "iss": str(APP_ID)},
        separators=(",", ":")).encode("ascii"))
    unsigned = header + "." + payload
    signature = subprocess.run(
        ["/usr/bin/openssl", "dgst", "-sha256", "-sign", KEY],
        input=unsigned.encode("ascii"), capture_output=True,
        check=True, timeout=10).stdout
    return unsigned + "." + _encode(signature)

def mint_token(*, repository, operation, server_authorized=False):
    """Return a short-lived secret to trusted publisher only.

    server_authorized is NOT an authorization mechanism by itself.
    The future MCP server must verify OAuth identity and repository policy.
    """
    if not server_authorized:
        raise PermissionError("server-side authorization required")
    if repository not in ALLOWED_REPOSITORIES:
        raise PermissionError("repository not allowlisted")
    if operation not in OPERATION_PERMISSIONS:
        raise PermissionError("operation not allowlisted")
    if os.geteuid() != 997:
        raise PermissionError("dedicated authenticator identity required")
    requested = OPERATION_PERMISSIONS[operation]
    body = {"repositories": [repository.split("/", 1)[1]],
            "permissions": requested}
    request = urllib.request.Request(
        f"https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens",
        data=json.dumps(body).encode("ascii"),
        method="POST",
        headers={
            "Authorization": "Bearer " + _make_jwt(),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "solverit-issue88-authenticator",
        })
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    repos = payload.get("repositories")
    if not isinstance(repos, list) or [r.get("full_name") for r in repos] != [repository]:
        raise RuntimeError("installation token repository scope mismatch")
    granted = payload.get("permissions", {})
    if not isinstance(granted, dict) or any(granted.get(k) != v for k, v in requested.items()):
        raise RuntimeError("installation token permission mismatch")
    if any(k not in requested and k != "metadata" for k in granted):
        raise RuntimeError("installation token granted unexpected permission")
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("GitHub response missing installation token")
    return token
