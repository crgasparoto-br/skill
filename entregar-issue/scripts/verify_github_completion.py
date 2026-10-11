#!/usr/bin/env python3
"""Obtain completion evidence from authenticated GitHub API, never from the implementer."""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from validate_finding_completion import validate


def github(path, token):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)


def audit_contract(review):
    """Require explicit machine-readable contract in an approved GitHub review."""
    body = review.get("body") or ""
    prefix = "SOLVERIT_AUDIT_JSON:"
    for line in body.splitlines():
        if line.startswith(prefix):
            try:
                data = json.loads(line[len(prefix):].strip())
            except json.JSONDecodeError:
                return None
            return data if isinstance(data, dict) and data.get("schema") == "solverit-audit-v1" else None
    return None


def verify(ledger, token, required_checks):
    repo = ledger["repository"]
    if not isinstance(repo, str) or repo.count("/") != 1 or any(not p.replace("-", "").replace("_", "").isalnum() for p in repo.split("/")):
        raise ValueError("invalid repository")
    number = ledger["pr_number"]
    if type(number) is not int or number < 1:
        raise ValueError("invalid PR number")
    pr = github(f"/repos/{repo}/pulls/{number}", token)
    head = pr["head"]["sha"]
    if ledger.get("head_sha") != head or pr["base"]["ref"] != "develop":
        raise ValueError("HEAD/base mismatch")
    reviews = github(f"/repos/{repo}/pulls/{number}/reviews?per_page=100", token)
    commits = github(f"/repos/{repo}/pulls/{number}/commits?per_page=100", token)
    if len(commits) == 100 or len(reviews) == 100:
        raise ValueError("pagination required; refusing incomplete review/commit set")
    implementers = {pr["user"]["login"]}
    implementers.update(c["author"]["login"] for c in commits if c.get("author"))
    valid = []
    for review in reviews:
        contract = audit_contract(review)
        reviewer = (review.get("user") or {}).get("login")
        if (review.get("state") == "APPROVED" and review.get("commit_id") == head
                and reviewer and reviewer not in implementers and contract
                and contract.get("audit_round") == ledger.get("audit_round")
                and contract.get("head_sha") == head
                and contract.get("finding_ids")):
            valid.append((review, contract))
    if not valid:
        raise ValueError("no independent exact-HEAD approved review with a valid audit contract")
    review, contract = valid[-1]
    checks = github(f"/repos/{repo}/commits/{head}/check-runs?per_page=100", token)
    runs = checks.get("check_runs", [])
    if checks.get("total_count", 0) > 100 or not required_checks:
        raise ValueError("incomplete or unspecified required CI checks")
    for name in required_checks:
        if not any(c.get("name") == name and c.get("head_sha") == head
                   and c.get("status") == "completed" and c.get("conclusion") == "success" for c in runs):
            raise ValueError(f"required check not green at HEAD: {name}")
    manifest = {"repository": repo, "pr_number": number, "audit_round": ledger["audit_round"],
                "finding_ids": contract["finding_ids"]}
    audit_url = review.get("html_url")
    if not audit_url:
        raise ValueError("review URL missing")
    attestation = {
        "repository": repo, "pr_number": number, "audit_round": ledger["audit_round"],
        "head_sha": head,
        "verified_findings": {fid: head for fid in contract.get("verified_finding_ids", [])},
        "accepted_exclusions": contract.get("accepted_exclusions", []),
        "ci": {"head_sha": head, "conclusion": "success",
               "run_url": runs[0].get("html_url") or "https://github.com/" + repo + "/actions"},
        "independent_audit": "approved", "auditor": review["user"]["login"],
        "implementer": pr["user"]["login"], "audit_url": audit_url,
    }
    return validate(ledger, manifest, attestation)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--required-check", action="append", required=True,
                        help="Actual check-run name required by the protected base branch")
    args = parser.parse_args()
    try:
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("GH_TOKEN or GITHUB_TOKEN required")
        ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
        ok, errors = verify(ledger, token, args.required_check)
    except (ValueError, KeyError, TypeError, OSError, urllib.error.URLError) as exc:
        ok, errors = False, [str(exc)]
    print(json.dumps({"verdict": "CONCLUIDO" if ok else "NAO_CONCLUIDO", "reasons": errors},
                     ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
