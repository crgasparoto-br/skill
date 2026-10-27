#!/usr/bin/env python3
"""Deterministic operator-attested review contract; NOT third-party identity proof.

No model calls, private key, candidate execution, administrative writes or merge.
A protected-base policy must explicitly opt into this weaker trust model.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import PurePosixPath

PREFIX = "SOLVERIT_SESSION_REVIEW_V1\n"
ASSURANCE = "operator-attested-session-review"
ACKNOWLEDGEMENT = "separate-context-declared-not-cryptographically-proven"
CHECK_NAME = "Verify session review (exact SHA)"
POLICY_PATH = ".github/session-review-policy.json"
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
MAX_BODY = 60000


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def strict_json(raw: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    if len(raw.encode()) > MAX_BODY:
        raise ValueError("review payload exceeds bounded size")
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def validate_policy(policy: dict) -> None:
    require(set(policy) == {"schema_version", "mode", "assurance", "acknowledgement", "operators"},
            "unexpected policy fields")
    require(type(policy["schema_version"]) is int and policy["schema_version"] == 1, "unsupported policy version")
    require(policy["mode"] == "enabled", "session-review policy is disabled or absent in trusted base")
    require(policy["assurance"] == ASSURANCE and policy["acknowledgement"] == ACKNOWLEDGEMENT,
            "policy must explicitly accept single-operator limitations")
    users = policy["operators"]
    require(isinstance(users, list) and bool(users), "explicit operator allowlist required")
    require(all(isinstance(u, dict) and set(u) == {"id", "login"}
                and type(u["id"]) is int and u["id"] > 0
                and isinstance(u["login"], str) and re.fullmatch(r"[A-Za-z0-9-]+", u["login"])
                for u in users), "invalid operator identity")
    require(len({u["id"] for u in users}) == len(users), "duplicate operator identity")


def allowed(comment: dict, policy: dict) -> bool:
    user = comment.get("user") or {}
    return user.get("type") != "Bot" and any(
        user.get("id") == item["id"] and str(user.get("login", "")).casefold() == item["login"].casefold()
        for item in policy["operators"]
    )


def latest_review(comments: list[dict], policy: dict, *, watermark: int = 0) -> dict:
    """Never fall back to an old approval after edit, rejection or deletion."""
    candidates = [c for c in comments if allowed(c, policy)
                  and isinstance(c.get("body"), str) and c["body"].startswith(PREFIX)]
    require(bool(candidates), "no operator-attested review recorded")
    selected = max(candidates, key=lambda c: c["id"])
    require(type(selected.get("id")) is int and selected["id"] >= watermark,
            "latest review deleted or superseded; a new review is required")
    require(selected.get("created_at") == selected.get("updated_at"),
            "edited review is revoked; submit a new immutable review")
    return selected


def validate_identity(identity: dict) -> None:
    require(set(identity) == {"repository", "pull_request", "issue", "base_ref", "base_sha", "head_sha",
                              "merge_preview_sha", "issue_sha256", "policy_sha256"}, "identity fields differ")
    require(isinstance(identity["repository"], str) and
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", identity["repository"]), "invalid repository")
    require(all(type(identity[k]) is int and identity[k] > 0 for k in ("pull_request", "issue")),
            "positive PR and issue numbers required")
    require(identity["base_ref"] in {"develop", "main"}, "unsupported base")
    require(all(isinstance(identity[k], str) and SHA.fullmatch(identity[k])
                for k in ("base_sha", "head_sha", "merge_preview_sha")), "exact SHAs required")
    require(all(isinstance(identity[k], str) and DIGEST.fullmatch(identity[k])
                for k in ("issue_sha256", "policy_sha256")), "immutable source digests required")


def verify_requirements(rows: list, requirements: list, files: dict[str, str], passed_tests: set[str]) -> None:
    """Reconcile all canonical obligations with exact source and executed controls."""
    expected = {item["candidate_key"] for item in requirements}
    require(bool(expected) and isinstance(rows, list) and len(rows) == len(expected), "incomplete requirement inventory")
    require(all(isinstance(row, dict) for row in rows), "requirement rows must be objects")
    require({row.get("candidate_key") for row in rows} == expected, "requirement keys are missing or foreign")
    for row in rows:
        require(set(row) == {"candidate_key", "analysis", "sources", "controls"}, "invalid requirement row")
        require(isinstance(row["analysis"], str) and len(row["analysis"].strip()) >= 40,
                "requirement-specific semantic analysis required")
        sources = row["sources"]
        require(isinstance(sources, list) and 0 < len(sources) <= 20, "source evidence required")
        for source in sources:
            require(isinstance(source, dict) and set(source) == {"path", "start_line", "end_line", "sha256"},
                    "invalid source anchor")
            path = source["path"]
            require(isinstance(path, str) and path in files and safe_path(path), "source not in frozen file inventory")
            start, end = source["start_line"], source["end_line"]
            lines = files[path].splitlines()
            require(type(start) is int and type(end) is int and 1 <= start <= end <= len(lines),
                    "source lines do not exist at material SHA")
            require(source["sha256"] == digest("\n".join(lines[start - 1:end]).encode()), "source evidence digest mismatch")
        controls = row["controls"]
        require(isinstance(controls, list) and len(controls) == 3, "positive, negative and regression controls required")
        require(all(isinstance(c, dict) and set(c) == {"kind", "test_case_id", "rationale"} for c in controls),
                "invalid test control")
        require({c["kind"] for c in controls} == {"positive", "negative", "regression"}, "test control kinds incomplete")
        require(len({c["test_case_id"] for c in controls}) == 3, "discriminating test cases must be distinct")
        for control in controls:
            require(control["test_case_id"] in passed_tests, "test was absent, failed or skipped at exact SHA")
            require(isinstance(control["rationale"], str) and len(control["rationale"].strip()) >= 25,
                    "test relevance rationale missing")


def verify_review(comment: dict, packet: dict, policy: dict, files: dict[str, str],
                  passed_tests: set[str]) -> dict:
    """All factual inputs are collected independently by the trusted runner.

    The author's claim that sessions are separate remains an explicit declaration,
    not a machine-verifiable proof. Evidence bindings do not prove semantics alone.
    """
    validate_policy(policy)
    require(allowed(comment, policy), "unauthorized review author")
    require(type(comment.get("id")) is int and comment["id"] > 0, "GitHub comment identity missing")
    require(comment.get("created_at") == comment.get("updated_at"), "review was edited")
    body = comment.get("body")
    require(isinstance(body, str) and body.startswith(PREFIX), "review marker missing")
    report = strict_json(body[len(PREFIX):])
    require(set(report) == {"schema_version", "identity", "assurance", "acknowledgement", "sessions",
                           "conclusion", "blocking_findings", "limitations", "requirements"},
            "unexpected or missing review fields")
    require(type(report["schema_version"]) is int and report["schema_version"] == 1, "unsupported review version")
    validate_identity(packet["identity"])
    validate_identity(report["identity"])
    require(report["identity"] == packet["identity"], "review identity is stale or belongs to another delivery")
    require(report["assurance"] == ASSURANCE and report["acknowledgement"] == ACKNOWLEDGEMENT,
            "a session review must not claim independent cryptographic identity")
    sessions = report["sessions"]
    require(isinstance(sessions, dict) and set(sessions) == {"implementation", "audit", "separate_context_attested"},
            "session declarations missing")
    require(all(isinstance(sessions[k], str) and 8 <= len(sessions[k]) <= 300
                and sessions[k].strip() == sessions[k] for k in ("implementation", "audit")),
            "session references must be supplied by the operator, not invented")
    require(sessions["separate_context_attested"] is True and sessions["implementation"] != sessions["audit"],
            "separate review context must be explicitly attested")
    require(report["conclusion"] == "approved", "review does not approve the candidate")
    require(report["blocking_findings"] == [] and report["limitations"] == [],
            "unresolved findings or material limitations")
    verify_requirements(report["requirements"], packet["requirements"], files, passed_tests)
    created = datetime.fromisoformat(comment["created_at"])
    require(created.tzinfo is not None, "review timestamp requires timezone")
    certified = datetime.fromisoformat(packet["certified_at"])
    require(certified.tzinfo is not None and created >= certified, "review predates certified evidence")
    receipt = {"schema_version": 1, "assurance": ASSURANCE, "identity": packet["identity"],
               "review_comment_id": comment["id"], "review_body_sha256": digest(body.encode()),
               "artifact_digest": packet["artifact_digest"], "technical_check_ids": packet["technical_check_ids"],
               "third_party_identity_proven": False, "session_separation": "operator-declared"}
    receipt["fingerprint"] = digest(canonical(receipt))
    return receipt


def safe_path(path: str) -> bool:
    value = PurePosixPath(path)
    return (bool(path) and str(value) != "." and not value.is_absolute() and ".." not in value.parts
            and "\\" not in path and all(ord(c) >= 32 for c in path)
            and path in {value.as_posix(), value.as_posix() + "/"})
