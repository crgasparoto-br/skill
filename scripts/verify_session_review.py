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

from session_review import ASSURANCE, CHECK_NAME, POLICY_PATH, PREFIX, allowed, canonical, digest, latest_review, require, safe_path, strict_json, validate_policy, verify_review

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 32 * 1024 * 1024
WORKFLOW = ".github/workflows/session-review.yml"
# Both the emitter and its verification policy must already exist in trusted base.
TRUSTED_PATHS = (WORKFLOW, POLICY_PATH, "scripts/session_review.py", "scripts/verify_session_review.py",
                 "scripts/verify_independent_pr_audit.py", "entregar-issue/scripts/specification.py",
                 "entregar-issue/scripts/require_actions_handoff_certificate.py",
                 "entregar-issue/scripts/build_test_candidate_index.py")


def api(path: str, *, method: str = "GET", data: dict | None = None, binary: bool = False):
    """gh is used only for authenticated GitHub calls, never model inference."""
    require(path.startswith("/repos/") and ".." not in path, "unexpected GitHub endpoint")
    command = ["gh", "api", "--method", method, path]
    if data is not None:
        command.extend(["--input", "-"])
    result = subprocess.run(command, input=canonical(data) if data is not None else None,
                            capture_output=True, check=False, timeout=90)
    require(result.returncode == 0, "authenticated GitHub request failed")
    require(len(result.stdout) <= MAX_BYTES, "GitHub response exceeds size limit")
    return result.stdout if binary else json.loads(result.stdout)


def pages(repo: str, endpoint: str) -> list[dict]:
    output = []
    for page in range(1, 26):
        separator = "&" if "?" in endpoint else "?"
        batch = api(f"/repos/{repo}/{endpoint}{separator}per_page=100&page={page}")
        require(isinstance(batch, list) and all(isinstance(x, dict) for x in batch), "invalid paginated response")
        output.extend(batch)
        if len(batch) < 100:
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


def target(repo: str, number: int, issue_number: int, policy_raw: bytes) -> tuple[dict, dict]:
    pr = api(f"/repos/{repo}/pulls/{number}")
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


def certified_evidence(identity: dict, checks: dict, directory: Path) -> tuple[dict, set[str]]:
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
    sys.path.insert(0, str(ROOT / "entregar-issue/scripts"))
    from build_test_candidate_index import collect
    from require_actions_handoff_certificate import verify
    event = {"repository": {"full_name": repo}, "pull_request": {"number": number,
             "base": {"ref": identity["base_ref"]}, "head": {"sha": head, "repo": {"full_name": repo}}}}
    event_path = directory / "trusted-event.json"
    event_path.write_bytes(canonical(event))
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
    return metadata, {t["id"] for t in index["tests"] if t["status"] == "passed"}


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
    packet = {"schema_version": 1, "identity": identity, "requirements": requirements(repo, issue), **metadata,
              "allowed_assurance": ASSURANCE, "sources": files, "diffs": diffs, "passed_tests": sorted(passed),
              "canonical_issue": {k: issue[k] for k in ("number", "title", "body")},
              "disposition": "RAW_INPUT_ONLY_NOT_REVIEW_APPROVAL"}
    current, _ = target(repo, number, issue_number, policy_raw)
    require(current == identity, "PR or issue changed during collection")
    return packet, policy, files, passed


def review_journal(repo: str, sha: str) -> tuple[int, list[dict]]:
    result = api(f"/repos/{repo}/commits/{sha}/check-runs?check_name={quote(CHECK_NAME)}&filter=all&per_page=100")
    require(result.get("total_count", 0) <= len(result.get("check_runs", [])), "review journal truncated")
    watermark = 0
    entries = []
    for check in result.get("check_runs", []):
        if check.get("name") != CHECK_NAME or (check.get("app") or {}).get("id") != 15368:
            continue
        try:
            receipt = json.loads((check.get("output") or {}).get("text") or "{}")
        except ValueError:
            raise ValueError("invalid prior review receipt") from None
        value = receipt.get("review_comment_id", 0)
        minimum = receipt.get("minimum_comment_id", 0)
        require(type(value) is int and value >= 0 and type(minimum) is int and minimum >= 0, "invalid review watermark")
        watermark = max(watermark, value, minimum)
        entries.append(check)
    return watermark, entries


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


