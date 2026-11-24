#!/usr/bin/env python3
"""Validate and optionally publish an append-only issue audit reconciliation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import jsonschema

ACCEPTANCE_HEADING_RE = re.compile(
    r"^#{1,6}\s+.*(?:crit[eé]rios?(?:\s+de)?\s+aceite|acceptance\s+criteria)\b",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^#{1,6}\s+")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+?)\s*$")
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
    return re.sub(r"\s+", " ", value).strip("| ")


def source_item(source: str, line: int) -> tuple[str, str]:
    lines = source.splitlines()
    if line < 1 or line > len(lines):
        raise ValueError(f"source line {line} is out of range")
    listed = LIST_ITEM_RE.match(lines[line - 1])
    if not listed:
        raise ValueError(f"source line {line} is not a normative list item")
    value = listed.group(1).strip()
    checkbox = CHECKBOX_RE.match(value)
    if checkbox:
        state = "checked" if checkbox.group(1).lower() == "x" else "unchecked"
        text = checkbox.group(2)
    else:
        state = "not-present"
        text = value
    return state, normalize(text)


def acceptance_lines(source: str) -> list[int]:
    active = False
    found: list[int] = []
    for line_no, raw in enumerate(source.splitlines(), start=1):
        if ACCEPTANCE_HEADING_RE.match(raw.strip()):
            active = True
            continue
        if HEADING_RE.match(raw.strip()):
            active = False
            continue
        if active and LIST_ITEM_RE.match(raw):
            found.append(line_no)
    return found


def load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
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
    command = ["gh", "api", endpoint, "--method", method]
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


def verify_live_head(report: dict[str, Any], head_sha: str,
                     repository: str) -> None:
    identity = report["identity"]
    if identity["pull_request"] is not None:
        pr = run_gh(f"/repos/{repository}/pulls/{identity['pull_request']}")
        if not isinstance(pr, dict) or (pr.get("head") or {}).get("sha") != head_sha:
            raise ValueError("pull request HEAD changed since the audit")
        if (pr.get("state") or "") != "open":
            raise ValueError("pull request is no longer open")
    else:
        branch = run_gh(
            f"/repos/{repository}/git/ref/heads/{identity['branch']}"
        )
        if not isinstance(branch, dict) or (branch.get("object") or {}).get(
            "sha"
        ) != head_sha:
            raise ValueError("branch HEAD changed since the audit")


def verify_required_audit_checks(
    repository: str,
    head_sha: str,
    issue_number: int,
    audit_report_sha256: str,
    required_names: list[str],
) -> list[dict[str, Any]]:
    response = run_gh(
        f"/repos/{repository}/commits/{head_sha}/check-runs?per_page=100"
    )
    if not isinstance(response, dict):
        raise ValueError("authenticated check-run inventory is malformed")
    runs = response.get("check_runs")
    if not isinstance(runs, list):
        raise ValueError("authenticated check-run inventory is missing")
    if response.get("total_count", len(runs)) > len(runs):
        raise ValueError("check-run inventory is incomplete")
    selected: list[dict[str, Any]] = []
    for name in required_names:
        matches = [
            item
            for item in runs
            if isinstance(item, dict)
            and item.get("name") == name
            and item.get("head_sha") == head_sha
        ]
        if not matches:
            raise ValueError(f"required audit check is missing: {name}")
        latest = max(matches, key=lambda item: int(item.get("id") or 0))
        if (
            latest.get("status") != "completed"
            or latest.get("conclusion") != "success"
        ):
            raise ValueError(f"required audit check is not green: {name}")
        detail = run_gh(f"/repos/{repository}/check-runs/{latest['id']}")
        if not isinstance(detail, dict):
            raise ValueError(f"audit check details are unavailable: {name}")
        text = str((detail.get("output") or {}).get("text") or "")
        try:
            receipt = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"required audit check has an invalid receipt: {name}"
            ) from exc
        if not isinstance(receipt, dict):
            raise ValueError(
                f"required audit check lacks one bound publication attestation: {name}"
            )
        attestation = receipt.get("publication_attestation")
        expected = {
            "schema": "issue-audit-publication-attestation-v1",
            "repository": repository,
            "issue": issue_number,
            "head_sha": head_sha,
            "audit_report_sha256": audit_report_sha256,
            "accepted": True,
        }
        if attestation != expected:
            raise ValueError(
                f"required audit check is not bound to the exact report: {name}"
            )
        selected.append(latest)
    return selected


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
    parser.add_argument("--audit-report-url", required=True)
    parser.add_argument(
        "--required-audit-check",
        action="append",
        required=True,
        help="Exact-head GitHub check required to authenticate the audit attestation.",
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
        if not re.fullmatch(r"[a-f0-9]{40}", args.head_sha):
            raise ValueError("head SHA must be a lowercase 40-character SHA")
        if not args.audit_report_url.startswith("https://"):
            raise ValueError("audit report URL must be an HTTPS URL")
        report = load_report(args.audit_report)
        audit_report_sha256 = digest(canonical(report))
        actor, comments, issue = read_authenticated_source(
            args.repository, args.issue
        )
        verify_live_head(report, args.head_sha, args.repository)
        selected_checks = verify_required_audit_checks(
            args.repository,
            args.head_sha,
            args.issue,
            audit_report_sha256,
            args.required_audit_check,
        )
        validate_report_against_sources(
            report,
            repository=args.repository,
            issue_number=args.issue,
            head_sha=args.head_sha,
            issue=issue,
            comments=comments,
        )
        payload = reconcile_payload(
            report, audit_report_sha256, args.audit_report_url
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
            "audit_check_run_ids": [item["id"] for item in selected_checks],
        }
        if persisted is not None:
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
            verify_live_head(report, args.head_sha, args.repository)
            verify_required_audit_checks(
                args.repository,
                args.head_sha,
                args.issue,
                audit_report_sha256,
                args.required_audit_check,
            )
            validate_report_against_sources(
                report,
                repository=args.repository,
                issue_number=args.issue,
                head_sha=args.head_sha,
                issue=latest_issue,
                comments=latest_comments,
            )
            if actor2["login"] != actor["login"]:
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
            if not isinstance(persisted, dict) or persisted.get("body") != comment:
                raise ValueError("authenticated readback did not match publication")
            verify_live_head(report, args.head_sha, args.repository)
            verify_required_audit_checks(
                args.repository,
                args.head_sha,
                args.issue,
                audit_report_sha256,
                args.required_audit_check,
            )
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
            final_matches = logical_matches(final_comments, marker)
            if (
                len(final_matches) != 1
                or final_matches[0].get("id") != created["id"]
            ):
                raise ValueError(
                    "authenticated final readback found missing or duplicate publication"
                )
            result.update({
                "status": "published" if created_now else "already-published",
                "comment_id": created["id"],
                "comment_url": persisted.get("html_url"),
                "readback_sha256": digest(comment.encode("utf-8")),
            })
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"BLOCK: {exc}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
