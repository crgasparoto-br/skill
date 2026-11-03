#!/usr/bin/env python3
"""Trusted exact-SHA gate for a solo-context Ed25519 audit attestation.

The workflow checks out github.workflow_sha from a protected ref. It never
checks out, imports, or executes candidate code and never changes the native
third-party-review gate.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "entregar-issue" / "scripts"))

import verify_session_review as session_runner
from solo_audit_check_runs import begin_check, publish_check, required_evidence
from solo_audit_contract import ACCEPTED_TEXT, ASSURANCE_MODE, require
from solo_audit_events import resolve_targets
from solo_audit_github import (
    current_target,
    github_token,
    is_authorized_reviewer,
    load_config,
    report_comment,
    require_unique_open_pr_head,
    validate_signed_report,
)
from solo_audit_source import (
    REPOSITORY_RE,
    SHA_RE,
    revalidate_execution_source,
    verify_execution_source,
)


def _recheck_comment(repo: str, number: int, initial: dict[str, Any], config: Any) -> None:
    selected, _, raw = report_comment(repo, number, config)
    require(selected["snapshot"] == initial["snapshot"] and raw == initial["raw_report"],
            "signed comment changed during final revalidation")
    live = session_runner.api(f"/repos/{repo}/issues/comments/{initial['comment']['id']}")
    live_snapshot = session_runner.review_snapshot(live, repo, number)
    require(live_snapshot == initial["snapshot"], "signed comment was edited or deleted")


def final_revalidation(repo: str, number: int, identity: dict[str, Any],
                       config0: Any, selected0: dict[str, Any], source0: dict[str, Any],
                       evidence_ids: list[int]) -> None:
    """Re-read every mutable authority after work and directly before success."""
    # CI/provenance collection can be slow. Recheck it first, then re-read all
    # other mutable authorities after that collection and immediately before write.
    evidence_ids_final = required_evidence(repo, identity)
    require(evidence_ids_final == evidence_ids,
            "required exact-HEAD checks changed during final revalidation")
    revalidate_execution_source(repo, identity["base_sha"], source0)
    latest, _ = current_target(repo, number, identity["issue"])
    require(latest == identity, "PR, issue body, base, HEAD, or merge preview changed")
    config1 = load_config(repo)
    require(config1.fingerprint == config0.fingerprint, "solo configuration or trusted key changed")
    selected1, report1, _ = report_comment(repo, number, config1)
    require(selected1["snapshot"] == selected0["snapshot"]
            and selected1["raw_report"] == selected0["raw_report"],
            "signed comment changed during final revalidation")
    require(report1.get("issue") == identity["issue"]
            and report1.get("pull_request") == number,
            "signed report PR/issue binding changed")
    _recheck_comment(repo, number, selected0, config1)
    login = selected1["comment"].get("user", {}).get("login")
    require(isinstance(login, str) and is_authorized_reviewer(repo, login, github_token()),
            "solo operator permission was revoked")
    require_unique_open_pr_head(repo, number, identity["head_sha"])


def evaluate_target(repo: str, number: int, expected_issue: int | None,
                    workflow_sha: str, run_id: str) -> int:
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "assurance_mode": ASSURANCE_MODE,
        "third_party_human_approval_claimed": False,
        "pull_request": number,
    }
    head = ""
    check_id: int | None = None
    identity: dict[str, Any] | None = None
    try:
        initial_pr = session_runner.api(f"/repos/{repo}/pulls/{number}")
        live_head = (initial_pr.get("head") or {}).get("sha") if isinstance(initial_pr, dict) else None
        require(isinstance(live_head, str) and SHA_RE.fullmatch(live_head), "live PR HEAD is unavailable")
        head = live_head
        check_id = begin_check(repo, head, number, run_id)

        identity, _ = current_target(repo, number, expected_issue, pr=initial_pr)
        require_unique_open_pr_head(repo, number, identity["head_sha"])
        receipt.update({
            "issue": identity["issue"], "base_ref": identity["base_ref"],
            "base_sha": identity["base_sha"], "head_sha": identity["head_sha"],
            "merge_preview_sha": identity["merge_preview_sha"],
            "issue_body_sha256": identity["issue_body_sha256"],
        })
        config0 = load_config(repo)
        source0 = verify_execution_source(repo, identity["base_sha"], workflow_sha)
        selected0, report0, raw0 = report_comment(repo, number, config0)
        require(report0.get("issue") == identity["issue"], "signed report issue differs from live PR reference")
        require(report0.get("pull_request") == number, "signed report PR differs from live PR")
        report_sha = validate_signed_report(repo, identity, config0, selected0, raw0)
        evidence_ids = required_evidence(repo, identity)
        receipt.update({"report_sha256": report_sha,
                        "configuration_fingerprint": config0.fingerprint,
                        "required_check_ids": evidence_ids})

        final_revalidation(repo, number, identity, config0, selected0, source0, evidence_ids)
        publish_check(
            repo, head, number, check_id, run_id, "success", receipt, identity=identity,
            before_patch=lambda: final_revalidation(
                repo, number, identity, config0, selected0, source0, evidence_ids
            ),
        )
        print(ACCEPTED_TEXT)
        return 0
    except Exception as exc:
        receipt["blocker"] = type(exc).__name__
        if head and SHA_RE.fullmatch(head):
            try:
                publish_check(repo, head, number, check_id, run_id, "failure", receipt, identity=identity)
            except Exception:
                # Do not mask the original failure or print response bodies/tokens.
                pass
        print(f"BLOCK: solo audit attestation validation failed ({type(exc).__name__})", file=sys.stderr)
        return 2


def verify_runtime_context(repo: str, workflow_sha: str, run_id: str, event_name: str) -> None:
    require(REPOSITORY_RE.fullmatch(repo) is not None, "invalid repository argument")
    require(SHA_RE.fullmatch(workflow_sha) is not None, "invalid workflow SHA")
    require(run_id.isdecimal() and int(run_id) > 0, "invalid trusted Actions run ID")
    require(os.environ.get("GITHUB_REF_PROTECTED") == "true",
            "GitHub does not report the workflow ref as protected")
    ref = os.environ.get("GITHUB_REF", "")
    trusted_branch_ref = ref in {"refs/heads/develop", "refs/heads/main"}
    trusted_review_ref = (event_name == "pull_request_review"
                          and re.fullmatch(r"refs/pull/[1-9][0-9]*/merge", ref) is not None)
    require(trusted_branch_ref or trusted_review_ref,
            "workflow is not running from a protected branch or authenticated review ref")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a signed solo-context audit on an exact PR HEAD")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--event", required=True, type=Path)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        event_name = os.environ.get("GITHUB_EVENT_NAME", "")
        verify_runtime_context(args.repo, args.workflow_sha, args.run_id, event_name)
        event_raw = args.event.read_bytes()
        require(len(event_raw) <= 5 * 1024 * 1024, "GitHub event payload exceeds the input bound")
        event = json.loads(event_raw)
        targets = resolve_targets(args.repo, event, event_name)
        if not targets:
            print("No eligible open PR targets for this trusted event.")
            return 0
        codes = [evaluate_target(args.repo, number, issue, args.workflow_sha, args.run_id)
                 for number, issue in targets]
        return 0 if all(code == 0 for code in codes) else 2
    except Exception as exc:
        print(f"BLOCK: trusted solo gate could not validate event ({type(exc).__name__})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
