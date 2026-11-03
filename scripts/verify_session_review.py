#!/usr/bin/env python3
"""Trusted GitHub-hosted review reader/publisher. Never executes candidate code."""
from __future__ import annotations

import argparse
import base64
import difflib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

import session_review_github as github_facts

from session_review import (
    ASSURANCE,
    CHECK_NAME,
    POLICY_PATH,
    PREFIX,
    PROVENANCE_TYPE,
    allowed,
    canonical,
    digest,
    latest_review,
    require,
    review_snapshot,
    safe_path,
    strict_json,
    validate_policy,
    verify_review,
)

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 32 * 1024 * 1024
WORKFLOW = ".github/workflows/session-review.yml"
# Both the emitter and its verification policy must already exist in trusted base.
TRUSTED_PATHS = (WORKFLOW, POLICY_PATH, "scripts/session_review.py", "scripts/verify_session_review.py",
                 "scripts/verify_independent_pr_audit.py", "entregar-issue/scripts/specification.py",
                 "entregar-issue/scripts/require_actions_handoff_certificate.py",
                 "entregar-issue/scripts/handoff_postcondition.py", "entregar-issue/scripts/handoff_postcondition_records.py",
                 "entregar-issue/scripts/certificate_postcondition_replay.py", "entregar-issue/scripts/certificate_replay_io.py",
                 "entregar-issue/scripts/certificate_replay_source.py", "entregar-issue/scripts/audit_artifact_io.py",
                 "entregar-issue/scripts/certificate_replay_inputs.py",
                 "entregar-issue/scripts/build_test_candidate_index.py")


def api(path: str, *, method: str = "GET", data: dict | None = None, binary: bool = False):
    """gh is used only for authenticated GitHub calls, never model inference."""
    require(path.startswith("/repos/") and ".." not in path, "unexpected GitHub endpoint")
    command = ["gh", "api", "--method", method, path]
    if data is not None:
        command.extend(["--input", "-"])
    result = subprocess.run(command, input=canonical(data) if data is not None else None,
                            capture_output=True, check=False, timeout=90)
    if result.returncode != 0:
        # GitHub CLI reports HTTP status on stderr. Never print stderr, which
        # could contain sensitive response data, or query parameters.
        match = re.search(rb"\bHTTP\s+([1-5][0-9]{2})\b", result.stderr, re.IGNORECASE)
        status = f"HTTP {match.group(1).decode('ascii')}" if match else "HTTP status unavailable"
        resource = path.split("?", 1)[0]
        raise ValueError(f"authenticated GitHub {method} {resource} request failed ({status})")
    require(len(result.stdout) <= MAX_BYTES, "GitHub response exceeds size limit")
    return result.stdout if binary else json.loads(result.stdout)


def pages(repo: str, endpoint: str, *, field: str | None = None) -> list[dict]:
    output = []
    total = None
    for page in range(1, 26):
        separator = "&" if "?" in endpoint else "?"
        batch = api(f"/repos/{repo}/{endpoint}{separator}per_page=100&page={page}")
        if field:
            count = batch.get("total_count") if isinstance(batch, dict) else None
            require(type(count) is int and count >= 0 and (total is None or total == count),
                    "paginated inventory changed or is malformed")
            total, batch = count, batch.get(field)
        require(isinstance(batch, list) and all(isinstance(x, dict) for x in batch), "invalid paginated response")
        output.extend(batch)
        if total is not None:
            require(len(output) <= total, "paginated inventory exceeds declared total")
            if len(output) == total:
                return output
        if len(batch) < 100:
            require(total is None, "paginated inventory truncated")
            return output
    raise ValueError("incomplete paginated inventory")


def content(repo: str, path: str, sha: str) -> tuple[bytes, str]:
    require(safe_path(path), "unsafe source path")
    obj = api(f"/repos/{repo}/contents/{quote(path, safe='/')}?ref={sha}")
    require(isinstance(obj, dict) and obj.get("type") == "file" and obj.get("encoding") == "base64",
            "source must be a complete regular file")
    raw = base64.b64decode("".join(obj["content"].split()), validate=True)
    require(len(raw) <= 2 * 1024 * 1024, "source exceeds audit size limit")
    return raw, obj["sha"]


