#!/usr/bin/env python3
"""Reconcile acceptance checkboxes offline; GitHub writes belong to an authorized controller."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*\r?\n?$")
CRITERIA_TITLE = re.compile(r"^(crit[eé]rios de aceite|acceptance criteria)$", re.IGNORECASE)
ITEM = re.compile(
    r"^(?P<prefix>[ \t]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]+)"
    r"(?P<checkbox>\[[ xX]\][ \t]+)?"
    r"(?P<text>\S.*?)(?P<ending>\r?\n?)$"
)
SHA = re.compile(r"^[0-9a-f]{40}$")
# In CommonMark thematic breaks take precedence over list items.
# They are inert separators, never acceptance criteria.
THEMATIC_BREAK = re.compile(
    r"^ {0,3}(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})\r?\n?$"
)


HTML_BLOCK_TAGS = (
    "address", "article", "aside", "base", "basefont", "blockquote", "body",
    "caption", "center", "col", "colgroup", "dd", "details", "dialog",
    "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure",
    "footer", "form", "frame", "frameset", "h1", "h2", "h3", "h4",
    "h5", "h6", "head", "header", "hr", "html", "iframe", "legend",
    "li", "link", "main", "menu", "menuitem", "meta", "nav",
    "noframes", "ol", "optgroup", "option", "output", "p", "param",
    "search", "section", "summary", "table", "tbody", "td", "tfoot",
    "th", "thead", "title", "tr", "track", "ul",
)
HTML_BLOCK_OPEN = re.compile(
    r"^ {0,3}</?(?:" + "|".join(HTML_BLOCK_TAGS) + r")(?=[ \t/>])",
    re.IGNORECASE,
)
# CommonMark type 7: a complete opening/closing HTML tag on its own line
# starts a raw block terminated by a blank line, including custom elements.
HTML_BLOCK_GENERIC = re.compile(
    r"^ {0,3}</?[A-Za-z][A-Za-z0-9-]*"
    r"(?:[ \t]+[A-Za-z_:][\w:.-]*(?:[ \t]*=[ \t]*(?:\"[^\"]*\"|'[^']*'|[^ \t=<>\x60'\"]+))?)*"
    r"[ \t]*/?>[ \t]*$"
)

def _open_raw_html_block(line: str, paragraph_open: bool) -> tuple[bool, str]:
    """Return whether this is an inert CommonMark HTML opener and how it ends."""
    raw_tag = re.match(r"<(pre|script|style|textarea)(?=[ \t>])", line, re.IGNORECASE)
    if raw_tag is not None:
        tag = raw_tag.group(1).lower()
        return True, tag if not re.search(rf"</{tag}[ \t]*>", line, re.IGNORECASE) else ""

    # Types 3-5 have a content terminator. Types 6-7 end at a blank line,
    # even if a closing HTML tag appears earlier.
    for prefix, terminator in (("<?", "?>"), ("<![CDATA[", "]]>")):
        if line.startswith(prefix):
            return True, f"terminator:{terminator}" if terminator not in line else ""
    if re.match(r"<![A-Z]", line):
        return True, "terminator:>" if ">" not in line else ""
    if HTML_BLOCK_OPEN.match(line):
        return True, "until-blank"
    # CommonMark type 7 cannot interrupt an already open paragraph.
    if not paragraph_open and HTML_BLOCK_GENERIC.match(line.rstrip("\r\n")):
        return True, "until-blank"
    return False, ""


def _advance_html_block(block: str, line: str) -> str:
    """Keep raw HTML inert until its CommonMark termination rule is met."""
    if block == "until-blank":
        return "" if not line.strip() else block
    if block.startswith("terminator:"):
        return "" if block[len("terminator:"):] in line else block
    return "" if re.search(rf"</{block}[ \t]*>", line, re.IGNORECASE) else block


def _criterion_match(line: str, in_criteria: bool, paragraph_open: bool) -> re.Match[str] | None:
    """Return only real criteria; a non-one ordered item cannot start a list mid-paragraph."""
    if not in_criteria:
        return None
    match = ITEM.match(line)
    if match is None or THEMATIC_BREAK.fullmatch(line.lstrip(" \t")):
        return None
    ordered = re.match(r"([0-9]+)[.)]", match.group("prefix").lstrip())
    if paragraph_open and ordered and int(ordered.group(1)) != 1:
        return None
    return match



def _relative_list_indent(line: str, content_indents: list[int]) -> int:
    """Compute code indentation relative to the innermost active list item.

    An indented child marker may be valid list content, not a code block.
    Pop containers when a line returns to an enclosing list or the document.
    """
    prefix = line[:len(line) - len(line.lstrip(" \t"))]
    columns = len(prefix.expandtabs(4))
    while content_indents and columns < content_indents[-1]:
        content_indents.pop()
    return columns - (content_indents[-1] if content_indents else 0)


def _top_level_heading(line: str, content_indents: list[int]) -> re.Match[str] | None:
    """Nested headings belong to a list item, not to the issue section index."""
    if content_indents:
        return None
    return HEADING.match(line)


def _append_continuation(
    items: list[dict], line: str, in_criteria: bool, separator: bool,
    active: list[int], recent: int | None, lazy: bool,
    indents: list[int], previous_indents: list[int], previous_active: list[int],
) -> tuple[int | None, bool, list[int]]:
    """Bind literal continuation to its owning acceptance item, including lazy lines."""
    if not in_criteria or separator:
        return recent, False, active
    if active:
        owner = active[-1]
    elif lazy:
        owner = recent
        indents[:] = previous_indents
        active = previous_active
    else:
        return recent, False, active
    if owner is None:
        return recent, False, active
    items[owner]["text"] += "\n" + line.rstrip("\r\n")
    return owner, True, active


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
    html_block = ""
    paragraph_open = False
    list_content_indents: list[int] = []
    active_item_indexes: list[int] = []
    recent_item_index: int | None = None
    can_lazily_continue = False

    for index, line in enumerate(lines):
        stripped = line.lstrip(" \t")
        prior_indents = list_content_indents.copy()
        prior_active = active_item_indexes.copy()
        relative_indent = _relative_list_indent(line, list_content_indents) if line.strip() else 0
        active_item_indexes = active_item_indexes[:len(list_content_indents)]
        # Track inert blocks before examining delimiters inside them.
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if html_block:
            html_block = _advance_html_block(html_block, stripped)
            continue
        if not line.strip():
            paragraph_open = False
            can_lazily_continue = False
            continue
        # A code block is indented four columns relative to its list container.
        if relative_indent >= 4:
            can_lazily_continue = False
            continue
        if stripped.startswith((chr(96) * 3, "~~~")):
            symbol = stripped[0]
            width = len(stripped) - len(stripped.lstrip(symbol))
            suffix = stripped[width:].strip()
            if not fence_marker:
                # A backtick opening fence cannot have backticks in its info string.
                if symbol == "~" or chr(96) not in suffix:
                    fence_marker, fence_width = symbol, width
                    paragraph_open = False
                    can_lazily_continue = False
                    continue
            elif symbol == fence_marker and width >= fence_width and not suffix:
                fence_marker, fence_width = "", 0
                continue
        if fence_marker:
            continue

        raw_inert, html_block = _open_raw_html_block(stripped, paragraph_open)
        if raw_inert:
            paragraph_open = False
            can_lazily_continue = False
            continue

        # Comments inside fenced code must not change parser state.
        if stripped.startswith("<!--"):
            in_comment = "-->" not in line
            paragraph_open = False
            can_lazily_continue = False
            continue

        heading = _top_level_heading(line, list_content_indents)
        if heading:
            paragraph_open = False
            can_lazily_continue = False
            depth = len(heading.group(1))
            if depth <= 2:
                heading_title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(2)).strip()
                in_criteria = depth == 2 and bool(CRITERIA_TITLE.fullmatch(heading_title))
                if in_criteria:
                    sections += 1
            continue
        match = _criterion_match(line, in_criteria, paragraph_open)
        if match is None:
            separator = bool(THEMATIC_BREAK.fullmatch(line))
            recent_item_index, can_lazily_continue, active_item_indexes = _append_continuation(
                items, line, in_criteria, separator, active_item_indexes,
                recent_item_index, can_lazily_continue,
                list_content_indents, prior_indents, prior_active,
            )
            paragraph_open = not separator
            continue
        paragraph_open = False
        list_content_indents.append(len(match.group("prefix").expandtabs(4)))
        items.append(
            {
                "ordinal": len(items) + 1,
                "line": index,
                "text": match.group("text"),
                "first_line_text": match.group("text"),
                "prefix": match.group("prefix"),
                "ending": match.group("ending"),
                "checked": bool(match.group("checkbox") and "x" in match.group("checkbox").lower()),
            }
        )
        active_item_indexes.append(len(items) - 1)
        recent_item_index = len(items) - 1
        can_lazily_continue = True
        normalized[index] = match.group("prefix") + match.group("text") + match.group("ending")

    if fence_marker or in_comment or (html_block and html_block != "until-blank"):
        raise ValueError("Unterminated inert Markdown block")
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
        if status in {"verified", "failed", "partial", "not-applicable"} and (
            not isinstance(evidence, list)
            or not evidence
            or any(not isinstance(ref, str) or not ref.strip() for ref in evidence)
        ):
            raise ValueError(
                "Verified, failed, partial, and not-applicable decisions require locatable evidence"
            )

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
            + observed["first_line_text"] + observed["ending"]
        )
        changes.append(
            {"ordinal": expected["ordinal"], "text": expected["text"], "checked": desired, "evidence": evidence or []}
        )

    new_body = "".join(current_lines)
    if analyze_body(new_body)[2] != current_norm:
        raise ValueError("Reconciliation altered normative content")
    return new_body, {
        "changes": changes, "warnings": warnings, "criteria_total": len(original),
        "publication": {
            "mode": "offline-proposal-only",
            "unconditional_github_patch_permitted": False,
            "atomic_conditional_write": "REQUIRED_NOT_ASSERTED",
        },
    }


def check_remote_readback(expected_body: str, observed_body: str,
                          material_sha: str, observed_material_sha: str) -> dict:
    """Fail closed on a fresh controller-supplied GitHub read-back.

    This comparison does not fetch GitHub data, prove provenance or grant write
    authority. The authorized controller must supply the *new* remote issue body
    and the freshly validated material identity after the remote update. A
    certified result-only child may have a different current PR HEAD.
    """
    if not SHA.fullmatch(material_sha) or material_sha != observed_material_sha:
        raise ValueError("Remote read-back material SHA differs from audited SHA")
    if observed_body != expected_body:
        raise ValueError("Remote issue read-back differs from proposed body")
    _, criteria, _ = analyze_body(observed_body)
    return {
        "subject_sha": material_sha,
        "criteria_total": len(criteria),
        "criteria_checked": sum(bool(item["checked"]) for item in criteria),
        "body_match": True,
        "publication_atomicity": "NOT_ASSERTED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audited-body", type=Path, required=True)
    parser.add_argument("--current-body", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--material-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--readback-body", type=Path)
    parser.add_argument("--observed-material-sha")
    args = parser.parse_args()
    if (args.readback_body is None) != (args.observed_material_sha is None):
        raise ValueError("Read-back body and observed material SHA must both be provided")
    audited_body = args.audited_body.read_text(encoding="utf-8")
    current_body = args.current_body.read_text(encoding="utf-8")
    audit = json.loads(args.audit.read_text(encoding="utf-8"))
    result, summary = reconcile(audited_body, current_body, audit, args.material_sha)
    if args.readback_body is not None:
        summary["remote_readback"] = check_remote_readback(
            result, args.readback_body.read_text(encoding="utf-8"),
            args.material_sha, args.observed_material_sha,
        )
    args.output.write_text(result, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
