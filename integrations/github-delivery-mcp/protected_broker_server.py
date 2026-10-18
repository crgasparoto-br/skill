"""Privileged, read-only CI evidence broker over a local Unix socket.

Staging boundary for Issue #88: the caller provides an OAuth bearer token,
verified *again* by the broker against pinned Keycloak JWKS. GitHub credentials,
actor, repository, PR number and required checks are never caller-supplied. All come
from a protected database or versioned broker policy. No publish operation
is implemented here. NOT an Internet-facing MCP endpoint.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sqlite3
import stat
import struct
import urllib.parse
import uuid
from contextlib import closing
from pathlib import Path

from app_token_broker import ALLOWED_REPOSITORIES, mint_token
from broker_oauth import build_broker_verifier, verified_actor
from github_evidence_reader import fetch_and_validate_github
from jobs import Job
from pr_binding import PRBinding

AUTH_UID = 997
WORKER_UID = 1004
DATABASE = Path("/var/lib/solverit/issue-delivery/protected/jobs.sqlite3")
SOCKET = Path("/run/solverit-issue88-broker/broker.sock")
MAX_REQUEST_BYTES = 12288
PROTOCOL_VERSION = 1

# Protected code policy; never accept required checks from MCP, worker or issue.
REQUIRED_CHECKS = {
    "crgasparoto-br/training-system": frozenset({"Validate repository"}),
}
_SHA = re.compile(r"^[0-9a-f]{40}$")


class BrokerDenied(PermissionError):
    """Generic failure; never include SQLite rows, tokens or URL contents."""


def _protected_path(path: Path, *, is_file: bool) -> None:
    """Reject symlinks, worker-owned paths and writable ancestors."""
    if not path.is_absolute():
        raise BrokerDenied("untrusted path")
    components = [path, *path.parents]
    for part in components:
        try:
            info = os.lstat(part)
        except OSError as exc:
            raise BrokerDenied("protected path unavailable") from exc
        if info.st_uid not in (0, AUTH_UID) or info.st_mode & 0o022:
            raise BrokerDenied("untrusted path ownership")
        if stat.S_ISLNK(info.st_mode):
            raise BrokerDenied("symlink forbidden")
        if part == path and is_file:
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != AUTH_UID
                    or info.st_mode & 0o077):
                raise BrokerDenied("untrusted database permissions")
        elif not stat.S_ISDIR(info.st_mode):
            raise BrokerDenied("untrusted parent directory")


def _read_persisted_binding(job_id: str, *, actor: str):
    """Read only the protected source of truth; never create/modify SQLite."""
    _protected_path(DATABASE, is_file=True)
    uri = "file:" + urllib.parse.quote(str(DATABASE), safe="/") + "?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=3)) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """SELECT j.job_id, j.actor, j.repo, j.issue_number, j.branch,
                          j.base_sha, j.expected_head, j.correlation_id,
                          j.status, j.created_at, j.updated_at,
                          b.pr_number, b.head_sha, b.recorded_at
                   FROM jobs AS j
                   JOIN job_pr_bindings AS b ON b.job_id=j.job_id
                   WHERE j.job_id=?""", (job_id,)
            ).fetchone()
    except sqlite3.Error as exc:
        raise BrokerDenied("protected store unavailable") from exc
    if row is None or row["actor"] != actor:
        raise BrokerDenied("trusted job binding missing")
    job = Job(**{field: row[field] for field in Job.__dataclass_fields__})
    binding = PRBinding(job_id, row["pr_number"], row["head_sha"],
                        row["recorded_at"])
    if (job.status != "prepared" or job.branch in ("develop", "main")
            or not _SHA.fullmatch(job.expected_head)
            or job.expected_head == job.base_sha
            or binding.head_sha != job.expected_head
            or type(binding.pr_number) is not int or binding.pr_number <= 0):
        raise BrokerDenied("trusted binding not publishable")
    return job, binding


def verify_bound_ci(job_id: str, *, actor: str) -> dict[str, object]:
    """Mint/read inside authenticator process; return only non-secret proof."""
    if os.geteuid() != AUTH_UID:
        raise BrokerDenied("authenticator identity required")
    job, binding = _read_persisted_binding(job_id, actor=actor)
    checks = REQUIRED_CHECKS.get(job.repo)
    if (job.repo not in ALLOWED_REPOSITORIES or not checks
            or not isinstance(job.issue_number, int) or job.issue_number <= 0):
        raise BrokerDenied("repository not authorized")
    # NEVER return token, even on failure; no logging of token/exceptions.
    token = mint_token(repository=job.repo, operation="read-checks",
                       server_authorized=True)
    verified_sha = fetch_and_validate_github(
        job=job, pr_number=binding.pr_number, binding=binding,
        token=token, required_checks=checks,
    )
    if verified_sha != job.expected_head:
        raise BrokerDenied("GitHub evidence mismatch")
    # CI verification does NOT certify audit and does NOT finalize any job.
    return {"ok": True, "job_id":job.job_id,
            "verified_head": verified_sha, "ci_verified": True,
            "audit_verified": False}


def dispatch(request: object, *, peer_uid: int, controller_uid: int,
             verifier: object) -> dict[str, object]:
    """Authenticate peer UID and signed Keycloak identity independently."""
    if (type(controller_uid) is not int or controller_uid <= 0
            or controller_uid in (AUTH_UID, WORKER_UID)
            or peer_uid != controller_uid):
        raise BrokerDenied("caller identity denied")
    if (not isinstance(request, dict)
            or set(request) != {"version", "operation", "job_id", "mcp_access_token"}
            or type(request.get("version")) is not int
            or request["version"] != PROTOCOL_VERSION
            or request.get("operation") != "verify_bound_ci"):
        raise BrokerDenied("operation denied")
    job_id = request["job_id"]
    if not isinstance(job_id, str) or len(job_id) != 36:
        raise BrokerDenied("invalid job identifier")
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise BrokerDenied("invalid job identifier")
    except ValueError as exc:
        raise BrokerDenied("invalid job identifier") from exc
    actor = verified_actor(request["mcp_access_token"], verifier=verifier)
    return verify_bound_ci(job_id, actor=actor)


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BrokerDenied("duplicate request field")
        result[key] = value
    return result


def _read_frame(connection: socket.socket) -> object:
    data = bytearray()
    while b"\n" not in data:
        chunk = connection.recv(MAX_REQUEST_BYTES + 1 - len(data))
        if not chunk:
            raise BrokerDenied("incomplete request")
        data.extend(chunk)
        if len(data) > MAX_REQUEST_BYTES:
            raise BrokerDenied("oversized request")
    line, _, rest = data.partition(b"\n")
    if rest or not line:
        raise BrokerDenied("invalid frame")
    try:
        return json.loads(line.decode("utf-8"), object_pairs_hook=_unique_json_keys)
    except (UnicodeError, ValueError) as exc:
        raise BrokerDenied("invalid request") from exc


def serve_one(connection: socket.socket, *, controller_uid: int, verifier: object) -> None:
    """Always redact errors. No request is read from unauthorized peers."""
    response: dict[str, object] = {"ok": False, "error": "denied"}
    try:
        if not hasattr(socket, "SO_PEERCRED"):
            raise BrokerDenied("peer credentials unsupported")
        credentials = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, peer_uid, _gid = struct.unpack("3i", credentials)
        if (peer_uid != controller_uid or controller_uid <= 0
                or controller_uid in (AUTH_UID, WORKER_UID)):
            raise BrokerDenied("unauthorized peer")
        connection.settimeout(5)
        response = dispatch(_read_frame(connection), peer_uid=peer_uid,
                            controller_uid=controller_uid, verifier=verifier)
    except Exception:
        # Security boundary: don't expose private exception messages or tokens.
        pass
    try:
        connection.sendall((json.dumps(response, sort_keys=True) + "\n").encode())
    except OSError:
        pass


def serve(*, controller_uid: int, socket_gid: int) -> None:
    if (os.geteuid() != AUTH_UID or type(controller_uid) is not int
            or controller_uid <= 0 or controller_uid in (AUTH_UID, WORKER_UID)
            or type(socket_gid) is not int or socket_gid <= 0):
        raise BrokerDenied("invalid broker identity configuration")
    _protected_path(DATABASE, is_file=True)
    _protected_path(SOCKET.parent, is_file=False)
    verifier = build_broker_verifier(os.environ)
    if os.path.lexists(SOCKET):
        raise BrokerDenied("socket path occupied; inspect before retry")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(SOCKET))
        try:
            os.chown(SOCKET, -1, socket_gid)
            os.chmod(SOCKET, 0o660)
            listener.listen(4)
            while True:
                connection, _ = listener.accept()
                with connection:
                    serve_one(connection, controller_uid=controller_uid, verifier=verifier)
        finally:
            # Socket directory must be private to the trusted broker account.
            if os.path.lexists(SOCKET) and stat.S_ISSOCK(os.lstat(SOCKET).st_mode):
                os.unlink(SOCKET)


def main() -> None:
    # Root-managed EnvironmentFile in systemd, never arguments from MCP.
    uid = os.environ.get("SOLVERIT_BROKER_CONTROLLER_UID", "")
    gid = os.environ.get("SOLVERIT_BROKER_SOCKET_GID", "")
    if not uid.isascii() or not uid.isdecimal() or not gid.isascii() or not gid.isdecimal():
        raise BrokerDenied("broker environment not provisioned")
    serve(controller_uid=int(uid), socket_gid=int(gid))


if __name__ == "__main__":
    main()
