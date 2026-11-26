"""Read-only provenance of the existing exact-SHA session review receipt."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import stat
from datetime import UTC, datetime
from urllib.parse import urlunsplit
from zipfile import ZipFile

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
ACTIONS_APP = 15368
MAX_ORIGIN_BYTES = 65536
ORIGIN_KEYS = {"schema_version", "run_id", "run_attempt"}
MARKER = re.compile(r"AUDIT_REPORT_SHA256=([a-f0-9]{64})\Z")
TRUSTED = (WORKFLOW, POLICY, ".github/workflows/reusable-handoff.yml",
           "entregar-issue/scripts/resolve_trusted_audit_transport.py",
           "entregar-issue/scripts/validate_native_actions_evidence.py",
           "scripts/dispatch_session_review.py", "scripts/session_review.py", "scripts/session_review_github.py",
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
MAIN_TRUSTED = (".github/workflows/main-native-evidence.yml", "scripts/run_main_evidence_tests.py",
                "entregar-issue/scripts/classify_audit_transport.py",
                "entregar-issue/scripts/prepare_actions_handoff.py")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def strict_json(raw, *, limit=65536):
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(_value):
        raise ValueError("nonfinite JSON value")

    require(isinstance(raw, str) and len(raw.encode()) <= limit, "invalid bounded JSON")
    result = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
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


def trusted_paths_at(api, repo, ref, paths):
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
        if path in paths:
            require(path not in tracked and row.get("type") == "blob"
                    and row.get("mode") in {"100644", "100755"} and sha(row.get("sha")),
                    "untrusted executable source entry")
            tracked[path] = row["sha"]
    require(set(tracked) == set(paths), "trusted executable closure incomplete")
    return tracked


def require_suite(api, repo, suite_id, head):
    require(positive(suite_id), "missing GitHub check suite")
    suite = api(f"/repos/{repo}/check-suites/{suite_id}")
    require(positive(suite.get("id")) and suite["id"] == suite_id and suite.get("head_sha") == head
            and actions_app(suite), "wrong GitHub Actions check suite provenance")


def actions_app(row):
    app_id = (row.get("app") or {}).get("id")
    return type(app_id) is int and app_id == ACTIONS_APP


def review_workflow(api, root, repo, origin, base, base_ref):
    run_id, attempt = origin["run_id"], origin["run_attempt"]
    run = api(f"{root}/actions/runs/{run_id}")
    event = api(f"{root}/actions/runs/{run_id}/attempts/{attempt}")
    fields = ("id", "run_attempt", "workflow_id", "check_suite_id", "head_sha", "head_branch",
              "path", "status", "conclusion", "event")
    require(canonical({k: run.get(k) for k in fields}) == canonical({k: event.get(k) for k in fields}),
            "review workflow attempt differs from the current run")
    workflow = api(f"{root}/actions/workflows/session-review.yml")
    require(positive(run.get("id")) and run["id"] == run_id
            and positive(run.get("run_attempt")) and run["run_attempt"] == attempt
            and positive(workflow.get("id")) and positive(run.get("workflow_id"))
            and run["workflow_id"] == workflow["id"] and workflow.get("path") == WORKFLOW,
            "review workflow identity does not match the protected workflow")
    branch, source = run.get("head_branch"), run.get("head_sha")
    repo_id = (run.get("repository") or {}).get("id")
    require(branch in {"main", "develop"} and sha(source)
            and run.get("path") in {WORKFLOW, f"{WORKFLOW}@refs/heads/{branch}"}
            and positive(repo_id) and all(
                (row.get(key) or {}).get("full_name") == repo
                and positive((row.get(key) or {}).get("id")) and row[key]["id"] == repo_id
                for row in (run, event) for key in ("repository", "head_repository"))
            and run.get("status") == "completed" and run.get("conclusion") == "success"
            and run.get("event") in {"issue_comment", "workflow_run", "pull_request_target", "issues", "push"},
            "review workflow is not a trusted protected-source run")
    protected = api(f"{root}/branches/{branch}")
    tip = (protected.get("commit") or {}).get("sha")
    require(protected.get("protected") is True and sha(tip), "review workflow source branch is not protected")
    if tip != source:
        comparison = api(f"{root}/compare/{source}...{tip}?per_page=1")
        require(comparison.get("status") == "ahead" and
                (comparison.get("merge_base_commit") or {}).get("sha") == source,
                "review workflow source is not in the protected branch ancestry")
    require_suite(api, repo, run.get("check_suite_id"), source)
    paths = (*TRUSTED, *MAIN_TRUSTED) if base_ref == "main" else TRUSTED
    require(trusted_paths_at(api, repo, base, paths) == trusted_paths_at(api, repo, source, paths),
            "review executable workflow source differs from trusted base")
    return branch, source, repo_id


def origin_artifact(api, root, origin, source):
    run_id = origin["run_id"]
    branch, head, repo_id = source
    name = f"session-review-origin-v2-attempt-{origin['run_attempt']}"
    inventory = api(f"{root}/actions/runs/{run_id}/artifacts?name={name}&per_page=100")
    entries = inventory.get("artifacts")
    require(isinstance(entries, list) and positive(inventory.get("total_count"))
            and inventory["total_count"] == len(entries) == 1, "unique review origin artifact required")
    info = entries[0]
    expected = {"id": run_id, "repository_id": repo_id, "head_repository_id": repo_id,
                "head_branch": branch, "head_sha": head}
    require(info.get("name") == name and canonical(info.get("workflow_run")) == canonical(expected)
            and positive(info.get("id")) and info.get("expired") is False
            and positive(info.get("size_in_bytes")) and info["size_in_bytes"] <= MAX_ORIGIN_BYTES,
            "review origin artifact identity, expiry or size is invalid")
    expiry = datetime.fromisoformat(info.get("expires_at") or "")
    digest = info.get("digest")
    require(expiry.tzinfo is not None and expiry > datetime.now(UTC)
            and isinstance(digest, str) and digest.startswith("sha256:") and sha(digest[7:], DIGEST),
            "review origin artifact is expired or has no authenticated digest")
    raw = api(f"{root}/actions/artifacts/{info['id']}/zip", binary_limit=MAX_ORIGIN_BYTES)
    require(isinstance(raw, bytes) and len(raw) == info["size_in_bytes"] and sha256(raw) == digest[7:],
            "review origin artifact bytes do not match authenticated digest")
    return info["id"], digest, raw


def verify_origin(api, detail, repo, head, base, base_ref):
    require(base_ref in {"develop", "main"}, "protected review base is invalid")
    check_id = detail.get("id")
    require(positive(check_id) and detail.get("name") == CHECK and detail.get("head_sha") == head
            and actions_app(detail), "audit check was not produced by GitHub Actions on the exact head")
    receipt = strict_json((detail.get("output") or {}).get("text"))
    origin = receipt.get("publication_origin")
    require(isinstance(origin, dict) and set(origin) == ORIGIN_KEYS
            and type(origin["schema_version"]) is int and origin["schema_version"] == 2
            and all(positive(origin[k]) for k in ("run_id", "run_attempt")),
            "official V2 review publication origin is required")
    require(detail.get("details_url") in {
        f"https://{GITHUB_HOST}/{repo}/runs/{check_id}",
        f"https://{GITHUB_HOST}/{repo}/actions/runs/{origin['run_id']}",
    }, "invalid review workflow run URL")
    root = f"/repos/{repo}"
    suite = (detail.get("check_suite") or {}).get("id")
    require_suite(api, repo, suite, head)
    source = review_workflow(api, root, repo, origin, base, base_ref)
    artifact_id, digest, archive = origin_artifact(api, root, origin, source)
    expected = {**origin, "check_id": check_id, "check_suite_id": suite,
                "receipt_sha256": sha256(canonical(receipt))}
    require_origin_record(archive, check_id, expected)
    return {**expected, "artifact_id": artifact_id, "artifact_digest": digest}


def require_origin_record(archive, check_id, expected):
    with ZipFile(io.BytesIO(archive)) as zipped:
        files = zipped.infolist()
        require(len(files) == 1 and files[0].filename == f"{check_id}.json"
                and stat.S_IFMT(files[0].external_attr >> 16) in {0, stat.S_IFREG}
                and 0 < files[0].file_size <= 4096 and not files[0].flag_bits & 1,
                "invalid bounded review origin artifact member")
        with zipped.open(files[0]) as stream:
            require(stream.read(4097) == canonical(expected), "review origin does not bind the exact receipt")


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
    require(isinstance(identity, dict) and all(canonical(identity.get(k)) == canonical(v) for k, v in expected.items())
            and positive(expected["pull_request"]) and sha(expected["merge_preview_sha"])
            and identity.get("base_ref") == audit["base_ref"] and audit["base_ref"] in {"main", "develop"}, "review receipt target identity mismatch")
    require(type(receipt.get("schema_version")) is int and receipt["schema_version"] == 1
            and receipt.get("assurance") == ASSURANCE
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
    fingerprint = sha256(canonical(payload))
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
    require(canonical(review.get("identity")) == canonical(identity) and review.get("conclusion") == "approved"
            and review.get("assurance") == ASSURANCE and review.get("acknowledgement") == ACKNOWLEDGEMENT,
            "live review identity or scope mismatch")
    require(review_digest(review) == report_sha, "review does not attest the exact audit report")
    return {"comment_id": selected["id"], "operators": policy_users,
            "url": f"https://github.com/{repo}/pull/{audit['pull_request']}#issuecomment-{selected['id']}"}
