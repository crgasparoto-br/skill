#!/usr/bin/env python3
"""Trusted GitHub Actions publisher for a verified certified-handoff artifact.

Run only under workflow_run from the default branch. Never execute PR code
while the privileged GITHUB_TOKEN is available.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

HEX_SHA = re.compile(r"[0-9a-f]{40}\Z")
REF = re.compile(r"(?:feat|fix|chore|docs)/[A-Za-z0-9_.-]+\Z")
PREFIX = ".audit/entregar-issue/"
CERTIFICATE = PREFIX + "handoff-ready.json"
SCRIPT_ROOT = Path(__file__).resolve().parent
MAX_EXECUTION_PROOF_BYTES = 2 * 1024 * 1024
MAX_EXECUTION_BYTES = 16 * 1024 * 1024


def block(message: str) -> None:
    raise ValueError(message)


def command(*values: str, cwd: Path | None = None) -> str:
    proc = subprocess.run(list(values), cwd=cwd, check=True, text=True, capture_output=True)
    return proc.stdout.strip()


def api_get(repository: str, endpoint: str) -> dict:
    token = os.environ.get("GH_TOKEN")
    api = os.environ.get("GITHUB_API_URL", "")
    if not token or not api.startswith("https://"):
        block("trusted publication requires GH_TOKEN and a valid GitHub API endpoint")
    request = urllib.request.Request(
        f"{api.rstrip('/')}/repos/{repository}/{endpoint.lstrip('/')}",
        headers={"Accept": "application/vnd.github+json",
                 "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        block("GitHub API returned a non-object response")
    return result


def target_from_event(event: dict, base_ref: str = "develop",
                      producer_path: str = ".github/workflows/handoff-evidence.yml") -> tuple[str, int, str, str]:
    if not re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml", producer_path):
        block("producer workflow path must be a GitHub Actions workflow file")
    run = event.get("workflow_run") or {}
    repo = (event.get("repository") or {}).get("full_name")
    prs = run.get("pull_requests") or []
    head = run.get("head_sha")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(repo)):
        block("invalid workflow repository identity")
    if (run.get("status") != "completed" or run.get("conclusion") != "success"
            or run.get("event") != "pull_request"
            or run.get("path") != producer_path
            or not HEX_SHA.fullmatch(str(head))
            or len(prs) != 1):
        block("only one completed, successful PR evidence run is eligible")
    pr_number = prs[0].get("number")
    if not isinstance(pr_number, int) or pr_number < 1:
        block("missing PR number in workflow_run event")
    pr = api_get(repo, f"pulls/{pr_number}")
    branch = (pr.get("head") or {}).get("ref")
    actual = (pr.get("head") or {}).get("sha")
    base = (pr.get("base") or {}).get("sha")
    if (pr.get("state") != "open" or actual != head
            or (pr.get("head") or {}).get("repo", {}).get("full_name") != repo
            or (pr.get("base") or {}).get("ref") != base_ref
            or not HEX_SHA.fullmatch(str(base)) or not REF.fullmatch(str(branch))):
        block("PR was closed, moved, forked, or changed identity since CI")
    return repo, pr_number, head, base


def allowed_paths(cert: dict) -> list[str]:
    from handoff_postcondition import require_final_phase
    require_final_phase(cert)
    policy = cert.get("certificate_commit_policy") or {}
    paths = policy.get("allowed_paths")
    if policy.get("mode") != "result-only-child" or not isinstance(paths, list):
        block("certificate does not authorize a result-only child")
    normalized = set()
    for item in paths:
        if not isinstance(item, str) or not item.startswith(PREFIX):
            block("certificate attempted to authorize a non-audit path")
        p = PurePosixPath(item)
        if ".." in p.parts or str(p) != item or not re.fullmatch(r"[A-Za-z0-9_./+-]+", item):
            block("certificate contains an unsafe or unrecognized audit path")
        normalized.add(item)
    if CERTIFICATE not in normalized:
        block("certificate is not included in its own allowlist")
    if not normalized:
        block("empty result-only allowlist")
    return sorted(normalized)


def safe_bundle_path(bundle: Path, relative: str) -> Path:
    path = bundle / relative
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(bundle.resolve()):
        block(f"missing or unsafe certified artifact: {relative}")
    return path


def materialize_grounding_proofs(source: Path, bundle: Path, cert: dict,
                                 grounded: Path, head: str) -> None:
    """Install only authenticated execution data before the trusted grounding gate."""
    from audit_artifact_io import artifact_metadata, load_json_artifact
    from bind_grounding_execution import EXECUTION_PREFIX, execution_path, sha256
    from validate_codebase_grounding import check_passed_test_evidence

    authorized = set(allowed_paths(cert))
    expected = cert["artifacts"]["codebase_grounding"]
    if PREFIX + expected["name"] not in authorized or artifact_metadata(grounded)["sha256"] != expected["sha256"]:
        block("grounding report is not an authenticated, allowlisted artifact")
    report = load_json_artifact(grounded, require_object=True)
    if report.get("subject_sha") != head:
        block("grounding execution report belongs to another material SHA")
    decisions = report.get("test_decisions", [])
    if not isinstance(decisions, list) or any(not isinstance(item, dict) for item in decisions):
        block("grounding test decision inventory is malformed")
    copies = {}
    for item in decisions:
        proof = item.get("verification") or {}
        if not isinstance(proof, dict):
            block("grounding execution proof is malformed")
        relative = proof.get("evidence_path")
        if not isinstance(relative, str) or not relative.startswith(EXECUTION_PREFIX):
            continue  # Existing attested evidence outside the producer stays in the material tree.
        if proof.get("status") != "passed" or relative not in authorized:
            block("grounding execution proof is not explicitly authorized by the certificate")
        artifact = execution_path(bundle, relative)
        if not artifact.is_file() or artifact.stat().st_size > MAX_EXECUTION_PROOF_BYTES:
            block("grounding execution proof is missing or exceeds its size bound")
        errors = []
        check_passed_test_evidence(item, bundle, head, errors)
        if errors:
            block("; ".join(errors))
        raw = artifact.read_bytes()
        if sha256(raw) != proof.get("evidence_sha256"):
            block("grounding execution proof changed after authentication")
        destination = execution_path(source, relative)
        if destination.exists() and (not destination.is_file() or destination.read_bytes() != raw):
            block("grounding execution destination contains conflicting material")
        copies[relative] = (destination, raw)
        if sum(len(data) for _, data in copies.values()) > MAX_EXECUTION_BYTES:
            block("grounding execution proof inventory exceeds its size bound")
    # Do not write a partial set when any later proof fails authentication.
    for destination, raw in copies.values():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)


def validate_certificate(repo: str, pr: int, head: str, base: str, source: Path,
                         bundle: Path, cert: dict, branch: str, base_ref: str = "develop") -> None:
    subject = cert.get("subject") or {}
    identity = cert.get("identity") or {}
    issue = subject.get("issue_number")
    if (subject.get("repository") != repo or subject.get("pull_request_number") != pr
            or subject.get("work_item_kind") != "pr" or subject.get("work_item_number") != pr
            or subject.get("base_ref") != base_ref or subject.get("head_ref") != branch
            or identity.get("material_head_sha") != head or identity.get("base_sha") != base
            or not isinstance(issue, int) or issue < 1):
        block("the certificate subject does not match the live PR")
    scope = cert.get("scope") or {}
    start = scope.get("work_item_start_sha")
    if not HEX_SHA.fullmatch(str(start)):
        block("certificate lacks a valid issue start SHA")
    command("git", "merge-base", "--is-ancestor", start, head, cwd=source)
    diff = set(command("git", "diff", "--name-only", "--no-renames", start, head, cwd=source).splitlines())
    if diff != set(scope.get("issue_changed_paths") or []):
        block("certified material diff differs from the exact Git tree")
    args = [
        "--certificate", str(bundle / CERTIFICATE), "--artifacts-dir", str(bundle / PREFIX),
        "--head-sha", head, "--base-sha", base, "--repository", repo,
        "--issue-number", str(issue), "--work-item-kind", "pr",
        "--work-item-number", str(pr), "--pull-request-number", str(pr),
        "--work-item-start-sha", start, "--base-ref", base_ref, "--head-ref", branch,
        "--source-repository-root", str(source),
    ]
    for path in sorted(diff):
        args.extend(["--issue-changed-path", path])
    command("python", str(SCRIPT_ROOT / "validate_handoff_certificate.py"), *args)
    reports = cert.get("artifacts") or {}
    grounding = reports.get("codebase_grounding")
    if isinstance(grounding, dict) and grounding.get("name"):
        grounded = safe_bundle_path(bundle, PREFIX + grounding["name"])
        materialize_grounding_proofs(source, bundle, cert, grounded, head)
        command("python", str(SCRIPT_ROOT / "validate_codebase_grounding.py"),
                "--repo", str(source), "--report", str(grounded),
                "--base-sha", start, "--head-sha", head)
    growth = reports.get("code_growth")
    if isinstance(growth, dict) and growth.get("name"):
        fresh = source.parent / "trusted-code-growth.json"
        command("python", str(SCRIPT_ROOT / "check_code_growth.py"),
                "--repo", str(source), "--base-sha", start, "--head-sha", head,
                "--out", str(fresh))
        report = json.loads(fresh.read_text(encoding="utf-8"))
        if (report.get("status") != "passed" or report.get("subject_sha") != head
                or report.get("blocking_files")):
            block("independent CODE-GROWTH-001 recomputation did not pass")


def terminal_args(cert: dict, repo: str, pr: int, head: str, base: str, published: str,
                  changed: list[str], audit: Path, branch: str, material_parent: Path,
                  base_ref: str = "develop") -> list[str]:
    args = [
        "python", str(SCRIPT_ROOT / "validate_terminal_handoff.py"),
        "--certificate", str(audit / "handoff-ready.json"),
        "--artifacts-dir", str(audit), "--repository", repo,
        "--issue-number", str(cert["subject"]["issue_number"]),
        "--work-item-kind", "pr", "--work-item-number", str(pr),
        "--pull-request-number", str(pr), "--base-ref", base_ref, "--head-ref", branch,
        "--material-head-sha", head, "--published-head-sha", published,
        "--published-parent-sha", head, "--current-head-sha", published,
        "--current-parent-sha", head, "--base-sha", base,
        "--material-parent-repository", str(audit.parents[1]),
    ]
    for path in changed:
        args.extend(["--published-changed-path", path, "--current-changed-path", path])
    if cert.get("previous_independent_rejection"):
        past = audit / "previous-audit-escape-closure.json"
        if not past.is_file():
            block("previous audit escape snapshot not available for the terminal guard")
        args.extend(["--previous-audit-escape-closure", str(past)])
        if cert.get("remediation_mode") in {"systemic-remediation", "mixed-remediation"}:
            previous = audit / "previous-inherited-controls.json"
            if not previous.is_file():
                block("previous inherited controls unavailable")
            args.extend(["--previous-inherited-controls", str(previous)])
    for filename, argument in (
        ("inherited-controls.json", "--material-parent-inherited-controls"),
        ("audit-escape-closure.json", "--material-parent-audit-escape-closure"),
    ):
        historical = material_parent / filename
        if historical.is_file():
            args.extend([argument, str(historical)])
    return args


def material_parent_snapshots(source: Path, temp: Path, head: str) -> Path:
    """Capture exact material blobs; absence stays absence until the terminal Git proof."""
    from validate_terminal_handoff import material_parent_blob

    folder = temp / "material-parent-snapshots"
    folder.mkdir()
    for name in ("inherited-controls.json", "audit-escape-closure.json"):
        raw = material_parent_blob(source, head, PREFIX + name)
        if raw is not None:
            (folder / name).write_bytes(raw)
    return folder


def check_material_ci(repository: str, head: str, pr_number: int,
                      required_checks: set[str] | None = None) -> None:
    """Require a terminal success from every observed PR workflow at this material SHA."""
    result = api_get(repository, f"actions/runs?head_sha={head}&per_page=100")
    observed = [
        row for row in result.get("workflow_runs") or []
        if row.get("head_sha") == head and row.get("event") == "pull_request"
        and any(ref.get("number") == pr_number for ref in row.get("pull_requests") or [])
    ]
    if not observed or result.get("total_count", 0) > 100:
        block("cannot prove complete current material CI inventory")
    latest = {}
    for row in observed:
        identifier = row.get("workflow_id")
        if identifier is None:
            block("CI run without workflow identity")
        if identifier not in latest or row.get("run_number", 0) > latest[identifier].get("run_number", 0):
            latest[identifier] = row
    names = {row.get("name") for row in latest.values()}
    required = required_checks if required_checks is not None else {
        "Validate skills", "Validate GitHub Audit MCP",
        "Collect and certify exact-SHA handoff"}
    if not required or any(not name.strip() for name in required):
        block("at least one explicit CI workflow name is mandatory")
    if not required.issubset(names):
        block("required current material PR checks are not present")
    if any(row.get("status") != "completed" or row.get("conclusion") != "success"
           for row in latest.values()):
        block("material PR workflow run is not terminal success")


def publish(event_path: Path, *, base_ref: str = "develop",
            producer_path: str = ".github/workflows/handoff-evidence.yml",
            required_checks: set[str] | None = None) -> str:
    event = json.loads(event_path.read_text(encoding="utf-8"))
    repo, pr_number, head, base = target_from_event(event, base_ref, producer_path)
    run_id = event["workflow_run"]["id"]
    name = f"handoff-evidence-{pr_number}-{head}"
    listed = api_get(repo, f"actions/runs/{run_id}/artifacts?per_page=100")
    matching = [a for a in listed.get("artifacts") or [] if a.get("name") == name and not a.get("expired")]
    if len(matching) != 1:
        block("expected exactly one non-expired exact-SHA certified artifact")

    with tempfile.TemporaryDirectory(prefix="trusted-handoff-") as work:
        temp = Path(work)
        bundle = temp / "bundle"
        bundle.mkdir()
        command("gh", "run", "download", str(run_id), "--repo", repo,
                "--name", name, "--dir", str(bundle))
        cert = json.loads(safe_bundle_path(bundle, CERTIFICATE).read_text(encoding="utf-8"))
        status = json.loads(safe_bundle_path(bundle, "handoff-certification-status.json").read_text(encoding="utf-8"))
        if (status.get("status") != "certificate-generated" or status.get("material_head_sha") != head
                or status.get("terminal_ready") is not False or status.get("certificate_published") is not False):
            block("untrusted Action artifact is not a valid certificate-generation receipt")
        paths = allowed_paths(cert)
        for path in paths:
            safe_bundle_path(bundle, path)

        # The worktree contains PR SOURCE as data. All executed Python comes
        # from the trusted default-branch checkout, never from the PR worktree.
        trusted = Path.cwd()
        command("git", "fetch", "--no-tags", "origin", head, cwd=trusted)
        source = temp / "source"
        command("git", "worktree", "add", "--detach", str(source), head, cwd=trusted)
        if command("git", "rev-parse", "HEAD", cwd=source) != head:
            block("downloaded material differs from the recorded SHA")
        pr = api_get(repo, f"pulls/{pr_number}")
        branch = pr["head"]["ref"]
        validate_certificate(repo, pr_number, head, base, source, bundle, cert, branch, base_ref)
        check_material_ci(repo, head, pr_number, required_checks)

        material_parent = material_parent_snapshots(source, temp, head)
        existing = set(command("git", "ls-files", "--", PREFIX, cwd=source).splitlines())
        if existing - set(paths):
            block("material HEAD contains stale audit paths outside the certificate allowlist")
        for path in paths:
            dest = source / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(safe_bundle_path(bundle, path).read_bytes())
        command("git", "add", "--", *paths, cwd=source)
        changed = command("git", "diff", "--cached", "--name-only", cwd=source).splitlines()
        if not changed or not set(changed).issubset(paths) or CERTIFICATE not in changed:
            block("result-only candidate differs from the certified allowlist")
        command("git", "-c", "user.name=github-actions[bot]",
                "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                "commit", "-m", f"ci(handoff): certify issue {cert['subject']['issue_number']} PR {pr_number}",
                cwd=source)
        published = command("git", "rev-parse", "HEAD", cwd=source)
        if command("git", "rev-parse", "HEAD^", cwd=source) != head:
            block("the result-only child has an incorrect parent")
        # Prepublication: synthetic published/current identity on the exact local
        # commit. A failure MUST NOT publish the commit.
        command(*terminal_args(cert, repo, pr_number, head, base, published,
                               changed, source / PREFIX, branch, material_parent, base_ref), cwd=trusted)
        fresh = api_get(repo, f"pulls/{pr_number}")
        if fresh.get("state") != "open" or fresh["head"]["sha"] != head or fresh["base"]["sha"] != base:
            block("PR moved before the atomic fast-forward publication")
        command("git", "push", "origin", f"{published}:refs/heads/{branch}", cwd=source)
        observed = api_get(repo, f"pulls/{pr_number}")
        published_metadata = api_get(repo, f"commits/{published}")
        if (observed.get("state") != "open" or observed["head"]["sha"] != published
                or [p.get("sha") for p in published_metadata.get("parents") or []] != [head]
                or {f["filename"] for f in published_metadata.get("files") or []} != set(changed)):
            block("fresh postpublication GitHub read failed the terminal identity check")
        command(*terminal_args(cert, repo, pr_number, head, base, published,
                               changed, source / PREFIX, branch, material_parent, base_ref), cwd=trusted)
        return published


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, type=Path)
    parser.add_argument("--base-ref", default="develop")
    parser.add_argument("--producer-path", default=".github/workflows/handoff-evidence.yml")
    parser.add_argument("--required-checks-csv", default="")
    args = parser.parse_args()
    names = {name.strip() for name in args.required_checks_csv.split(",") if name.strip()}
    try:
        published = publish(args.event, base_ref=args.base_ref,
                            producer_path=args.producer_path,
                            required_checks=names or None)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"BLOCK: certified handoff publication aborted: {exc}")
        return 2
    print(f"READY: result-only handoff child published and verified {published}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
