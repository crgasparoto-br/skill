#!/usr/bin/env python3
"""Reconcile acceptance checkboxes offline; GitHub writes belong to an authorized controller."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*\r?\n?$")
CRITERIA_TITLE = re.compile(r"^(crit[eé]rios de aceite|acceptance criteria)$", re.IGNORECASE)
ITEM = re.compile(
    r"^(?P<prefix>[ \t]{0,3}(?:[-*+]|\d+[.)])[ \t]+)"
    r"(?P<checkbox>\[[ xX]\][ \t]+)?"
    r"(?P<text>\S.*?)(?P<ending>\r?\n?)$"
)
SHA = re.compile(r"^[0-9a-f]{40}$")


def analyze_body(body: str) -> tuple[list[str], list[dict], str]:
    """Return original lines, criteria, and text normalized only for checkbox markers."""
    lines = body.splitlines(keepends=True)
    normalized = list(lines)
    items: list[dict] = []
    in_criteria = False
    sections = 0
    fence_marker = ""
    fence_width = 0
    in_comment = False

    for index, line in enumerate(lines):
        stripped = line.lstrip(" ")
        indentation = len(line) - len(stripped)
        if indentation <= 3 and stripped.startswith((chr(96) * 3, "~~~")):
            symbol = stripped[0]
            width = len(stripped) - len(stripped.lstrip(symbol))
            suffix = stripped[width:].strip()
            if not fence_marker:
                # A backtick opening fence cannot have backticks in its info string.
                if symbol == "~" or chr(96) not in suffix:
                    fence_marker, fence_width = symbol, width
                    continue
            elif symbol == fence_marker and width >= fence_width and not suffix:
                fence_marker, fence_width = "", 0
                continue
        if fence_marker:
            continue

        # Comments inside fenced code must not change parser state.
        if stripped.startswith("<!--"):
            in_comment = True
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue

        heading = HEADING.match(line)
        if heading:
            depth = len(heading.group(1))
            if depth <= 2:
                heading_title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(2)).strip()
                in_criteria = depth == 2 and bool(CRITERIA_TITLE.fullmatch(heading_title))
                if in_criteria:
                    sections += 1
            continue
        if not in_criteria:
            continue
        match = ITEM.match(line)
        if match is None:
            continue
        items.append(
            {
                "ordinal": len(items) + 1,
                "line": index,
                "text": match.group("text"),
                "prefix": match.group("prefix"),
                "ending": match.group("ending"),
                "checked": bool(match.group("checkbox") and "x" in match.group("checkbox").lower()),
            }
        )
        normalized[index] = match.group("prefix") + match.group("text") + match.group("ending")

    if sections != 1:
        raise ValueError("Expected exactly one level-2 acceptance-criteria section")
    if not items:
        raise ValueError("Acceptance-criteria section has no list items")
    return lines, items, "".join(normalized)


def reconcile(audited_body: str, current_body: str, audit: dict, material_sha: str) -> tuple[str, dict]:
    """Propose new issue body; callers must authenticate audit origin and perform the remote write."""
    if not SHA.fullmatch(material_sha):
        raise ValueError("Material SHA must contain 40 lowercase hex characters")
    if audit.get("subject_sha") != material_sha or audit.get("validity") not in {"independent", "solo-context-attested"}:
        raise ValueError("Trusted review/attestation and exact material SHA are required")
    if not isinstance(audit.get("audit_url"), str) or not audit["audit_url"].startswith("https://"):
        raise ValueError("Locatable independent audit reference is required")

    _, original, audited_norm = analyze_body(audited_body)
    current_lines, live, current_norm = analyze_body(current_body)
    if audited_norm != current_norm:
        raise ValueError("Issue changed beyond checklist markers; rederive and reauditar before writing")
    if len(original) != len(live):
        raise ValueError("Acceptance-criteria count changed")

    decisions = audit.get("criteria")
    if not isinstance(decisions, list) or len(decisions) != len(original):
        raise ValueError("Every criterion must have an explicit audit decision")
    allowed = {"verified", "failed", "partial", "unknown", "not-applicable"}
    changes: list[dict] = []
    warnings: list[str] = []

    for expected, observed, decision in zip(original, live, decisions, strict=True):
        if (
            not isinstance(decision, dict)
            or decision.get("ordinal") != expected["ordinal"]
            or decision.get("text") != expected["text"]
            or decision.get("original_checked") is not expected["checked"]
            or observed["text"] != expected["text"]
        ):
            raise ValueError("Criterion identity/order does not match the audited issue")
        status = decision.get("status")
        evidence = decision.get("evidence")
        if status not in allowed:
            raise ValueError("Invalid or absent criterion decision")
        if status in {"verified", "failed", "partial"} and (
            not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(ref, str) or not ref.strip() for ref in evidence)
        ):
            raise ValueError("Decisive statuses require locatable evidence")

        if status == "verified":
            desired = True
        elif status in {"failed", "partial"}:
            desired = False
        else:
            desired = False
            if observed["checked"]:
                warnings.append(f"Criterion {expected['ordinal']} reopened: no verified evidence")
        if desired == observed["checked"]:
            continue
        current_lines[observed["line"]] = (
            observed["prefix"] + ("[x] " if desired else "[ ] ")
            + observed["text"] + observed["ending"]
        )
        changes.append(
            {"ordinal": expected["ordinal"], "text": expected["text"], "checked": desired, "evidence": evidence or []}
        )

    new_body = "".join(current_lines)
    if analyze_body(new_body)[2] != current_norm:
        raise ValueError("Reconciliation altered normative content")
    return new_body, {"changes": changes, "warnings": warnings, "criteria_total": len(original)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audited-body", type=Path, required=True)
    parser.add_argument("--current-body", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--material-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audited_body = args.audited_body.read_text(encoding="utf-8")
    current_body = args.current_body.read_text(encoding="utf-8")
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    result, summary = reconcile(audited_body, current_body, audit, args.material_sha)
    args.output.write_text(result, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
