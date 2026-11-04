#!/usr/bin/env python3
"""Authenticated GitHub facts for session review, evaluated only by trusted code.

The caller injects the GitHub API transport; untrusted candidate code and
operator narratives cannot select the source of authority.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from typing import TYPE_CHECKING

from session_review import PROVENANCE_TYPE, SHA, canonical, digest, require, strict_json

if TYPE_CHECKING:
    from pathlib import Path


def authenticated_certificate_event(identity: dict, api) -> dict:
    """Rebuild the certificate event using live GitHub PR and ordered merge parents."""
    repo, number = identity["repository"], identity["pull_request"]
    pr = api(f"/repos/{repo}/pulls/{number}")
    require(isinstance(pr, dict), "malformed authenticated PR response")
    head, base = pr.get("head") or {}, pr.get("base") or {}
    require(isinstance(head, dict) and isinstance(base, dict), "malformed PR base/head")
    preview = pr.get("merge_commit_sha")
    require(pr.get("number") == number and pr.get("state") == "open" and pr.get("draft") is False
            and head.get("sha") == identity["head_sha"]
            and base.get("sha") == identity["base_sha"] and base.get("ref") == identity["base_ref"]
            and (head.get("repo") or {}).get("full_name") == repo
            and (base.get("repo") or {}).get("full_name") == repo
            and isinstance(preview, str) and re.fullmatch("[0-9a-f]{40}", preview)
            and preview == identity["merge_preview_sha"], "PR identity/preview drift")
    merge = api(f"/repos/{repo}/git/commits/{preview}")
    parents = merge.get("parents") if isinstance(merge, dict) else None
    require(isinstance(merge, dict) and merge.get("sha") == preview and isinstance(parents, list)
            and len(parents) == 2 and all(isinstance(p, dict) for p in parents)
            and [p.get("sha") for p in parents] == [identity["base_sha"], identity["head_sha"]],
            "merge preview has incorrect ordered base/HEAD parents")
    return {"repository": {"full_name": repo}, "pull_request": {
        "number": number, "title": pr.get("title") or "", "body": pr.get("body") or "",
        "merge_commit_sha": preview, "base": {"ref": identity["base_ref"], "sha": identity["base_sha"]},
        "head": {"sha": identity["head_sha"], "repo": {"full_name": repo}}}}


def authenticated_preview_reconciliation(identity: dict, certified_sha: str, api) -> dict:
    """Reconcile GitHub synthetic merges only after authenticating both Git commits."""
    current = identity["merge_preview_sha"]
    require(isinstance(certified_sha, str) and SHA.fullmatch(certified_sha)
            and isinstance(current, str) and SHA.fullmatch(current),
            "invalid certified or current merge preview identity")
    proof = {"certified_sha": certified_sha, "current_sha": current}
    if certified_sha == current:
        # The authenticated_certificate_event reader already validated parents.
        return {**proof, "mode": "exact"}

    def checked_commit(sha: str) -> str:
        obj = api(f"/repos/{identity['repository']}/git/commits/{sha}")
        parents = obj.get("parents") if isinstance(obj, dict) else None
        tree = obj.get("tree") if isinstance(obj, dict) else None
        require(isinstance(obj, dict) and obj.get("sha") == sha
                and isinstance(parents, list) and len(parents) == 2
                and all(isinstance(p, dict) for p in parents)
                and [p.get("sha") for p in parents] == [identity["base_sha"], identity["head_sha"]],
                "merge preview has incorrect ordered base/HEAD parents")
        require(isinstance(tree, dict) and isinstance(tree.get("sha"), str)
                and SHA.fullmatch(tree["sha"]), "authenticated merge preview tree is missing")
        return tree["sha"]

    original_tree = checked_commit(certified_sha)
    current_tree = checked_commit(current)
    require(original_tree == current_tree, "merge preview tree differs from certified result")
    return {**proof, "mode": "equivalent-ordered-parents-and-tree", "tree_sha": original_tree,
            "ordered_parents": [identity["base_sha"], identity["head_sha"]]}


def reconcile_target(packet: dict, live_identity: dict,
                     authenticated_certificate_event, authenticated_preview_reconciliation) -> dict | None:
    """Stabilize the certified preview without weakening the exact base/HEAD checks."""
    original = packet["identity"]
    if "merge_preview_reconciliation" not in packet:
        require(live_identity == original, "PR or issue identity/preview changed")
        return None
    current_fields = {k: v for k, v in live_identity.items() if k != "merge_preview_sha"}
    stable_fields = {k: v for k, v in original.items() if k != "merge_preview_sha"}
    require(current_fields == stable_fields, "PR or issue base/HEAD/source identity changed")
    authenticated_certificate_event(live_identity)
    proof = authenticated_preview_reconciliation(live_identity, original["merge_preview_sha"])
    require(packet["merge_preview_reconciliation"]["certified_sha"] == proof["certified_sha"],
            "certification preview identity was replaced")
    return proof


def authenticated_implementation_provenance(identity: dict, metadata: dict, pages, api) -> dict:
    """Rebuild the linear material commit chain using only authenticated GitHub API."""
    repo, number = identity["repository"], identity["pull_request"]
    commits = pages(repo, f"pulls/{number}/commits")
    require(bool(commits) and len(commits) <= 2500, "material GitHub PR commits missing or truncated")
    seen, previous, shas = set(), identity["base_sha"], []
    for row in commits:
        sha = row.get("sha")
        require(isinstance(sha, str) and SHA.fullmatch(sha) and sha not in seen,
                "invalid or duplicate GitHub PR material commit")
        obj = api(f"/repos/{repo}/git/commits/{sha}")
        parents = obj.get("parents") if isinstance(obj, dict) else None
        require(isinstance(obj, dict) and obj.get("sha") == sha
                and isinstance(parents, list) and len(parents) == 1
                and isinstance(parents[0], dict) and parents[0].get("sha") == previous,
                "GitHub PR commits are not an authenticated linear material chain from base")
        seen.add(sha)
        shas.append(sha)
        previous = sha
    require(previous == identity["head_sha"], "GitHub PR commits do not terminate at material HEAD")
    return {"type": PROVENANCE_TYPE, "repository": repo, "pull_request": number,
            "issue": identity["issue"], "base_sha": identity["base_sha"],
            "head_sha": identity["head_sha"], "commits": shas,
            "handoff": {"artifact_id": metadata["artifact_id"], "digest": metadata["artifact_digest"]}}


def certified_evidence(identity: dict, checks: dict, directory: Path, *, api, unpack,
                       authenticated_certificate_event, authenticated_preview_reconciliation,
                       root: Path) -> tuple[dict, set[str]]:
    """Technical workflow authentication is reused, not replaced by check-name matching."""
    from verify_independent_pr_audit import HANDOFF, required_checks_green, trusted_workflow_check
    repo, number = identity["repository"], identity["pull_request"]
    head, base = identity["head_sha"], identity["base_sha"]
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    require(bool(token), "GitHub credential missing")
    trust = lambda name, check: trusted_workflow_check(repo, number, name, check, head, base, token)
    # Session mode certifies all targets, including main. The legacy human route is unchanged.
    required_checks_green(checks, head, "develop", trust)
    candidates = [c for c in checks["check_runs"] if c.get("name") == HANDOFF and c.get("head_sha") == head and trust(HANDOFF, c)]
    chosen = max(candidates, key=lambda c: c["id"])
    run_id = int(re.search(r"/actions/runs/(\d+)/", chosen["details_url"])[1])
    artifacts = api(f"/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100")
    require(artifacts.get("total_count") == len(artifacts.get("artifacts", [])), "artifact inventory truncated")
    name = f"handoff-evidence-{number}-{head}"
    matches = [a for a in artifacts["artifacts"] if a.get("name") == name and not a.get("expired")]
    require(len(matches) == 1, "exact-SHA evidence artifact missing or ambiguous")
    artifact = matches[0]
    raw = api(f"/repos/{repo}/actions/artifacts/{artifact['id']}/zip", binary=True)
    require(artifact.get("digest") == "sha256:" + digest(raw), "artifact transport digest mismatch")
    unpack(raw, directory)
    sys.path.insert(0, str(root / "entregar-issue/scripts"))
    from build_test_candidate_index import collect
    from require_actions_handoff_certificate import verify
    event = authenticated_certificate_event(identity)
    recorded_raw = (directory / "certification-event.json").read_bytes()
    recorded = strict_json(recorded_raw.decode())
    recorded_pr = recorded.get("pull_request")
    require(isinstance(recorded_pr, dict),
            "certification event altered or stale against authenticated PR")
    certified_sha = recorded_pr.get("merge_commit_sha")
    # The authenticated live event is the template. Only the test-merge object
    # may differ; all other bytes remain bound to the trusted PR/issue.
    expected = copy.deepcopy(event)
    expected["pull_request"]["merge_commit_sha"] = certified_sha
    require(recorded == expected, "certification event altered or stale against authenticated PR")
    proof = authenticated_preview_reconciliation(identity, certified_sha)
    # The original pre-test preview and the preview written into the handoff
    # may differ from GitHub's current synthetic merge without changing code.
    # Authenticate the third commit before giving the strict legacy verifier
    # a temporary event; never rewrite the ZIP or its original-event digest.
    preflight_snapshot = strict_json((directory / "handoff-preflight.json").read_text(encoding="utf-8"))
    original_preview = recorded_pr.get("merge_commit_sha")
    require(isinstance(preflight_snapshot, dict)
            and isinstance(preflight_snapshot.get("identity"), dict)
            and preflight_snapshot["identity"].get("merge_preview_sha") == original_preview,
            "pre-test merge preview differs from authenticated snapshot")
    certificate = strict_json((directory / ".audit/entregar-issue/handoff-ready.json").read_text(encoding="utf-8"))
    certificate_identity = certificate.get("identity") if isinstance(certificate, dict) else None
    require(isinstance(certificate_identity, dict), "certified handoff identity is missing")
    certificate_preview = certificate_identity.get("material_merge_preview_sha")
    require(isinstance(certificate_preview, str) and SHA.fullmatch(certificate_preview)
            and certificate_identity.get("merge_preview_sha") == certificate_preview,
            "certified handoff merge preview is missing or inconsistent")
    certificate_reconciliation = authenticated_preview_reconciliation(identity, certificate_preview)
    verified_event = copy.deepcopy(recorded)
    verified_event["pull_request"]["merge_commit_sha"] = certificate_preview
    event_path = directory / "trusted-event.json"
    event_path.write_bytes(canonical(verified_event))
    verify(directory, event_path, identity["base_ref"])
    preflight = json.loads((directory / "handoff-preflight.json").read_bytes())
    require(preflight["identity"]["issue_number"] == identity["issue"]
            and preflight["identity"]["base_sha"] == base, "certificate issue/base mismatch")
    require(preflight["source"]["issue_body_sha256"] == identity["issue_sha256"], "canonical issue changed since certification")
    facts = json.loads((directory / "test-execution-facts.json").read_bytes())
    require(facts.get("subject_sha") == head and facts.get("verification") == "passed"
            and facts.get("execution", {}).get("exit_code") == 0, "test execution not proven")
    require(digest((directory / "pytest-exact-head.log").read_bytes()) == facts["execution"]["log_sha256"], "test log digest mismatch")
    junit = directory / "pytest-exact-head.xml"
    require(not any(marker in junit.read_bytes().upper() for marker in (b"<!DOCTYPE", b"<!ENTITY")), "unsafe JUnit XML")
    index = collect(junit, head)
    require(index["counts"]["failure"] == 0 and index["counts"]["error"] == 0, "JUnit contains failing tests")
    metadata = {"artifact_digest": artifact["digest"], "artifact_id": artifact["id"], "certified_at": chosen["completed_at"],
                "technical_check_ids": sorted(c["id"] for c in checks["check_runs"] if c.get("name") in
                                             {"Structure and tests", "Offline authorization tests", HANDOFF})}
    metadata["merge_preview_reconciliation"] = proof
    metadata["certified_handoff_preview_reconciliation"] = certificate_reconciliation
    metadata["certification_event_sha256"] = digest(recorded_raw)
    return metadata, {t["id"] for t in index["tests"] if t["status"] == "passed"}
