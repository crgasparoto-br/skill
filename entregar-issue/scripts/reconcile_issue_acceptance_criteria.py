#!/usr/bin/env python3
"""Validate and optionally publish an append-only issue audit reconciliation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import acceptance_publication_provenance as provenance
import jsonschema
from acceptance_markdown import analyze_body
from validate_controller_audit_result import validate_report_data

CHECKBOX_RE = re.compile(r"^\s*\[\s*([xX ])\s*\]\s*(.*?)\s*$")
COMMENT_LOCATOR_RE = re.compile(r"^issue-comment:(\d+)$")
FINGERPRINT_RE = re.compile(
    r"<!-- audit-acceptance-criteria-fingerprint:([a-f0-9]{64}) -->"
)
PAYLOAD_PREFIX = "AUDIT_ACCEPTANCE_CRITERIA_JSON="


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def normalize(text: str) -> str:
    value = text.strip()
    checkbox = CHECKBOX_RE.match(value)
    if checkbox:
        value = checkbox.group(2)
    return re.sub(r"\s+", " ", value).strip()


def source_item(source: str, line: int) -> tuple[str, str]:
    item = analyze_body(source).get(line)
    if item is None:
        raise ValueError(f"source line {line} is not a normative list item")
    return item[0], normalize(item[1])


def acceptance_lines(source: str) -> list[int]:
    return list(analyze_body(source))


def load_report(path: Path) -> dict[str, Any]:
    report = provenance.strict_json(path.read_text(encoding="utf-8"), limit=2 * 1024 * 1024)
    schema_root = Path(__file__).resolve().parents[1] / "schemas"
    canonical_path = schema_root / "controller-audit-result.schema.json"
    reconciliation_path = (
        Path(__file__).resolve().parents[1]
        / "schemas"
        / "issue-acceptance-reconciliation.schema.json"
    )
    for schema_path in (canonical_path, reconciliation_path):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(
            schema, format_checker=jsonschema.FormatChecker()
        ).validate(report)
    return report


def run_gh(endpoint: str, *, method: str = "GET", payload: object | None = None,
          paginate: bool = False) -> Any:
    command = ["gh", "api", "--hostname", "github.com", endpoint, "--method", method]
    if paginate:
        command.extend(["--paginate", "--slurp"])
    if payload is not None:
        command.extend(["--input", "-"])
    completed = subprocess.run(
        command,
        input=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValueError(
            f"authenticated GitHub {method} {endpoint} failed: "
            f"{completed.stderr.strip()}"
        )
    return json.loads(completed.stdout) if completed.stdout.strip() else None


def flatten_pages(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError("paginated GitHub response is not a list")
    if all(isinstance(item, dict) for item in value):
        return [item for item in value if isinstance(item, dict)]
    pages = value
    if all(isinstance(page, list) for page in pages):
        return [
            item
            for page in pages
            for item in page
            if isinstance(item, dict)
        ]
    raise ValueError("paginated GitHub response has an unexpected shape")


def criterion_source(
    criterion: dict[str, Any],
    *,
    body: str,
    comments: dict[str, str],
) -> str:
    locator = str(criterion["source_locator"])
    if criterion["origin"] == "issue-body":
        if locator != "issue-body":
            raise ValueError(f"{criterion['id']} has an invalid issue-body locator")
        return body
    match = COMMENT_LOCATOR_RE.fullmatch(locator)
    if not match or match.group(1) not in comments:
        raise ValueError(
            f"{criterion['id']} references an unavailable issue comment"
        )
    return comments[match.group(1)]


def validate_acceptance_criterion(
    criterion: dict[str, Any],
    requirement: dict[str, Any],
    source: str,
) -> tuple[str, int, str]:
    identifier = str(criterion["id"])
    if digest(source.encode("utf-8")) != criterion["source_sha256"]:
        raise ValueError(f"{identifier} source changed since the audit")
    line = int(criterion["source_line"])
    state, text = source_item(source, line)
    if state != criterion["initial_checkbox_state"] or text != normalize(
        str(criterion["text"])
    ):
        raise ValueError(f"{identifier} no longer matches its exact source item")
    decision = criterion["decision"]
    proposed = criterion["proposed_checkbox_state"]
    if decision == "verified":
        if not criterion["evidence"]:
            raise ValueError(f"{identifier} verified decision lacks evidence")
        if requirement["status"] != "Implementado":
            raise ValueError(
                f"{identifier} verified decision has no implemented requirement"
            )
        if proposed != "checked":
            raise ValueError(
                f"{identifier} verified decision must propose checked"
            )
    else:
        expected = (
            "unchanged"
            if criterion["initial_checkbox_state"] == "not-present"
            else "unchecked"
        )
        if proposed != expected:
            raise ValueError(f"{identifier} unverified decision must remain open")
    return str(criterion["source_locator"]), line, text


def validate_report_against_sources(
    report: dict[str, Any],
    *,
    repository: str,
    issue_number: int,
    head_sha: str,
    issue: dict[str, Any],
    comments: list[dict[str, Any]],
) -> None:
    identity = report["identity"]
    if (
        identity["repository"] != repository
        or identity["issue"] != issue_number
        or identity["head_sha"] != head_sha
    ):
        raise ValueError("audit report target differs from the requested reconciliation")
    if str(issue.get("state") or "").lower() != "open":
        raise ValueError("acceptance criteria reconciliation requires an open issue")
    body = issue.get("body")
    if not isinstance(body, str):
        raise ValueError("authenticated issue body is unavailable")
    if digest(body.encode("utf-8")) != identity["issue_snapshot_sha256"]:
        raise ValueError("issue body changed since the audit snapshot")

    comment_by_id = {
        str(item.get("id")): str(item.get("body") or "")
        for item in comments
        if item.get("id") is not None
    }
    requirements = {str(item["id"]): item for item in report["requirements"]}
    criterion_ids: set[str] = set()
    source_locations: set[tuple[str, int, str]] = set()
    body_lines: set[int] = set()
    for criterion in report["acceptance_criteria"]:
        identifier = str(criterion["id"])
        if identifier in criterion_ids:
            raise ValueError(f"duplicate acceptance criterion id: {identifier}")
        criterion_ids.add(identifier)
        requirement = requirements.get(str(criterion["requirement_id"]))
        if requirement is None:
            raise ValueError(f"{identifier} references an unknown requirement")
        source = criterion_source(
            criterion, body=body, comments=comment_by_id
        )
        location = validate_acceptance_criterion(
            criterion, requirement, source
        )
        if location in source_locations:
            raise ValueError(f"{identifier} duplicates another criterion source")
        source_locations.add(location)
        if location[0] == "issue-body":
            body_lines.add(location[1])
    expected_body_lines = set(acceptance_lines(body))
    if body_lines != expected_body_lines:
        missing = sorted(expected_body_lines - body_lines)
        extra = sorted(body_lines - expected_body_lines)
        raise ValueError(
            "acceptance criteria inventory differs from the issue body "
            f"(missing={missing}, extra={extra})"
        )


def reconcile_payload(
    report: dict[str, Any], audit_report_sha256: str, audit_report_url: str
) -> dict[str, Any]:
    identity = report["identity"]
    criteria = []
    for criterion in report["acceptance_criteria"]:
        criteria.append({
            "id": criterion["id"],
            "requirement_id": criterion["requirement_id"],
            "origin": criterion["origin"],
            "source_id": criterion["source_id"],
            "source_locator": criterion["source_locator"],
            "source_sha256": criterion["source_sha256"],
            "source_line": criterion["source_line"],
            "text": criterion["text"],
            "initial_checkbox_state": criterion["initial_checkbox_state"],
            "decision": criterion["decision"],
            "evidence": criterion["evidence"],
            "rationale": criterion["rationale"],
            "proposed_checkbox_state": criterion["proposed_checkbox_state"],
        })
    result = {
        "schema": "issue-acceptance-criteria-reconciliation-v1",
        "repository": identity["repository"],
        "issue": identity["issue"],
        "head_sha": identity["head_sha"],
        "contract_sha256": identity["issue_snapshot_sha256"],
        "audit_verdict": report["verdict"],
        "audit_report_url": audit_report_url,
        "audit_report_sha256": audit_report_sha256,
        "criteria": criteria,
        "body_write": "not-attempted-no-proven-cas",
    }
    result["fingerprint"] = digest(canonical(result))
    return result


def render_comment(payload: dict[str, Any]) -> str:
    rows = []
    for criterion in payload["criteria"]:
        evidence = "<br>".join(
            str(item).replace("|", r"\|").replace("\n", " ")
            for item in criterion["evidence"]
        ) or "none"
        rows.append(
            "| `{}` | `{}` | {} | `{}` | {} | `{}` | `{}` |".format(
                criterion["id"],
                criterion["source_locator"],
                str(criterion["text"]).replace("|", r"\|").replace("\n", " "),
                criterion["initial_checkbox_state"],
                evidence,
                criterion["decision"],
                criterion["proposed_checkbox_state"],
            )
        )
    table = [
        "| ID | Origem | Critério | Checkbox inicial | Evidência exata | Decisão | Ação proposta |",
        "|---|---|---|---|---|---|---|",
        *rows,
    ]
    body = "\n".join(table)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        "<!-- audit-acceptance-criteria-reconciliation:v1 -->\n"
        f"<!-- audit-acceptance-criteria-fingerprint:{payload['fingerprint']} -->\n"
        "## Reconciliação de critérios de aceite\n\n"
        f"- Parecer: [{payload['audit_verdict']}]({payload['audit_report_url']})\n"
        f"- SHA auditado: `{payload['head_sha']}`\n"
        f"- Digest do corpo da issue: `{payload['contract_sha256']}`\n"
        f"- SHA-256 do parecer: `{payload['audit_report_sha256']}`\n"
        "- Corpo da issue: preservado; checkbox somente documentado porque este\n"
        "  runtime não dispõe de CAS atômico comprovado para editar o corpo.\n\n"
        f"{body}\n\n"
        "Estas decisões não concedem aprovação, merge, fechamento ou release.\n\n"
        f"{PAYLOAD_PREFIX}{encoded}\n"
    )


def read_authenticated_source(repository: str, issue_number: int) -> tuple[
    dict[str, Any], list[dict[str, Any]], dict[str, Any]
]:
    actor = run_gh("/user")
    issue = run_gh(f"/repos/{repository}/issues/{issue_number}")
    comments = flatten_pages(
        run_gh(
            f"/repos/{repository}/issues/{issue_number}/comments?per_page=100",
            paginate=True,
        )
    )
    if not isinstance(actor, dict) or not actor.get("login"):
        raise ValueError("authenticated GitHub identity is unavailable")
    if not isinstance(issue, dict):
        raise ValueError("authenticated issue response is malformed")
    return actor, comments, issue


def verify_live_head(report: dict[str, Any], head_sha: str, repository: str) -> str:
    identity = report["identity"]
    number = identity["pull_request"]
    if type(number) is not int or number <= 0 or not isinstance(identity["merge_preview_sha"], str):
        raise ValueError("protected PR and exact merge preview are required")
    pr = run_gh(f"/repos/{repository}/pulls/{number}")
    if not isinstance(pr, dict):
        raise ValueError("authenticated pull request is unavailable")
    head, base = pr.get("head") or {}, pr.get("base") or {}
    canonical_ref = {int(x) for x in re.findall(
        r"(?im)^\s*(?:closes|fixes|refs)\s+#([1-9][0-9]*)\s*$", pr.get("body") or "")}
    if (pr.get("number") != number or pr.get("state") != "open" or pr.get("draft") is not False
            or head.get("sha") != head_sha or base.get("sha") != identity["base_sha"]
            or pr.get("merge_commit_sha") != identity["merge_preview_sha"]
            or (head.get("repo") or {}).get("full_name") != repository
            or (base.get("repo") or {}).get("full_name") != repository
            or base.get("ref") not in {"develop", "main"} or canonical_ref != {identity["issue"]}):
        raise ValueError("pull request HEAD changed or is not the exact protected audit target")
    branch = run_gh(f"/repos/{repository}/branches/{base['ref']}")
    if branch.get("protected") is not True or (branch.get("commit") or {}).get("sha") != base["sha"]:
        raise ValueError("protected target branch changed or could not be authenticated")
    return base["ref"]


def verify_required_audit_checks(
    repository: str,
    head_sha: str,
    audit_report_sha256: str,
    audit_identity: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    response = run_gh(
        f"/repos/{repository}/commits/{head_sha}/check-runs?per_page=100&filter=all"
    )
    if not isinstance(response, dict):
        raise ValueError("authenticated check-run inventory is malformed")
    runs = response.get("check_runs")
    if not isinstance(runs, list):
        raise ValueError("authenticated check-run inventory is missing")
    if response.get("total_count", len(runs)) > len(runs):
        raise ValueError("check-run inventory is incomplete")
    name = provenance.CHECK
    matches = [item for item in runs if isinstance(item, dict)
               and item.get("name") == name and item.get("head_sha") == head_sha]
    if not matches or any(not provenance.positive(item.get("id")) for item in matches):
        raise ValueError(f"required audit check is missing or malformed: {name}")
    latest = max(matches, key=lambda item: item["id"])
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ValueError(f"required audit check is not green: {name}")
    detail = run_gh(f"/repos/{repository}/check-runs/{latest['id']}")
    if (not isinstance(detail, dict) or detail.get("id") != latest["id"]
            or detail.get("status") != "completed" or detail.get("conclusion") != "success"):
        raise ValueError(f"audit check details changed: {name}")
    provenance.verify_origin(run_gh, detail, repository, head_sha, audit_identity["base_sha"])
    binding = provenance.verify_review_binding(run_gh, flatten_pages, detail, repository,
                                                audit_identity, audit_report_sha256)
    return latest["id"], binding


def validate_semantic_audit(report: dict[str, Any], path: Path) -> None:
    try:
        validate_report_data(report, path)
    except (ValueError, OSError) as exc:
        raise ValueError("canonical semantic report validation failed: " + str(exc)) from exc


def authenticate_attempt(report, args, report_sha):
    base_ref = verify_live_head(report, args.head_sha, args.repository)
    return verify_required_audit_checks(args.repository, args.head_sha, report_sha,
                                        {**report["identity"], "base_ref": base_ref})


def verify_publisher_comment(comment, expected_body, repository, issue, operators, actor=None):
    if (not isinstance(comment, dict) or comment.get("body") != expected_body
            or comment.get("issue_url") != f"{provenance.API_ROOT}/repos/{repository}/issues/{issue}"
            or not isinstance(comment.get("created_at"), str)
            or comment["created_at"] != comment.get("updated_at")
            or not provenance.allowed(comment, operators)
            or (actor is not None and (comment.get("user") or {}).get("id") != actor["id"])):
        raise ValueError("published issue comment is not the immutable authorized readback")


def logical_matches(
    comments: list[dict[str, Any]], marker: str
) -> list[dict[str, Any]]:
    return [
        item
        for item in comments
        if marker in FINGERPRINT_RE.findall(str(item.get("body") or ""))
    ]


def exact_existing_comment(
    comments: list[dict[str, Any]], marker: str, expected_body: str,
    repository: str,
) -> dict[str, Any] | None:
    matches = logical_matches(comments, marker)
    if len(matches) > 1:
        raise ValueError("logical duplicate reconciliation comments exist")
    if not matches:
        return None
    persisted = run_gh(
        f"/repos/{repository}/issues/comments/{matches[0]['id']}"
    )
    if not isinstance(persisted, dict) or persisted.get("body") != expected_body:
        raise ValueError("existing reconciliation marker does not match the exact audit")
    return persisted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-report", required=True, type=Path)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--audit-report-url", help="Optional exact authenticated review comment URL")
    parser.add_argument(
        "--required-audit-check",
        action="append",
        help="Only the built-in canonical session-review check is accepted.",
    )
    parser.add_argument(
        "--required-audit-workflow",
        action="append",
        help="Only the built-in canonical session-review workflow is accepted.",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--update-checkboxes",
        action="store_true",
        help="Rejected unless a future implementation proves atomic conditional writes.",
    )
    args = parser.parse_args()

    try:
        if args.update_checkboxes:
            raise ValueError(
                "issue body updates are prohibited without proven atomic CAS"
            )
        if args.issue <= 0 or not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", args.repository):
            raise ValueError("valid GitHub repository and issue are required")
        if not re.fullmatch(r"[a-f0-9]{40}", args.head_sha):
            raise ValueError("head SHA must be a lowercase 40-character SHA")
        if args.required_audit_check not in (None, [provenance.CHECK]) or (
                args.required_audit_workflow not in (None, [provenance.WORKFLOW])):
            raise ValueError("only the canonical session-review authority is supported")
        report = load_report(args.audit_report)
        if report["verdict"] != "Aprovado":
            raise ValueError("negative or partial audit is local-only; no approved publication receipt")
        audit_report_sha256 = digest(canonical(report))
        actor, comments, issue = read_authenticated_source(args.repository, args.issue)
        check_id, binding = authenticate_attempt(report, args, audit_report_sha256)
        if args.audit_report_url is not None and args.audit_report_url != binding["url"]:
            raise ValueError("report URL must be the authenticated review comment")
        if not provenance.allowed({"user": actor}, binding["operators"]):
            raise ValueError("authenticated publisher is not an allowed operator")
        validate_semantic_audit(report, args.audit_report)
        validate_report_against_sources(
            report,
            repository=args.repository,
            issue_number=args.issue,
            head_sha=args.head_sha,
            issue=issue,
            comments=comments,
        )
        payload = reconcile_payload(
            report, audit_report_sha256, binding["url"]
        )
        comment = render_comment(payload)
        marker = payload["fingerprint"]
        persisted = exact_existing_comment(
            comments, marker, comment, args.repository
        )
        result: dict[str, Any] = {
            "schema": "issue-acceptance-criteria-reconciliation-receipt-v1",
            "status": "planned",
            "actor": actor["login"],
            "fingerprint": marker,
            "audit_report_sha256": payload["audit_report_sha256"],
            "body_write": "not-attempted-no-proven-cas",
            "audit_check_run_ids": [check_id],
            "audit_review_comment_id": binding["comment_id"],
        }
        if persisted is not None:
            verify_publisher_comment(persisted, comment, args.repository, args.issue,
                                     binding["operators"])
            result.update({
                "status": "already-published",
                "comment_id": persisted.get("id"),
                "comment_url": persisted.get("html_url"),
                "readback_sha256": digest(
                    str(persisted.get("body") or "").encode("utf-8")
                ),
            })
        elif args.apply:
            actor2, latest_comments, latest_issue = read_authenticated_source(
                args.repository, args.issue
            )
            if authenticate_attempt(report, args, audit_report_sha256) != (check_id, binding):
                raise ValueError("review authority changed before publication")
            validate_report_against_sources(
                report,
                repository=args.repository,
                issue_number=args.issue,
                head_sha=args.head_sha,
                issue=latest_issue,
                comments=latest_comments,
            )
            if actor2["login"] != actor["login"] or actor2.get("id") != actor["id"]:
                raise ValueError("authenticated publisher identity changed")
            persisted = exact_existing_comment(
                latest_comments, marker, comment, args.repository
            )
            if persisted is None:
                created_now = True
                created = run_gh(
                    f"/repos/{args.repository}/issues/{args.issue}/comments",
                    method="POST",
                    payload={"body": comment},
                )
                if not isinstance(created, dict) or not isinstance(
                    created.get("id"), int
                ):
                    raise ValueError(
                        "GitHub did not return the created comment identity"
                    )
                persisted = run_gh(
                    f"/repos/{args.repository}/issues/comments/{created['id']}"
                )
            else:
                created_now = False
                created = persisted
            verify_publisher_comment(persisted, comment, args.repository, args.issue,
                                     binding["operators"], actor if created_now else None)
            if authenticate_attempt(report, args, audit_report_sha256) != (check_id, binding):
                raise ValueError("review authority changed during publication")
            final_issue = run_gh(
                f"/repos/{args.repository}/issues/{args.issue}"
            )
            if (
                not isinstance(final_issue, dict)
                or digest(str(final_issue.get("body") or "").encode("utf-8"))
                != report["identity"]["issue_snapshot_sha256"]
            ):
                raise ValueError("issue body changed during reconciliation")
            final_comments = flatten_pages(
                run_gh(
                    f"/repos/{args.repository}/issues/{args.issue}/comments?per_page=100",
                    paginate=True,
                )
            )
            validate_report_against_sources(
                report,
                repository=args.repository,
                issue_number=args.issue,
                head_sha=args.head_sha,
                issue=final_issue,
                comments=final_comments,
            )
            final_matches = logical_matches(final_comments, marker)
            if (
                len(final_matches) != 1
                or final_matches[0].get("id") != created["id"]
            ):
                raise ValueError(
                    "authenticated final readback found missing or duplicate publication"
                )
            verify_publisher_comment(final_matches[0], comment, args.repository, args.issue,
                                     binding["operators"], actor if created_now else None)
            result.update({
                "status": "published" if created_now else "already-published",
                "comment_id": created["id"],
                "comment_url": persisted.get("html_url"),
                "readback_sha256": digest(comment.encode("utf-8")),
            })
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
