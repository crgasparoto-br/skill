#!/usr/bin/env python3
"""Strict input contract for the separate single-operator Ed25519 audit check.

This module parses only trusted Actions variables and the public comment transport;
it does not perform GitHub I/O, publish checks, or claim third-party independence.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

CHECK_NAME = "Verify solo audit attestation (exact SHA)"
COMMENT_MARKER = "SOLVERIT_EXTERNAL_AUDIT_JSON:"
ASSURANCE_MODE = "single-operator-separate-context"
ACCEPTED_TEXT = "solo-context audit accepted — no third-party human approval claimed"
MAX_COMMENT_BYTES = 48 * 1024
MAX_REGISTRY_BYTES = 32 * 1024
MAX_JSON_DEPTH = 64
REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
KEY_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{3,63}\Z")
NUMERIC_ID_RE = re.compile(r"[1-9][0-9]{0,18}\Z")
GLOB_CHARS = frozenset("*?[]")

VARIABLE_NAMES = frozenset({
    "SOLVERIT_TRUSTED_AUDITORS_JSON",
    "SOLVERIT_SOLO_AUDIT_OPERATOR_ID",
    "SOLVERIT_SOLO_AUDIT_KEY_ID",
    "SOLVERIT_SOLO_AUDIT_ENABLED",
})


@dataclass(frozen=True)
class TrustedConfig:
    operator_id: int
    key_id: str
    registry_raw: bytes
    registry: dict[str, Any]
    fingerprint: str


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _check_depth(value: object, depth: int = 0) -> None:
    require(depth <= MAX_JSON_DEPTH, "JSON nesting exceeds the safety limit")
    if isinstance(value, dict):
        for child in value.values():
            _check_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_depth(child, depth + 1)


def strict_json(raw: bytes | str, *, limit: int) -> dict[str, Any]:
    """Parse one bounded JSON object; reject duplicate keys and non-JSON constants."""
    if isinstance(raw, bytes):
        require(len(raw) <= limit, "JSON input exceeds its byte limit")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("JSON input is not UTF-8") from exc
    elif isinstance(raw, str):
        encoded = raw.encode("utf-8", errors="strict")
        require(len(encoded) <= limit, "JSON input exceeds its byte limit")
        text = raw
    else:
        raise ValueError("JSON input must be UTF-8 text or bytes")

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    try:
        value = json.loads(text, object_pairs_hook=unique_pairs, parse_constant=_reject_constant)
        _check_depth(value)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("invalid bounded JSON object") from exc
    require(isinstance(value, dict), "JSON root must be an object")
    return value


def _registry_key(registry: dict[str, Any], key_id: str, repository: str) -> dict[str, Any]:
    require(type(registry.get("schema_version")) is int and registry["schema_version"] == 1,
            "trusted auditor registry version is invalid")
    auditors = registry.get("auditors")
    require(isinstance(auditors, list) and bool(auditors), "trusted auditor registry is empty or malformed")
    all_ids: list[str] = []
    for item in auditors:
        require(isinstance(item, dict) and isinstance(item.get("key_id"), str),
                "trusted auditor registry entry is malformed")
        all_ids.append(item["key_id"])
    require(len(all_ids) == len(set(all_ids)), "trusted auditor key IDs must be unique")
    matches = [item for item in auditors if item.get("key_id") == key_id]
    require(len(matches) == 1 and matches[0].get("enabled") is True,
            "configured solo signing key is absent or disabled")
    repositories = matches[0].get("repositories")
    require(isinstance(repositories, list) and all(isinstance(x, str) for x in repositories),
            "configured signing key repository scope is malformed")
    require(all(not any(char in pattern for char in GLOB_CHARS) for pattern in repositories),
            "solo signing key repository scope must not contain wildcards")
    require(all(REPOSITORY_RE.fullmatch(pattern) is not None for pattern in repositories),
            "solo signing key repository scopes must be valid owner/repo literals")
    require(len(repositories) == len(set(repositories)),
            "solo signing key repository scopes must be unique")
    require(repository in repositories, "signing key is not registered for the exact repository")
    return matches[0]


def parse_trusted_config(values: dict[str, object], repository: str) -> TrustedConfig:
    """Validate the four repository Actions variables; never fall back to candidate data."""
    require(isinstance(values, dict) and VARIABLE_NAMES <= set(values),
            "solo audit configuration is absent")
    require(all(isinstance(values[name], str) for name in VARIABLE_NAMES),
            "solo audit configuration values must be strings")
    require(REPOSITORY_RE.fullmatch(repository) is not None, "invalid configured repository")
    enabled = values["SOLVERIT_SOLO_AUDIT_ENABLED"]
    require(enabled == "true", "solo audit mode is disabled")

    operator_text = values["SOLVERIT_SOLO_AUDIT_OPERATOR_ID"]
    key_id = values["SOLVERIT_SOLO_AUDIT_KEY_ID"]
    registry_text = values["SOLVERIT_TRUSTED_AUDITORS_JSON"]
    require(NUMERIC_ID_RE.fullmatch(operator_text) is not None, "solo operator ID must be a positive canonical number")
    require(KEY_ID_RE.fullmatch(key_id) is not None, "solo signing key ID is malformed")
    registry_raw = registry_text.encode("utf-8", errors="strict")
    require(len(registry_raw) <= MAX_REGISTRY_BYTES, "trusted auditor registry exceeds 32 KiB")
    registry = strict_json(registry_raw, limit=MAX_REGISTRY_BYTES)
    _registry_key(registry, key_id, repository)

    material = {name: values[name] for name in sorted(VARIABLE_NAMES)}
    fingerprint = hashlib.sha256(canonical(material)).hexdigest()
    return TrustedConfig(
        operator_id=int(operator_text), key_id=key_id, registry_raw=registry_raw,
        registry=registry, fingerprint=fingerprint,
    )


def parse_report_comment_body(body: object) -> tuple[bytes, dict[str, Any]]:
    """Require one exact marker line and a single JSON object, with no narrative."""
    require(isinstance(body, str), "audit transport comment body is missing")
    encoded = body.encode("utf-8", errors="strict")
    require(len(encoded) <= MAX_COMMENT_BYTES, "audit transport comment exceeds 48 KiB")
    require(body.count(COMMENT_MARKER) == 1 and body.startswith(COMMENT_MARKER + "\n"),
            "audit transport must contain one exact marker line")
    payload = body[len(COMMENT_MARKER) + 1:]
    report = strict_json(payload, limit=MAX_COMMENT_BYTES - len(COMMENT_MARKER.encode("utf-8")) - 1)
    return payload.encode("utf-8"), report


def select_report_comment(comments: list[dict[str, Any]]) -> dict[str, Any]:
    """Require exactly one active marker-bearing comment; never fall back to history."""
    require(isinstance(comments, list) and all(isinstance(item, dict) for item in comments),
            "comment inventory is incomplete or malformed")
    marked = [item for item in comments
              if isinstance(item.get("body"), str) and COMMENT_MARKER in item["body"]]
    require(len(marked) == 1, "exactly one active signed audit comment is required")
    return marked[0]


def canonical_issue_reference(pr_body: object) -> int:
    """Return one isolated canonical closes/fixes/refs issue reference or fail."""
    require(isinstance(pr_body, str), "PR body is unavailable")
    matches = re.findall(r"(?im)^\s*(?:closes|fixes|refs)\s+#([1-9][0-9]*)\s*$", pr_body)
    require(len(matches) == 1, "canonical PR-to-issue reference is missing or ambiguous")
    return int(matches[0])
