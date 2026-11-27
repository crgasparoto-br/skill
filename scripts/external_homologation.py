"""Read-only M1 contract kernel. Inputs must come from an authenticated collector.

This module does not authenticate GitHub, deployments or human observations and
cannot publish a check or authorize release. M2 must establish those boundaries.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

OWNER_PREFIX = "SOLVERIT_EXTERNAL_HOMOLOGATION_V1\n"
REVIEW_PREFIX = "SOLVERIT_EXTERNAL_HOMOLOGATION_REVIEW_V1\n"
SOLO = "owner-attested-separated-context"
THIRD_PARTY = "owner-attested-third-party-review"
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
IDENTITY_FIELDS = {"repository", "pull_request", "issue", "base_ref", "base_sha", "head_sha",
                   "merge_preview_sha", "issue_sha256", "policy_sha256"}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def object_fields(value, fields):
    require(isinstance(value, dict) and set(value) == fields, "unexpected or missing fields")


def parse(raw):
    require(isinstance(raw, bytes) and 0 < len(raw) <= 60000, "bounded JSON bytes required")

    def unique(pairs):
        value = dict(pairs)
        require(len(value) == len(pairs), "duplicate JSON key")
        return value

    def reject_constant(_value):
        raise ValueError("non-finite JSON value")

    value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique, parse_constant=reject_constant)
    require(isinstance(value, dict), "JSON object required")
    return value


def positive(value):
    return type(value) is int and value > 0


def match(pattern, value):
    return isinstance(value, str) and bool(pattern.fullmatch(value))


def valid_identity(identity):
    object_fields(identity, IDENTITY_FIELDS)
    require(match(re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"), identity["repository"])
            and all(part not in {".", ".."} for part in identity["repository"].split("/")), "repository")
    require(all(positive(identity[k]) for k in ("pull_request", "issue")), "PR/issue identity")
    require(isinstance(identity["base_ref"], str) and bool(identity["base_ref"]), "base ref")
    require(all(match(SHA, identity[k]) for k in ("base_sha", "head_sha", "merge_preview_sha")), "exact SHA")
    require(all(match(DIGEST, identity[k]) for k in ("issue_sha256", "policy_sha256")), "identity digest")


def principal(value):
    object_fields(value, {"id", "login"})
    require(positive(value["id"]) and match(re.compile(r"[A-Za-z0-9-]+"), value["login"]), "principal")


def https_origin(value):
    require(isinstance(value, str) and value.isascii() and not any(ord(c) < 33 or ord(c) == 127 for c in value)
            and "\\" not in value, "HTTPS origin required")
    url = urlsplit(value)
    require(url.scheme == "https" and url.hostname and not url.username and not url.password
            and url.path == "" and not url.query and not url.fragment
            and value == url.scheme + "://" + url.netloc and not any(c.isspace() for c in value), "HTTPS origin required")
    require(url.port is None or 0 < url.port <= 65535, "invalid port")
    host = url.hostname
    require(match(re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?"), host)
            and ".." not in host, "unsupported or ambiguous hostname")
    authority = host if url.port is None else f"{host}:{url.port}"
    require(url.netloc == authority, "noncanonical HTTPS origin")


def policy_for(default_raw, base_raw, identity, scenario):
    require(isinstance(default_raw, bytes) and isinstance(base_raw, bytes)
            and default_raw == base_raw, "trusted policies absent or divergent")
    policy = parse(default_raw)
    object_fields(policy, {"schema_version", "mode", "repository", "api_origin", "assurance", "owner", "reviewer", "scenarios"})
    require(type(policy["schema_version"]) is int and policy["schema_version"] == 1
            and policy["mode"] == "enabled", "policy disabled")
    require(policy["repository"] == identity["repository"] and digest(default_raw) == identity["policy_sha256"], "policy scope")
    https_origin(policy["api_origin"])
    for key in ("owner", "reviewer"):
        principal(policy[key])
    same = policy["owner"]["id"] == policy["reviewer"]["id"]
    require((policy["assurance"] == SOLO and same and policy["owner"] == policy["reviewer"])
            or (policy["assurance"] == THIRD_PARTY and not same
                and policy["owner"]["login"].casefold() != policy["reviewer"]["login"].casefold()),
            "assurance/principal mismatch")
    require(isinstance(policy["scenarios"], dict) and scenario in policy["scenarios"], "scenario not authorized")
    selected = policy["scenarios"][scenario]
    object_fields(selected, {"origin", "controls", "technical_checks"})
    https_origin(selected["origin"])
    controls = selected["controls"]
    require(isinstance(controls, list) and controls and all(isinstance(c, str) and c for c in controls)
            and len(set(controls)) == len(controls), "explicit unique controls required")
    checks = selected["technical_checks"]
    require(isinstance(checks, dict) and checks and all(isinstance(k, str) and k and positive(v)
                                                     for k, v in checks.items()), "technical checks required")
    return policy, selected


def verify_facts(facts, identity, scenario_policy, api_origin):
    object_fields(facts, {"api_origin", "environment", "external_attempt", "technical_checks"})
    require(facts["api_origin"] == api_origin, "API origin mismatch")
    env = facts["environment"]
    object_fields(env, {"origin", "head_sha", "deployment_id", "tls_verified"})
    require(env["origin"] == scenario_policy["origin"] and env["head_sha"] == identity["head_sha"]
            and isinstance(env["deployment_id"], str) and bool(env["deployment_id"])
            and env["tls_verified"] is True, "unverified HTTPS candidate environment")
    attempt = facts["external_attempt"]
    object_fields(attempt, {"head_sha", "run_id", "run_attempt", "result", "diagnostic_sha256"})
    require(attempt["head_sha"] == identity["head_sha"] and positive(attempt["run_id"])
            and positive(attempt["run_attempt"]) and attempt["result"] == "blocked-external"
            and match(DIGEST, attempt["diagnostic_sha256"]), "external block not established")
    checks = facts["technical_checks"]
    expected = scenario_policy["technical_checks"]
    object_fields(checks, set(expected))
    ids = []
    for name, check in checks.items():
        object_fields(check, {"id", "app_id", "head_sha", "run_id", "run_attempt", "conclusion"})
        require(all(positive(check[k]) for k in ("id", "app_id", "run_id", "run_attempt"))
                and check["app_id"] == expected[name] and check["head_sha"] == identity["head_sha"]
                and check["conclusion"] == "success", "technical gate not successful at exact HEAD")
        ids.append(check["id"])
    require(len(set(ids)) == len(ids), "reused technical check")


def verify_files(manifest, files, controls):
    names = manifest["files"]
    require(isinstance(names, dict) and 0 < len(names) <= 16, "bounded evidence inventory required")
    object_fields(files, set(names))
    for name, sha in names.items():
        require(match(re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"), name) and match(DIGEST, sha)
                and isinstance(files[name], bytes) and 0 < len(files[name]) <= 16 * 1024 * 1024
                and digest(files[name]) == sha, "evidence bytes missing or divergent")
    require(sum(map(len, files.values())) <= 32 * 1024 * 1024, "aggregate evidence limit")
    observed = manifest["observations"]
    object_fields(observed, set(controls))
    used = set()
    for observation in observed.values():
        object_fields(observation, {"result", "files"})
        refs = observation["files"]
        require(observation["result"] == "observed-pass" and isinstance(refs, list) and refs
                and all(isinstance(ref, str) and ref in names for ref in refs), "required observation missing")
        used.update(refs)
    require(used == set(names), "unreferenced evidence")


def selected_statement(comments, prefix, actor, identity, watermark, api_origin):
    require(isinstance(comments, list) and type(watermark) is int and watermark >= 0, "journal required")
    candidates = []
    for comment in comments:
        require(isinstance(comment, dict), "invalid comment metadata")
        user = comment.get("user")
        if not isinstance(user, dict) or user.get("id") != actor["id"]:
            continue
        body = comment.get("body")
        if isinstance(body, str) and body.startswith(prefix):
            require(positive(comment.get("id")) and positive(user.get("id")) and user.get("type") == "User"
                    and user.get("login") == actor["login"], "unauthorized author")
            candidates.append(comment)
    require(bool(candidates), "authorized statement absent")
    require(len({c["id"] for c in candidates}) == len(candidates), "duplicate statement")
    selected = max(candidates, key=lambda c: c["id"])
    require(selected["id"] >= watermark and isinstance(selected.get("created_at"), str)
            and bool(selected["created_at"]) and selected["created_at"] == selected.get("updated_at"),
            "statement edited, deleted or superseded")
    base = f"{api_origin}/repos/{identity['repository']}/issues"
    require(selected.get("issue_url") == f"{base}/{identity['pull_request']}"
            and selected.get("url") == f"{base}/comments/{selected['id']}", "statement not linked to PR")
    require(match(re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"), selected["created_at"]), "invalid statement timestamp")
    created = datetime.fromisoformat(selected["created_at"])
    raw = selected["body"].encode()
    return selected["id"], digest(raw), created, parse(raw[len(prefix):])


def validate_external_homologation(*, default_policy, base_policy, identity, facts, manifest_raw,
                                   files, comments, watermarks):
    """Check consistency of collector-supplied bytes; never confer operational authority."""
    valid_identity(identity)
    manifest = parse(manifest_raw)
    object_fields(manifest, {"schema_version", "identity", "scenario", "kind", "simulated",
                             "facts_sha256", "observations", "files"})
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
            and canonical(manifest["identity"]) == canonical(identity) and manifest["kind"] == "human-observed-external"
            and manifest["simulated"] is False and isinstance(manifest["scenario"], str), "wrong evidence identity or kind")
    policy, scenario = policy_for(default_policy, base_policy, identity, manifest["scenario"])
    verify_facts(facts, identity, scenario, policy["api_origin"])
    require(manifest["facts_sha256"] == digest(canonical(facts)), "stale collector facts")
    verify_files(manifest, files, scenario["controls"])
    object_fields(watermarks, {"owner", "reviewer"})
    owner_id, owner_hash, owner_time, owner = selected_statement(comments, OWNER_PREFIX, policy["owner"], identity, watermarks["owner"], policy["api_origin"])
    review_id, _, review_time, review = selected_statement(comments, REVIEW_PREFIX, policy["reviewer"], identity, watermarks["reviewer"], policy["api_origin"])
    expected = {"identity": identity, "manifest_sha256": digest(manifest_raw), "decision": "observed-pass"}
    require(canonical(owner) == canonical(expected), "owner statement mismatch")
    expected.update(decision="approved", owner_comment_id=owner_id, owner_comment_sha256=owner_hash,
                    assurance=policy["assurance"], separate_context_attested=True)
    require(review_id > owner_id and review_time >= owner_time
            and canonical(review) == canonical(expected), "review statement mismatch")
    return {"result": "contract-valid", "assurance": policy["assurance"], "automated_live_pass": False,
            "source_authentication_performed": False, "release_gate_satisfied": False}