def publish(repo: str, sha: str, conclusion: str, summary: str, receipt: dict, run_id: str,
            check_id: int | None = None) -> None:
    require(run_id.isdecimal(), "authenticated Actions run required for publication")
    require(conclusion in {"success", "failure"}, "invalid check conclusion")
    body = {"name": CHECK_NAME, "head_sha": sha, "status": "completed", "conclusion": conclusion,
            "external_id": receipt.get("fingerprint", "blocked"),
            "details_url": f"https://github.com/{repo}/actions/runs/{run_id}",
            "output": {"title": "Operator-attested session review", "summary": summary,
                       "text": json.dumps(receipt, sort_keys=True)}}
    # An unchanged validated fingerprint reuses the latest receipt. No commit or
    # recursive audit is generated. A failing check always revokes earlier success.
    _, previous = review_journal(repo, sha)
    if check_id is None and conclusion == "success" and previous:
        latest = max(previous, key=lambda item: item["id"])
        if latest.get("conclusion") == "success" and latest.get("external_id") == body["external_id"]:
            return
    if check_id is None:
        result = api(f"/repos/{repo}/check-runs", method="POST", data=body)
    else:
        body.pop("head_sha")
        result = api(f"/repos/{repo}/check-runs/{check_id}", method="PATCH", data=body)
    require(result.get("head_sha") == sha and result.get("conclusion") == conclusion,
            "check publication was not confirmed")


def evaluate(repo: str, number: int, issue_number: int, packet_out: Path | None = None) -> int:
    receipt = {"third_party_identity_proven": False}
    pr = api(f"/repos/{repo}/pulls/{number}")
    head = pr["head"]["sha"]
    check_id = None
    if not packet_out:
        pending = api(f"/repos/{repo}/check-runs", method="POST", data={
            "name": CHECK_NAME, "head_sha": head, "status": "in_progress",
            "output": {"title": "Revalidating session review", "summary": "Approval is withheld until live evidence is verified."}})
        check_id = pending["id"]
    try:
        watermark, _ = review_journal(repo, head) if not packet_out else (0, [])
        local_policy = strict_json((ROOT / POLICY_PATH).read_text(encoding="utf-8"))
        watermark = max(watermark, event_review_id(local_policy)) if not packet_out else watermark
        receipt["minimum_comment_id"] = watermark
        packet, policy, files, passed = prepare(repo, number, issue_number, require_enabled=not packet_out)
        if packet_out:
            packet_out.parent.mkdir(parents=True, exist_ok=True)
            packet_out.write_bytes(canonical(packet) + b"\n")
            print("RAW PACKET: no reviewer identity or approval is asserted")
            return 0
        comments = pages(repo, f"issues/{number}/comments")
        watermark = max(watermark, event_review_id(policy))
        receipt["minimum_comment_id"] = watermark
        selected = latest_review(comments, policy, watermark=watermark)
        receipt["review_comment_id"] = selected["id"]
        # A write-capable, currently authorized operator is required in addition to
        # the numeric account allowlist. The PR author's account may be that operator.
        require(authorized_operator(repo, selected["user"]), "reviewer's permission was revoked")
        receipt = verify_review(selected, packet, policy, files, passed)
        # Re-read every mutable authority and input after verifying the review.
        latest = api(f"/repos/{repo}/issues/comments/{selected['id']}")
        require(latest == selected, "review changed during verification")
        selected_now = latest_review(pages(repo, f"issues/{number}/comments"), policy, watermark=selected["id"])
        require(selected_now == selected, "a newer review superseded this approval")
        recheck_inputs(packet)
        refreshed, _ = target(repo, number, issue_number, (ROOT / POLICY_PATH).read_bytes())
        require(refreshed == packet["identity"], "target changed before publication")
        require(authorized_operator(repo, selected["user"]), "reviewer permission changed")
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
        issue = linked_issue(pr)
        if event.get("issue") and not event["issue"].get("pull_request") and event["issue"]["number"] != issue:
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
