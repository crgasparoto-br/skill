"""Trusted-controller IPC client for the separate Issue 88 CI evidence broker.

Only call from authenticated MCP server middleware. It passes the original
Keycloak access token to a Unix peer that independently validates issuer,
audience, scope and subject. NEVER pass a GitHub token or user-supplied actor.
This is NOT a public MCP tool or a job success gate.
"""
from __future__ import annotations

import json
import re
import socket
import struct
import uuid

from protected_broker_server import (
    AUTH_UID,
    MAX_REQUEST_BYTES,
    PROTOCOL_VERSION,
    SOCKET,
)

_SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_RESPONSE_BYTES = 4096


class BrokerClientError(RuntimeError):
    pass


def _unique_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("ambiguous broker response")
        result[key] = value
    return result


def _exchange(payload: dict[str, object]) -> dict[str, object]:
    request = json.dumps(payload, separators=(",", ":")).encode("ascii") + b"\n"
    if len(request) > MAX_REQUEST_BYTES:
        raise BrokerClientError("oversized request")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(5)
            connection.connect(str(SOCKET))
            if not hasattr(socket, "SO_PEERCRED"):
                raise BrokerClientError("peer credentials unavailable")
            credentials = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
            _pid, peer_uid, _gid = struct.unpack("3i", credentials)
            if peer_uid != AUTH_UID:
                raise BrokerClientError("broker identity mismatch")
            connection.sendall(request)
            buffer = bytearray()
            while b"\n" not in buffer:
                fragment = connection.recv(MAX_RESPONSE_BYTES + 1 - len(buffer))
                if not fragment:
                    raise BrokerClientError("broker response incomplete")
                buffer.extend(fragment)
                if len(buffer) > MAX_RESPONSE_BYTES:
                    raise BrokerClientError("broker response oversized")
            payload, _, extra = buffer.partition(b"\n")
            if extra or not payload:
                raise BrokerClientError("unexpected broker frame")
    except (OSError, ValueError, struct.error, BrokerClientError) as exc:
        raise BrokerClientError("broker unavailable or unauthorized") from exc

    try:
        response = json.loads(payload, object_pairs_hook=_unique_json_keys)
    except (ValueError, UnicodeError) as exc:
        raise BrokerClientError("broker response invalid") from exc
    if not isinstance(response, dict):
        raise BrokerClientError("broker response invalid")
    return response


def _validate_token(mcp_access_token: str) -> None:
    if (not isinstance(mcp_access_token, str) or not mcp_access_token.isascii()
            or any(x.isspace() for x in mcp_access_token)
            or not 10 <= len(mcp_access_token) <= 8192):
        raise BrokerClientError("invalid MCP authentication")


def check_job_ci(*, job_id: str, mcp_access_token: str) -> dict[str, object]:
    if not isinstance(job_id, str) or len(job_id) != 36:
        raise BrokerClientError("invalid job")
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise BrokerClientError("invalid job")
    except ValueError as exc:
        raise BrokerClientError("invalid job") from exc
    _validate_token(mcp_access_token)
    response = _exchange({
        "version": PROTOCOL_VERSION,
        "operation": "verify_bound_ci",
        "job_id": job_id,
        "mcp_access_token": mcp_access_token,
    })
    if (not isinstance(response, dict)
            or set(response) != {"ok", "job_id", "verified_head",
                                "ci_verified", "audit_verified"}
            or response["ok"] is not True or response["ci_verified"] is not True
            or response["audit_verified"] is not False
            or response["job_id"] != job_id
            or not isinstance(response["verified_head"], str)
            or not _SHA.fullmatch(response["verified_head"])):
        raise BrokerClientError("broker denied or returned invalid evidence")
    return response



def inspect_authorized_issue(*, repository: str, issue_number: int,
                             mcp_access_token: str, verified_actor: str) -> str:
    """Return pinned develop SHA only after independent broker OAuth validation."""
    if (repository != "crgasparoto-br/training-system"
            or type(issue_number) is not int or not 1 <= issue_number <= 2_147_483_647
            or not isinstance(verified_actor, str) or not verified_actor
            or len(verified_actor) > 256):
        raise BrokerClientError("issue inspection not authorized")
    _validate_token(mcp_access_token)
    response = _exchange({
        "version": PROTOCOL_VERSION,
        "operation": "inspect_issue_develop",
        "repository": repository,
        "issue_number": issue_number,
        "mcp_access_token": mcp_access_token,
    })
    if (set(response) != {"ok", "repository", "issue_number",
                         "develop_sha", "verified_actor"}
            or response["ok"] is not True
            or response["repository"] != repository
            or type(response["issue_number"]) is not int
            or response["issue_number"] != issue_number
            or response["verified_actor"] != verified_actor
            or not isinstance(response["develop_sha"], str)
            or not _SHA.fullmatch(response["develop_sha"])):
        raise BrokerClientError("broker issue inspection rejected")
    return response["develop_sha"]