def target(repo: str, number: int, issue_number: int, policy_raw: bytes, *, pr: dict | None = None) -> tuple[dict, dict]:
    pr = api(f"/repos/{repo}/pulls/{number}") if pr is None else pr
    issue = api(f"/repos/{repo}/issues/{issue_number}")
    require(pr.get("state") == "open" and not pr.get("draft"), "open, non-draft PR required")
    require(pr["head"]["repo"]["full_name"] == repo and pr["base"]["repo"]["full_name"] == repo,
            "cross-repository candidate requires separate policy")
    require(issue.get("number") == issue_number and "pull_request" not in issue and isinstance(issue.get("body"), str),
            "canonical issue is missing")
    refs = {int(x) for x in re.findall(r"(?im)^\s*(?:closes|fixes|refs)\s+#([1-9][0-9]*)\s*$", pr.get("body") or "")}
    require(refs == {issue_number}, "canonical issue reference missing or ambiguous")
    identity = {"repository": repo, "pull_request": number, "issue": issue_number,
                "base_ref": pr["base"]["ref"], "base_sha": pr["base"]["sha"], "head_sha": pr["head"]["sha"],
                "merge_preview_sha": pr.get("merge_commit_sha"), "issue_sha256": digest(issue["body"].encode()),
                "policy_sha256": digest(policy_raw)}
    return identity, issue


def requirements(repo: str, issue: dict) -> list[dict]:
    # Reuse the canonical parser, with LIVE issue bytes, not a candidate-supplied list.
    sys.path.insert(0, str(ROOT / "entregar-issue/scripts"))
    from specification import extract_candidates
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        source = directory / "issue.txt"
        source.write_text(issue["body"], encoding="utf-8")
        sid = f"SRC-ISSUE-{issue['number']}"
        snapshot = {"schema_version": 1, "repository": repo, "issue": issue["number"],
                    "primary_source_id": sid, "sources": [{"id": sid, "kind": "issue-body", "textual": True,
                    "path": "issue.txt", "sha256": digest(source.read_bytes())}]}
        path = directory / "snapshot.json"
        path.write_bytes(canonical(snapshot))
        errors = []
        _, _, rows = extract_candidates(path, errors)
        require(not errors and bool(rows), "canonical obligation extraction failed")
    return rows


