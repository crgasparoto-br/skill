from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def expected_issue_and_pull_request(
    *,
    work_item_kind: str,
    work_item_number: int,
    issue_number: int | None,
    pull_request_number: int | None,
) -> tuple[int | None, int | None]:
    expected_issue = issue_number if issue_number is not None else (work_item_number if work_item_kind == "issue" else None)
    expected_pr = pull_request_number if pull_request_number is not None else (work_item_number if work_item_kind == "pr" else None)
    return expected_issue, expected_pr


def subject_matches_target(
    cert: dict[str, Any],
    *,
    repository: str,
    work_item_kind: str,
    work_item_number: int,
    issue_number: int | None,
    pull_request_number: int | None,
    base_ref: str | None,
    head_ref: str | None,
) -> bool:
    subject = cert.get("subject")
    if not isinstance(subject, dict):
        return False

    expected_issue, expected_pr = expected_issue_and_pull_request(
        work_item_kind=work_item_kind,
        work_item_number=work_item_number,
        issue_number=issue_number,
        pull_request_number=pull_request_number,
    )

    checks = [
        subject.get("repository") == repository,
        subject.get("work_item_kind") == work_item_kind,
        subject.get("work_item_number") == work_item_number,
        subject.get("pull_request") == expected_pr,
    ]
    if "issue_number" in subject and expected_issue is not None:
        checks.append(subject.get("issue_number") == expected_issue)
    if "pull_request_number" in subject and expected_pr is not None:
        checks.append(subject.get("pull_request_number") == expected_pr)
    if base_ref is not None:
        checks.append(subject.get("base_ref") == base_ref)
    if head_ref is not None:
        checks.append(subject.get("head_ref") == head_ref)
    return all(checks)


def files_are_identical(left: Path, right: Path) -> bool:
    if not left.is_file() or not right.is_file():
        return False
    left_bytes = left.read_bytes()
    right_bytes = right.read_bytes()
    if len(left_bytes) != len(right_bytes):
        return False
    return hashlib.sha256(left_bytes).digest() == hashlib.sha256(right_bytes).digest()


def inherited_foreign_certificate_by_bytes(
    cert: dict[str, Any],
    *,
    candidate_certificate: Path,
    base_certificate: Path | None,
    repository: str,
    work_item_kind: str,
    work_item_number: int,
    issue_number: int | None,
    pull_request_number: int | None,
    base_ref: str | None,
    head_ref: str | None,
) -> bool:
    if base_certificate is None or not files_are_identical(candidate_certificate, base_certificate):
        return False
    return not subject_matches_target(
        cert,
        repository=repository,
        work_item_kind=work_item_kind,
        work_item_number=work_item_number,
        issue_number=issue_number,
        pull_request_number=pull_request_number,
        base_ref=base_ref,
        head_ref=head_ref,
    )


def connector_origin_is_same_base_blob(manifest: dict[str, Any]) -> bool:
    origin = manifest.get("handoff_origin")
    if not isinstance(origin, dict):
        return False
    candidate_blob = str(origin.get("candidate_git_blob_sha") or "").strip().lower()
    base_blob = str(origin.get("base_git_blob_sha") or "").strip().lower()
    return (
        origin.get("same_blob_as_base") is True
        and len(candidate_blob) == 40
        and len(base_blob) == 40
        and candidate_blob == base_blob
    )
