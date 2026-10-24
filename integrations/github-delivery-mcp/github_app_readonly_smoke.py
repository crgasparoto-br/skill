"""Non-disruptive GitHub App read-only VPS smoke: no secrets in output.

Run only as the dedicated authenticator identity after installing the code in
an administrator-reviewed, read-only location. Does not touch jobs or publish.
"""
from __future__ import annotations

import json
import sys

from app_token_broker import ALLOWED_REPOSITORIES, mint_token
from github_evidence_reader import _get_json

REPOSITORY = "crgasparoto-br/training-system"


def smoke() -> dict:
    if REPOSITORY not in ALLOWED_REPOSITORIES:
        raise PermissionError("smoke repository not allowlisted")
    token = mint_token(repository=REPOSITORY, operation="read-checks",
                       server_authorized=True)
    # Fixed endpoint: no user-defined URL or external redirect is allowed.
    branch = _get_json(token=token, repo=REPOSITORY, suffix="/branches/develop")
    commit = branch.get("commit")
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if not isinstance(sha, str) or len(sha) != 40 or any(
            c not in "0123456789abcdef" for c in sha):
        raise RuntimeError("invalid develop commit from GitHub")
    checks = _get_json(token=token, repo=REPOSITORY,
                       suffix="/commits/" + sha + "/check-runs?per_page=100")
    count = checks.get("total_count")
    if (type(count) is not int or count > 100 or count < 0
            or not isinstance(checks.get("check_runs"), list)
            or len(checks["check_runs"]) != count):
        raise RuntimeError("incomplete GitHub check page")
    # Deliberately omit token, endpoint headers and check payload details.
    return {"repository": REPOSITORY, "branch": "develop",
            "head_sha": sha, "check_run_count": count,
            "read_only": True}


def main() -> int:
    try:
        result = smoke()
    except Exception:
        # No exception printing: prevent accidental credential leaks in logs.
        print("github_app_readonly_smoke: FAILED", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