def unpack(raw: bytes, directory: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = set()
        total = 0
        for info in archive.infolist():
            total += info.file_size
            require(safe_path(info.filename) and info.filename not in names and total <= MAX_BYTES,
                    "unsafe, duplicated or oversized evidence archive")
            require(not stat.S_ISLNK(info.external_attr >> 16), "symlink in evidence archive")
            names.add(info.filename)
        archive.extractall(directory)


def authenticated_certificate_event(identity: dict) -> dict:
    return github_facts.authenticated_certificate_event(identity, api)


def authenticated_preview_reconciliation(identity: dict, certified_sha: str) -> dict:
    return github_facts.authenticated_preview_reconciliation(identity, certified_sha, api)


def reconcile_target(packet: dict, live_identity: dict) -> dict | None:
    return github_facts.reconcile_target(
        packet, live_identity, authenticated_certificate_event, authenticated_preview_reconciliation)


def authenticated_implementation_provenance(identity: dict, metadata: dict) -> dict:
    return github_facts.authenticated_implementation_provenance(identity, metadata, pages, api)


def certified_evidence(identity: dict, checks: dict, directory: Path) -> tuple[dict, set[str]]:
    return github_facts.certified_evidence(
        identity, checks, directory, api=api, unpack=unpack,
        authenticated_certificate_event=authenticated_certificate_event,
        authenticated_preview_reconciliation=authenticated_preview_reconciliation, root=ROOT)


def freeze_files(repo: str, changed: list[dict], base: str, head: str) -> tuple[dict, dict]:
    files, diffs = {}, {}
    total = 0
    for item in changed:
        status, path = item.get("status"), item["filename"]
        require(status in {"added", "removed", "modified", "renamed"}, "unsupported file change requires separate evidence")
        old_path = item.get("previous_filename", path)
        before = b"" if status == "added" else content(repo, old_path, base)[0]
        after = b"" if status == "removed" else content(repo, path, head)[0]
        total += len(before) + len(after)
        require(total <= MAX_BYTES, "source inventory exceeds audit budget; no silent truncation")
        before_text, after_text = before.decode("utf-8"), after.decode("utf-8")
        if status != "added":
            files["base/" + old_path] = before_text
        if status != "removed":
            files["head/" + path] = after_text
        diffs[path] = "".join(difflib.unified_diff(before_text.splitlines(keepends=True),
            after_text.splitlines(keepends=True), fromfile="base/" + old_path, tofile="head/" + path))
    return files, diffs


def authorized_operator(repo: str, user: dict) -> bool:
    repository = api(f"/repos/{repo}")
    owner = repository.get("owner") or {}
    if owner.get("type") == "User" and owner.get("id") == user.get("id") and owner.get("login") == user.get("login"):
        return True
    from verify_independent_pr_audit import is_authorized_reviewer
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return is_authorized_reviewer(repo, user["login"], token)


def prepare(repo: str, number: int, issue_number: int, *, require_enabled: bool) -> tuple[dict, dict, dict, set[str]]:
    pr = api(f"/repos/{repo}/pulls/{number}")
    base = pr["base"]["sha"]
    policy_raw, _ = content(repo, POLICY_PATH, base)
    policy = strict_json(policy_raw.decode())
    if require_enabled:
        validate_policy(policy)
    for path in TRUSTED_PATHS:
        trusted, _ = content(repo, path, base)
        require((ROOT / path).read_bytes() == trusted, "execution policy differs from trusted base")
    identity, issue = target(repo, number, issue_number, policy_raw)
    require(identity["base_sha"] == base and identity["head_sha"] == pr["head"]["sha"],
            "PR changed before source collection")
    changed = pages(repo, f"pulls/{number}/files")
    require(len(changed) == pr["changed_files"] and bool(changed), "changed-file inventory incomplete")
    files, diffs = freeze_files(repo, changed, base, identity["head_sha"])
    checks = api(f"/repos/{repo}/commits/{identity['head_sha']}/check-runs?per_page=100")
    with tempfile.TemporaryDirectory() as temporary:
        metadata, passed = certified_evidence(identity, checks, Path(temporary))
    # The material SHA and base are fixed. The certified synthetic merge
    # remains the stable review identity even when GitHub recreates its commit.
    stable = {**identity, "merge_preview_sha": metadata["merge_preview_reconciliation"]["certified_sha"]}
    packet = {"schema_version": 1, "identity": stable, "requirements": requirements(repo, issue), **metadata,
              "allowed_assurance": ASSURANCE, "sources": files, "diffs": diffs, "passed_tests": sorted(passed),
              "canonical_issue": {k: issue[k] for k in ("number", "title", "body")},
              "disposition": "RAW_INPUT_ONLY_NOT_REVIEW_APPROVAL"}
    current, _ = target(repo, number, issue_number, policy_raw)
    reconcile_target(packet, current)
    return packet, policy, files, passed


def review_journal(repo: str, sha: str) -> tuple[int, list[dict]]:
    watermark = 0
    entries = []
    checks = pages(repo, f"commits/{sha}/check-runs?check_name={quote(CHECK_NAME)}&filter=all", field="check_runs")
    require(len({check.get("id") for check in checks}) == len(checks), "duplicated review journal entry")
    for check in checks:
        if check.get("name") != CHECK_NAME or (check.get("app") or {}).get("id") != 15368:
            continue
        require(type(check.get("id")) is int and check["id"] > 0 and check.get("head_sha") == sha,
                "review journal check identity mismatch")
        try:
            receipt = strict_json((check.get("output") or {}).get("text") or "{}")
        except (ValueError, RecursionError):
            raise ValueError("invalid prior review receipt") from None
        value = receipt.get("review_comment_id", 0)
        minimum = receipt.get("minimum_comment_id", 0)
        require(type(value) is int and value >= 0 and type(minimum) is int and minimum >= 0, "invalid review watermark")
        watermark = max(watermark, value, minimum)
        entries.append(check)
    return watermark, entries


def begin_check(repo: str, sha: str, receipt: dict, previous: list[dict]) -> int:
    """The workflow serializes writers; retain the watermark when reusing its check."""
    latest = max(previous, key=lambda item: item["id"]) if previous else None
    body = {"name": CHECK_NAME, "status": "in_progress",
            "output": {"title": "Revalidating session review", "text": json.dumps(receipt, sort_keys=True),
                       "summary": "Approval is withheld until live evidence is verified."}}
    if latest:
        result = api(f"/repos/{repo}/check-runs/{latest['id']}", method="PATCH", data=body)
        require(result.get("head_sha") == sha and result.get("id") == latest["id"]
                and result.get("name") == CHECK_NAME, "existing check identity changed during revalidation")
        if result.get("status") == "completed":
            # GitHub can retain a terminal status instead of reopening the old check.
            # Start a new pending check so a stale approved result cannot remain latest.
            result = api(f"/repos/{repo}/check-runs", method="POST", data={**body, "head_sha": sha})
    else:
        result = api(f"/repos/{repo}/check-runs", method="POST", data={**body, "head_sha": sha})
    # GitHub can finalize a POST immediately. The verification may continue only
    # if the observed state cannot satisfy a required check without this review.
    status, conclusion = result.get("status"), result.get("conclusion")
    blocked = ((status in {"queued", "in_progress"} and conclusion is None)
               or (status == "completed" and conclusion == "failure"))
    observed = status if status in {"queued", "in_progress", "completed"} else "unexpected"
    require(result.get("head_sha") == sha and type(result.get("id")) is int
            and result["id"] > 0 and blocked,
            f"check identity or fail-closed state not confirmed ({observed})")
    return result["id"]


def event_review_id(policy: dict) -> int:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return 0
    event = json.loads(Path(path).read_bytes())
    comment = event.get("comment") or {}
    previous = (event.get("changes", {}).get("body") or {}).get("from", "")
    is_review = str(comment.get("body", "")).startswith(PREFIX) or str(previous).startswith(PREFIX)
    if allowed(comment, policy) and is_review:
        return int(comment["id"]) + (1 if event.get("action") in {"edited", "deleted"} else 0)
    return 0


def recheck_inputs(packet: dict) -> None:
    from verify_independent_pr_audit import required_checks_green, trusted_workflow_check
    ident = packet["identity"]
    repo, head, base = ident["repository"], ident["head_sha"], ident["base_sha"]
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    checks = api(f"/repos/{repo}/commits/{head}/check-runs?per_page=100")
    required_checks_green(checks, head, "develop", lambda name, check: trusted_workflow_check(
        repo, ident["pull_request"], name, check, head, base, token))
    ids = sorted(c["id"] for c in checks["check_runs"] if c.get("name") in {
        "Structure and tests", "Offline authorization tests", "collect / Require certified semantic handoff (exact SHA)"})
    require(ids == packet["technical_check_ids"], "technical evidence changed during verification")
    artifact = api(f"/repos/{repo}/actions/artifacts/{packet['artifact_id']}")
    require(not artifact.get("expired") and artifact.get("digest") == packet["artifact_digest"],
            "certified artifact expired or changed")
    observed, _ = target(repo, ident["pull_request"], ident["issue"], (ROOT / POLICY_PATH).read_bytes())
    reconcile_target(packet, observed)
    if "implementation_provenance" in packet:
        verified = authenticated_implementation_provenance(ident, packet)
        require(verified == packet["implementation_provenance"],
                "GitHub implementation history changed during review")


def publish(repo: str, sha: str, conclusion: str, summary: str, receipt: dict, run_id: str,
            check_id: int | None = None) -> None:
    require(run_id.isdecimal(), "authenticated Actions run required for publication")
    require(conclusion in {"success", "failure"}, "invalid check conclusion")
    require(conclusion != "success" or (receipt.get("identity") or {}).get("head_sha") == sha,
            "approved evidence does not authorize this check SHA")
    body = {"name": CHECK_NAME, "head_sha": sha, "status": "completed", "conclusion": conclusion,
            "external_id": receipt.get("fingerprint", "blocked"),
            "details_url": f"https://github.com/{repo}/actions/runs/{run_id}",
            "output": {"title": "Operator-attested session review", "summary": summary,
                       "text": json.dumps(receipt, sort_keys=True)}}
    # Failure publication must remain possible when reading the journal failed.
    if check_id is None:
        result = api(f"/repos/{repo}/check-runs", method="POST", data=body)
    else:
        current = api(f"/repos/{repo}/check-runs/{check_id}")
        require(current.get("head_sha") == sha and current.get("name") == CHECK_NAME
                and (current.get("app") or {}).get("id") == 15368,
                "existing check belongs to another target or publisher")
        body.pop("head_sha")
        result = api(f"/repos/{repo}/check-runs/{check_id}", method="PATCH", data=body)
    require(result.get("head_sha") == sha and result.get("conclusion") == conclusion,
            "check publication was not confirmed")


def evaluate(repo: str, number: int, issue_number: int, packet_out: Path | None = None) -> int:
    receipt = {"third_party_identity_proven": False}
    pr = api(f"/repos/{repo}/pulls/{number}")
    head = pr["head"]["sha"]
    check_id = None
    try:
        watermark, previous = review_journal(repo, head) if not packet_out else (0, [])
        receipt["minimum_comment_id"] = watermark
        if not packet_out:
            check_id = begin_check(repo, head, receipt, previous)
        policy_raw = (ROOT / POLICY_PATH).read_bytes()
        local_policy = strict_json(policy_raw.decode())
        watermark = max(watermark, event_review_id(local_policy)) if not packet_out else watermark
        receipt["minimum_comment_id"] = watermark
        require(type(issue_number) is int and issue_number > 0, "canonical issue reference missing or ambiguous")
        initial, _ = target(repo, number, issue_number, policy_raw, pr=pr)
        packet, policy, files, passed = prepare(repo, number, issue_number, require_enabled=not packet_out)
        try:
            reconcile_target(packet, initial)
        except ValueError as exc:
            raise ValueError("target changed between initial observation and evidence collection") from exc
        require(initial["head_sha"] == head, "target changed between initial observation and evidence collection")
        if packet_out:
            if policy.get("implementation_provenance") == {"mode": "enabled", "type": PROVENANCE_TYPE}:
                packet["implementation_provenance"] = authenticated_implementation_provenance(packet["identity"], packet)
            packet_out.parent.mkdir(parents=True, exist_ok=True)
            packet_out.write_bytes(canonical(packet) + b"\n")
            print("RAW PACKET: no reviewer identity or approval is asserted")
            return 0
        comments = pages(repo, f"issues/{number}/comments")
        watermark = max(watermark, event_review_id(policy))
        receipt["minimum_comment_id"] = watermark
        selected = latest_review(comments, policy, watermark=watermark)
        # Historical v1 reviews do not depend on the optional GitHub recovery
        # capability, even when the trusted policy has opted into that feature.
        report_hint = strict_json(selected["body"][len(PREFIX):])
        declared = report_hint.get("sessions")
        wants_provenance = isinstance(declared, dict) and isinstance(declared.get("implementation"), dict)
        if wants_provenance and policy.get("implementation_provenance") == {
                "mode": "enabled", "type": PROVENANCE_TYPE}:
            packet["implementation_provenance"] = authenticated_implementation_provenance(packet["identity"], packet)
        snapshot = review_snapshot(selected, repo, number)
        receipt["review_comment_id"] = selected["id"]
        # A write-capable, currently authorized operator is required in addition to
        # the numeric account allowlist. The PR author's account may be that operator.
        require(authorized_operator(repo, selected["user"]), "reviewer's permission was revoked")
        receipt = verify_review(selected, packet, policy, files, passed)
        # Re-read every mutable authority and input after verifying the review.
        latest = api(f"/repos/{repo}/issues/comments/{selected['id']}")
        require(review_snapshot(latest, repo, number) == snapshot, "review changed during verification")
        selected_now = latest_review(pages(repo, f"issues/{number}/comments"), policy, watermark=selected["id"])
        require(review_snapshot(selected_now, repo, number) == snapshot,
                "a newer review superseded this approval")
        recheck_inputs(packet)
        refreshed, _ = target(repo, number, issue_number, (ROOT / POLICY_PATH).read_bytes())
        try:
            proof = reconcile_target(packet, refreshed)
        except ValueError as exc:
            raise ValueError("target changed before publication") from exc
        if proof is not None:
            receipt["merge_preview_reconciliation"] = proof
            receipt["fingerprint"] = digest(canonical({k: v for k, v in receipt.items() if k != "fingerprint"}))
        require(authorized_operator(repo, selected["user"]), "reviewer permission changed")
        # Repeat the mutable-review check after every other revalidation. A review
        # edited, deleted, rejected or superseded while the target/evidence checks
        # were running must never leave a stale success behind.
        final_review = api(f"/repos/{repo}/issues/comments/{selected['id']}")
        require(review_snapshot(final_review, repo, number) == snapshot,
                "review changed during final publication revalidation")
        final_selected = latest_review(
            pages(repo, f"issues/{number}/comments"), policy, watermark=selected["id"]
        )
        require(review_snapshot(final_selected, repo, number) == snapshot,
                "a newer review superseded this approval during final publication revalidation")
        # Last live authority check after the final comment read. GitHub may
        # regenerate its test merge during the review, or concurrently mutate
        # the base/HEAD; neither change may silently authorize publication.
        terminal, _ = target(repo, number, issue_number, (ROOT / POLICY_PATH).read_bytes())
        terminal_proof = reconcile_target(packet, terminal)
        if terminal_proof is not None:
            receipt["merge_preview_reconciliation"] = terminal_proof
            receipt["fingerprint"] = digest(canonical({k: v for k, v in receipt.items() if k != "fingerprint"}))
        summary = "Verified evidence-bound session review. Session separation is operator-attested, NOT third-party identity."
        publish(repo, head, "success", summary, receipt, os.environ.get("GITHUB_RUN_ID", ""), check_id)
        print(summary)
        return 0
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        reason = f"BLOCK: {type(exc).__name__}: {exc}"
        if not packet_out:
            publish(repo, head, "failure", reason[:4000], receipt, os.environ.get("GITHUB_RUN_ID", ""), check_id)
        print(reason, file=sys.stderr)
        return 2


def linked_issue(pr: dict) -> int:
    refs = {int(x) for x in re.findall(r"(?im)^\s*(?:closes|fixes|refs)\s+#([1-9][0-9]*)\s*$", pr.get("body") or "")}
    require(len(refs) == 1, "PR must reference exactly one canonical issue")
    return next(iter(refs))


def resolve_targets(repo: str, event: dict) -> list[tuple[int, int]]:
    require(event.get("repository", {}).get("full_name") == repo, "event repository mismatch")
    numbers = []
    if isinstance(event.get("pull_request"), dict):
        numbers = [event["pull_request"]["number"]]
    elif event.get("issue", {}).get("pull_request"):
        numbers = [event["issue"]["number"]]
    elif event.get("inputs", {}).get("pull_request"):
        numbers = [int(event["inputs"]["pull_request"])]
    elif event.get("workflow_run"):
        run = event["workflow_run"]
        require(run.get("event") == "pull_request", "not a PR technical workflow")
        numbers = [p["number"] for p in run.get("pull_requests", [])]
        if not numbers:
            numbers = [p["number"] for p in pages(repo, f"commits/{run['head_sha']}/pulls") if p.get("state") == "open"]
    else:
        numbers = [p["number"] for p in pages(repo, "pulls?state=open")]
    result = []
    for number in sorted(set(numbers)):
        pr = api(f"/repos/{repo}/pulls/{number}")
        if pr.get("state") != "open" or pr.get("base", {}).get("ref") not in {"develop", "main"}:
            continue
        try:
            issue = linked_issue(pr)
        except ValueError:
            issue = 0  # Keep the PR target so evaluate revokes a previous approval.
        if issue and event.get("issue") and not event["issue"].get("pull_request") and event["issue"]["number"] != issue:
            continue
        result.append((number, issue))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--issue", type=int)
    parser.add_argument("--event", type=Path)
    parser.add_argument("--packet-out", type=Path)
    args = parser.parse_args()
    require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo)), "invalid repository")
    if args.event:
        require(not args.pr and not args.issue and not args.packet_out, "event mode does not take explicit targets")
        targets = resolve_targets(args.repo, json.loads(args.event.read_bytes()))
    else:
        require(type(args.pr) is int and args.pr > 0 and type(args.issue) is int and args.issue > 0,
                "positive PR and issue required")
        targets = [(args.pr, args.issue)]
    results = [evaluate(args.repo, number, issue, args.packet_out) for number, issue in targets]
    return max(results, default=0)


if __name__ == "__main__":
    raise SystemExit(main())
