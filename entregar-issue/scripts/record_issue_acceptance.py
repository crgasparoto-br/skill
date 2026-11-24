#!/usr/bin/env python3
"""Render and verify append-only GitHub issue acceptance comments, without remote writes."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from reconcile_issue_checkboxes import analyze_body, reconcile

MARKER = "SOLVERIT_ACCEPTANCE_RECORD_V1\n"
REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def render_record(audited_body: str, current_body: str, audit: dict,
                  repository: str, issue_number: int, pr_number: int,
                  material_sha: str) -> str:
    """Only render: validity and audit URLs do NOT authenticate their own origin."""
    if not isinstance(repository, str) or not REPO.fullmatch(repository):
        raise ValueError("Expected owner/repository")
    if any(type(n) is not int or n <= 0 for n in (issue_number, pr_number)):
        raise ValueError("Issue and PR must be positive integers")
    if not isinstance(material_sha, str) or not SHA.fullmatch(material_sha):
        raise ValueError("Invalid material SHA")
    reconcile(audited_body, current_body, audit, material_sha)
    _, initial, audited_norm = analyze_body(audited_body)
    _, observed, current_norm = analyze_body(current_body)
    if audited_norm != current_norm:
        raise ValueError("Normative contract drift")
    criteria = [
        {"ordinal": source["ordinal"], "text": source["text"],
         "audited_checked": source["checked"], "observed_checked": live["checked"],
         "status": decision["status"], "verified": decision["status"] == "verified",
         "evidence": decision.get("evidence", [])}
        for source, live, decision in zip(initial, observed, audit["criteria"], strict=True)
    ]
    payload = {
        "schema_version": 1, "kind": "issue-acceptance-evidence",
        "repository": repository, "issue_number": issue_number,
        "pull_request_number": pr_number, "material_sha": material_sha,
        "audit_url": audit["audit_url"], "asserted_audit_validity": audit["validity"],
        "issue_contract_sha256": digest(current_norm),
        "issue_body_sha256": digest(current_body),
        "criteria": criteria, "publication": "APPEND_ONLY_ISSUE_COMMENT",
        "issue_body_modified": False, "audit_authenticated": "CONTROLLER_MUST_VERIFY",
        "approval_granted": False,
    }
    return MARKER + json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def parse_record(comment_body: str) -> dict:
    if not isinstance(comment_body, str) or not comment_body.startswith(MARKER):
        raise ValueError("Missing acceptance record marker")
    try:
        record = json.loads(comment_body[len(MARKER):])
    except json.JSONDecodeError as exc:
        raise ValueError("Malformed acceptance record JSON") from exc
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ValueError("Invalid record schema")
    if (record.get("kind") != "issue-acceptance-evidence"
            or record.get("approval_granted") is not False
            or record.get("publication") != "APPEND_ONLY_ISSUE_COMMENT"):
        raise ValueError("Record must not assert approval")
    return record


def publication_decision(expected: str, comments: list[dict]) -> str:
    """Best-effort dedupe, not atomic exactly-once across concurrent POSTs."""
    wanted = parse_record(expected)
    if not isinstance(comments, list):
        raise ValueError("Invalid GitHub comment list")
    found = False
    for comment in comments:
        if not isinstance(comment, dict):
            raise ValueError("Malformed GitHub comment")
        body = comment.get("body")
        if not isinstance(body, str) or not body.startswith(MARKER):
            continue
        other = parse_record(body)
        key = ("repository", "issue_number", "pull_request_number",
               "material_sha", "issue_contract_sha256")
        if all(other.get(field) == wanted.get(field) for field in key):
            if body != expected:
                raise ValueError("Conflicting acceptance record at exact identity")
            found = True
    return "already-recorded" if found else "publish"


def check_comment_readback(expected: str, observed: str, issue_body: str,
                           material_sha: str, observed_material_sha: str,
                           comment_id: int) -> dict:
    """Compare inputs obtained by controller from GitHub; cannot authenticate source."""
    record = parse_record(expected)
    if observed != expected:
        raise ValueError("Remote comment read-back differs")
    if not SHA.fullmatch(material_sha) or material_sha != observed_material_sha:
        raise ValueError("Remote material SHA drift")
    if record.get("material_sha") != material_sha:
        raise ValueError("Record material SHA mismatch")
    if digest(issue_body) != record.get("issue_body_sha256"):
        raise ValueError("Remote issue-body drift")
    if type(comment_id) is not int or comment_id <= 0:
        raise ValueError("Missing confirmed GitHub comment ID")
    return {"comment_id": comment_id, "comment_match": True, "issue_body_match": True,
            "material_sha": material_sha, "origin_authenticated": "CONTROLLER_MUST_VERIFY",
            "approval": "NOT_ASSERTED"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audited-body", type=Path, required=True)
    parser.add_argument("--current-body", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    parser.add_argument("--pull-request-number", type=int, required=True)
    parser.add_argument("--material-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prior-comments", type=Path)
    parser.add_argument("--readback-comment", type=Path)
    parser.add_argument("--readback-issue-body", type=Path)
    parser.add_argument("--observed-material-sha")
    parser.add_argument("--observed-comment-id", type=int)
    args = parser.parse_args()
    readback = (args.readback_comment, args.readback_issue_body,
                args.observed_material_sha, args.observed_comment_id)
    if any(x is not None for x in readback) and not all(x is not None for x in readback):
        raise ValueError("All read-back arguments required together")
    record = render_record(
        args.audited_body.read_text(encoding="utf-8"),
        args.current_body.read_text(encoding="utf-8"),
        json.loads(args.audit.read_text(encoding="utf-8")),
        args.repository, args.issue_number, args.pull_request_number, args.material_sha,
    )
    result = {"mode": "offline-only", "remote_write": False}
    if args.prior_comments:
        result["publication_decision"] = publication_decision(
            record, json.loads(args.prior_comments.read_text(encoding="utf-8"))
        )
    if args.readback_comment:
        result["readback"] = check_comment_readback(
            record, args.readback_comment.read_text(encoding="utf-8"),
            args.readback_issue_body.read_text(encoding="utf-8"),
            args.material_sha, args.observed_material_sha, args.observed_comment_id,
        )
    args.output.write_text(record, encoding="utf-8")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
