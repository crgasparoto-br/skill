"""Read-only provenance of the existing exact-SHA session review receipt."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

GITHUB_HOST = "github.com"
API_ROOT = urlunsplit(("https", "api." + GITHUB_HOST, "", "", ""))
CHECK = "Verify session review (exact SHA)"
WORKFLOW = ".github/workflows/session-review.yml"
POLICY = ".github/session-review-policy.json"
PREFIX = "SOLVERIT_SESSION_REVIEW_V1\n"
ASSURANCE = "operator-attested-session-review"
ACKNOWLEDGEMENT = "separate-context-declared-not-cryptographically-proven"
SHA = re.compile(r"[a-f0-9]{40}\Z")
DIGEST = re.compile(r"[a-f0-9]{64}\Z")
MARKER = re.compile(r"AUDIT_REPORT_SHA256=([a-f0-9]{64})\Z")
TRUSTED = (WORKFLOW, POLICY, ".github/workflows/reusable-handoff.yml",
           "entregar-issue/scripts/resolve_trusted_audit_transport.py",
           "entregar-issue/scripts/validate_native_actions_evidence.py",
           "scripts/session_review.py", "scripts/session_review_github.py",
           "scripts/verify_session_review.py", "scripts/verify_independent_pr_audit.py",
           "entregar-issue/scripts/specification.py",
           "entregar-issue/scripts/require_actions_handoff_certificate.py",
           "entregar-issue/scripts/handoff_merge_preview.py",
           "entregar-issue/scripts/handoff_postcondition.py",
           "entregar-issue/scripts/handoff_postcondition_records.py",
           "entregar-issue/scripts/certificate_postcondition_replay.py",
           "entregar-issue/scripts/certificate_replay_io.py",
           "entregar-issue/scripts/certificate_replay_source.py",
           "entregar-issue/scripts/audit_artifact_io.py",
           "entregar-issue/scripts/certificate_replay_inputs.py",
           "entregar-issue/scripts/build_test_candidate_index.py")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw, *, limit=65536):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    require(isinstance(raw, str) and len(raw.encode()) <= limit, "invalid bounded JSON")
    result = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(result, dict), "JSON object required")
    return result


def positive(value):
    return type(value) is int and value > 0


def sha(value, pattern=SHA):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def github_blob(api, repo, path, ref):
    row = api(f"/repos/{repo}/contents/{path}?ref={ref}")
    require(row.get("type") == "file" and row.get("encoding") == "base64"
            and sha(row.get("sha")), "trusted file provenance unavailable")
    raw = base64.b64decode("".join(row["content"].split()), validate=True)
    oid = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    require(oid == row["sha"], "trusted file digest mismatch")
    return raw


def trusted_paths_at(api, repo, ref):
    require(sha(ref), "invalid trusted source revision")
    commit = api(f"/repos/{repo}/git/commits/{ref}")
    tree = (commit.get("tree") or {}).get("sha")
    require(commit.get("sha") == ref and sha(tree), "trusted workflow commit mismatch")
    snapshot = api(f"/repos/{repo}/git/trees/{tree}?recursive=1")
    require(snapshot.get("sha") == tree and snapshot.get("truncated") is False,
            "trusted workflow tree unavailable or truncated")
    tracked = {}
    for row in snapshot.get("tree", []):
        path = row.get("path")
        if path in TRUSTED:
            require(path not in tracked and row.get("type") == "blob"
                    and row.get("mode") in {"100644", "100755"} and sha(row.get("sha")),
                    "untrusted executable source entry")
            tracked[path] = row["sha"]
    require(set(tracked) == set(TRUSTED), "trusted executable closure incomplete")
    return tracked


def require_suite(api, repo, suite_id, head):
    require(positive(suite_id), "missing GitHub check suite")
    suite = api(f"/repos/{repo}/check-suites/{suite_id}")
    require(suite.get("id") == suite_id and suite.get("head_sha") == head
            and (suite.get("app") or {}).get("id") == 15368,
            "wrong GitHub Actions check suite provenance")


def verify_origin(api, detail, repo, head, base):
    require(detail.get("name") == CHECK and detail.get("head_sha") == head
            and (detail.get("app") or {}).get("id") == 15368,
            "audit check was not produced by GitHub Actions on the exact head")
    url = urlsplit(str(detail.get("details_url") or ""))
    match = re.fullmatch(rf"/{re.escape(repo)}/actions/runs/([1-9][0-9]*)", url.path)
    require(url.scheme == "https" and url.netloc == GITHUB_HOST and match is not None
            and not url.query and not url.fragment, "invalid review workflow run URL")
    run_id = int(match.group(1))
    run = api(f"/repos/{repo}/actions/runs/{run_id}")
    workflow = api(f"/repos/{repo}/actions/workflows/session-review.yml")
    branch, source = run.get("head_branch"), run.get("head_sha")
    require(run.get("id") == run_id and positive(workflow.get("id"))
            and run.get("workflow_id") == workflow["id"] and workflow.get("path") == WORKFLOW,
            "review workflow identity does not match the protected workflow")
    require(branch in {"main", "develop"} and sha(source)
            and run.get("path") in {WORKFLOW, f"{WORKFLOW}@refs/heads/{branch}"}
            and (run.get("repository") or {}).get("full_name") == repo
            and (run.get("head_repository") or {}).get("full_name") == repo
            and run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("event") in {"issue_comment", "workflow_run", "pull_request_target", "issues", "push"},
            "review workflow is not a trusted protected-source run")
    require(api(f"/repos/{repo}/branches/{branch}").get("protected") is True,
            "review workflow source branch is not protected")
    require_suite(api, repo, (detail.get("check_suite") or {}).get("id"), head)
    require_suite(api, repo, run.get("check_suite_id"), source)
    require(trusted_paths_at(api, repo, base) == trusted_paths_at(api, repo, source),
            "review executable workflow source differs from trusted base")


def require_preview_equivalence(api, repo, base, head, certified, current):
    """Read authenticated GitHub commits without substituting the certified identity."""
    require(all(sha(value) for value in (base, head, certified, current)),
            "invalid certified or live merge preview identity")
    trees = set()
    for preview in dict.fromkeys((certified, current)):
        obj = api(f"/repos/{repo}/git/commits/{preview}")
        require(isinstance(obj, dict) and obj.get("sha") == preview,
                "authenticated merge preview commit missing or mismatched")
        parents = obj.get("parents")
        require(isinstance(parents, list) and len(parents) == 2
                and all(isinstance(parent, dict) for parent in parents)
                and [parent.get("sha") for parent in parents] == [base, head],
                "merge preview has incorrect authenticated ordered parents")
        tree = obj.get("tree")
        require(isinstance(tree, dict) and sha(tree.get("sha")),
                "merge preview has missing authenticated Git tree")
        trees.add(tree["sha"])
    require(len(trees) == 1, "merge previews have different authenticated Git trees")


def receipt_identity(receipt, audit):
    expected = {"repository": audit["repository"], "issue": audit["issue"],
                "pull_request": audit["pull_request"], "base_sha": audit["base_sha"],
                "head_sha": audit["head_sha"], "merge_preview_sha": audit["merge_preview_sha"],
                "issue_sha256": audit["issue_snapshot_sha256"]}
    identity = receipt.get("identity")
    require(isinstance(identity, dict) and all(identity.get(k) == v for k, v in expected.items())
            and positive(expected["pull_request"]) and sha(expected["merge_preview_sha"])
            and identity.get("base_ref") == audit["base_ref"] and audit["base_ref"] in {"main", "develop"}, "review receipt target identity mismatch")
    require(receipt.get("schema_version") == 1 and receipt.get("assurance") == ASSURANCE
            and receipt.get("session_separation") == "operator-declared"
            and receipt.get("third_party_identity_proven") is False
            and positive(receipt.get("review_comment_id")) and sha(receipt.get("review_body_sha256"), DIGEST),
            "invalid official session review receipt")
    return identity


def validate_policy(policy):
    keys = {"schema_version", "mode", "assurance", "acknowledgement", "operators"}
    require(set(policy) in (keys, keys | {"implementation_provenance"})
            and type(policy.get("schema_version")) is int and policy["schema_version"] == 1
            and policy["mode"] == "enabled" and policy["assurance"] == ASSURANCE
            and policy["acknowledgement"] == ACKNOWLEDGEMENT, "trusted review policy is not enabled")
    users = policy["operators"]
    require(isinstance(users, list) and bool(users) and all(
        isinstance(u, dict) and set(u) == {"id", "login"} and positive(u["id"])
        and isinstance(u["login"], str) and re.fullmatch(r"[A-Za-z0-9-]+", u["login"]) for u in users
    ) and len({u["id"] for u in users}) == len(users), "invalid trusted operator allowlist")
    return users


def allowed(comment, operators):
    user = comment.get("user") or {}
    return user.get("type") == "User" and positive(user.get("id")) and any(
        user["id"] == item["id"] and str(user.get("login", "")).casefold() == item["login"].casefold()
        for item in operators)


def review_digest(review):
    lines = []
    selected_has_analysis = False
    for row in review.get("requirements", []):
        analysis = row.get("analysis", "")
        require(isinstance(analysis, str), "review analysis shape mismatch")
        markers = [line for line in analysis.splitlines()
                   if line.lstrip().casefold().startswith("audit_report_sha256")]
        if markers:
            selected_has_analysis = len("\n".join(
                line for line in analysis.splitlines() if line not in markers).strip()) >= 40
        lines.extend(markers)
    require(len(lines) == 1 and MARKER.fullmatch(lines[0]),
            "exactly one canonical report digest line is required in review analysis")
    require(selected_has_analysis, "report digest cannot replace requirement analysis")
    return MARKER.fullmatch(lines[0]).group(1)


def verify_review_binding(api, pages, detail, repo, audit, report_sha):
    receipt = strict_json((detail.get("output") or {}).get("text"))
    identity = receipt_identity(receipt, audit)
    raw_policy = github_blob(api, repo, POLICY, audit["base_sha"])
    require(identity.get("policy_sha256") == sha256(raw_policy), "review receipt policy mismatch")
    policy_users = validate_policy(strict_json(raw_policy.decode("utf-8")))
    payload = {k: v for k, v in receipt.items() if k != "fingerprint"}
    fingerprint = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    require(receipt.get("fingerprint") == fingerprint and detail.get("external_id") == fingerprint,
            "review receipt fingerprint mismatch")
    comments = [c for c in pages(api(f"/repos/{repo}/issues/{audit['pull_request']}/comments?per_page=100",
                                    paginate=True))
                if allowed(c, policy_users) and str(c.get("body") or "").startswith(PREFIX)]
    require(comments and all(positive(c.get("id")) for c in comments), "no authorized live review")
    selected = max(comments, key=lambda c: c["id"])
    require(selected["id"] == receipt["review_comment_id"], "review was superseded or deleted")
    live = api(f"/repos/{repo}/issues/comments/{selected['id']}")
    fields = ("id", "body", "user", "created_at", "updated_at", "issue_url")
    pr_issue_url = f"{API_ROOT}/repos/{repo}/issues/{audit['pull_request']}"
    require(live.get("issue_url") == pr_issue_url and all(live.get(k) == selected.get(k) for k in fields)
            and allowed(live, policy_users), "live review readback changed")
    created, updated = live.get("created_at"), live.get("updated_at")
    require(isinstance(created, str) and created == updated
            and datetime.fromisoformat(created).tzinfo is not None, "review is edited or undated")
    body = live["body"]
    require(sha256(body.encode()) == receipt["review_body_sha256"], "review body digest mismatch")
    review = strict_json(body[len(PREFIX):])
    require(review.get("identity") == identity and review.get("conclusion") == "approved"
            and review.get("assurance") == ASSURANCE and review.get("acknowledgement") == ACKNOWLEDGEMENT,
            "live review identity or scope mismatch")
    require(review_digest(review) == report_sha, "review does not attest the exact audit report")
    return {"comment_id": selected["id"], "operators": policy_users,
            "url": f"https://github.com/{repo}/pull/{audit['pull_request']}#issuecomment-{selected['id']}"}
