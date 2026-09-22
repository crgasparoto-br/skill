#!/usr/bin/env python3
"""Shared semantic target-binding checks for governed delivery handoffs."""
from __future__ import annotations

from typing import Any


def _compare(label: str, observed: Any, expected: Any, reasons: list[str]) -> None:
    if expected is None:
        return
    if observed != expected:
        reasons.append(f"{label} differs: observed={observed!r} expected={expected!r}")


def classify_handoff_subject(
    certificate: dict[str, Any],
    *,
    repository: str,
    work_item_kind: str | None = None,
    work_item_number: int | None = None,
    pull_request: int | None = None,
    base_ref: str | None = None,
    head_ref: str | None = None,
) -> dict[str, Any]:
    """Classify whether a delivery certificate is semantically bound to the current target."""
    expected = {
        "repository": repository,
        "work_item_kind": work_item_kind,
        "work_item_number": work_item_number,
        "pull_request": pull_request,
        "base_ref": base_ref,
        "head_ref": head_ref,
    }
    reasons: list[str] = []

    subject = certificate.get("subject")
    if not isinstance(subject, dict):
        return {
            "status": "unbound-or-invalid",
            "applicable": False,
            "expected_subject": expected,
            "observed_subject": None,
            "reasons": ["handoff certificate lacks semantic subject binding"],
        }

    _compare("subject.repository", subject.get("repository"), repository, reasons)
    _compare("subject.work_item_kind", subject.get("work_item_kind"), work_item_kind, reasons)
    _compare("subject.work_item_number", subject.get("work_item_number"), work_item_number, reasons)
    _compare("subject.pull_request", subject.get("pull_request"), pull_request, reasons)
    _compare("subject.base_ref", subject.get("base_ref"), base_ref, reasons)
    _compare("subject.head_ref", subject.get("head_ref"), head_ref, reasons)

    if reasons:
        return {
            "status": "foreign-target",
            "applicable": False,
            "expected_subject": expected,
            "observed_subject": subject,
            "reasons": reasons,
        }

    return {
        "status": "current-target",
        "applicable": True,
        "expected_subject": expected,
        "observed_subject": subject,
        "reasons": ["handoff certificate subject matches the current CI target"],
    }
