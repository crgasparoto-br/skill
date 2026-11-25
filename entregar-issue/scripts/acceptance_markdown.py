"""Bounded acceptance-section scanner derived from the reviewed checklist parser."""
from __future__ import annotations

import re

HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*\r?\n?$")
CRITERIA_TITLE = re.compile(r"^(crit[eé]rios de aceite|acceptance criteria)$", re.IGNORECASE)
ITEM = re.compile(
    r"^(?P<prefix>[ \t]*(?:[-*+]|[0-9]{1,9}[.)])[ \t]+)"
    r"(?P<checkbox>\[[ xX]\][ \t]+)?"
    r"(?P<text>\S.*?)(?P<ending>\r?\n?)$"
)
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


def _lazy_continuation(line: str) -> bool:
    stripped = line.lstrip(" \t")
    return bool(line.strip() and not ITEM.match(line) and not HEADING.match(line)
                and not THEMATIC_BREAK.fullmatch(stripped)
                and not stripped.startswith((chr(96) * 3, "~~~", "<", ">")))


def analyze_body(body: str) -> dict[int, tuple[str, str]]:
    """Index real criteria by original line, including their own continuation text."""
    lines = body.splitlines(keepends=True)
    items: list[dict] = []
    in_criteria = False
    sections = 0
    fence_marker = ""
    fence_width = 0
    in_comment = False
    html_block = ""
    inert_depth = 0
    paragraph_open = False
    list_content_indents: list[int] = []
    active_items: list[dict] = []
    item_paragraph_open = False

    def continuation(line: str) -> None:
        if in_criteria and active_items:
            active_items[-1]["continuations"].append(line.strip())

    def skip_inert(line: str, stripped: str, relative_indent: int) -> bool:
        nonlocal fence_marker, fence_width, in_comment, html_block, paragraph_open
        # Track inert blocks before examining delimiters inside them.
        if in_comment:
            continuation(line)
            if "-->" in line:
                in_comment = False
            return True
        if html_block:
            continuation(line)
            html_block = _advance_html_block(html_block, stripped)
            return True
        if not line.strip():
            paragraph_open = False
            return True
        # A code block is indented four columns relative to its list container.
        if relative_indent >= 4:
            continuation(line)
            return True
        if stripped.startswith((chr(96) * 3, "~~~")):
            symbol = stripped[0]
            width = len(stripped) - len(stripped.lstrip(symbol))
            suffix = stripped[width:].strip()
            if not fence_marker:
                # A backtick opening fence cannot have backticks in its info string.
                if symbol == "~" or chr(96) not in suffix:
                    fence_marker, fence_width = symbol, width
                    paragraph_open = False
                    continuation(line)
                    return True
            elif symbol == fence_marker and width >= fence_width and not suffix:
                fence_marker, fence_width = "", 0
                continuation(line)
                return True
        if fence_marker:
            continuation(line)
            return True

        raw_inert, html_block = _open_raw_html_block(stripped, paragraph_open)
        if raw_inert:
            continuation(line)
            paragraph_open = False
            return True

        # Comments inside fenced code must not change parser state.
        if stripped.startswith("<!--"):
            continuation(line)
            in_comment = "-->" not in line
            paragraph_open = False
            return True
        return False

    for index, line in enumerate(lines):
        stripped = line.lstrip(" \t")
        prefix_width = len(line[:len(line) - len(stripped)].expandtabs(4))
        if (item_paragraph_open and list_content_indents and prefix_width < list_content_indents[-1]
                and _lazy_continuation(line)):
            continuation(line)
            continue
        item_paragraph_open = False
        relative_indent = _relative_list_indent(line, list_content_indents) if line.strip() else 0
        del active_items[len(list_content_indents):]
        # CommonMark implicitly closes fenced/raw blocks at the end of their
        # owning list container; never carry inert state into a sibling.
        if inert_depth > len(list_content_indents):
            fence_marker, fence_width, in_comment, html_block = "", 0, False, ""
            inert_depth = 0
        if skip_inert(line, stripped, relative_indent):
            inert_depth = len(list_content_indents) if fence_marker or in_comment or html_block else 0
            continue

        heading = _top_level_heading(line, list_content_indents)
        if heading:
            paragraph_open = False
            depth = len(heading.group(1))
            if depth <= 2:
                heading_title = re.sub(r"[ \t]+#+[ \t]*$", "", heading.group(2)).strip()
                in_criteria = depth == 2 and bool(CRITERIA_TITLE.fullmatch(heading_title))
                if in_criteria:
                    sections += 1
            continue
        match = _criterion_match(line, in_criteria, paragraph_open)
        if match is None:
            continuation(line)
            paragraph_open = not bool(THEMATIC_BREAK.fullmatch(line))
            item_paragraph_open = bool(active_items) and _lazy_continuation(line)
            continue
        paragraph_open = False
        list_content_indents.append(len(match.group("prefix").expandtabs(4)))
        marker = match.group("checkbox")
        item = {"line": index + 1, "text": match.group("text"), "continuations": [],
                "state": "not-present" if marker is None else
                "checked" if "x" in marker.lower() else "unchecked"}
        items.append(item)
        active_items.append(item)
        item_paragraph_open = True

    if not inert_depth and (fence_marker or in_comment or (html_block and html_block != "until-blank")):
        raise ValueError("Unterminated inert Markdown block")
    if sections != 1:
        raise ValueError("Expected exactly one level-2 acceptance-criteria section")
    if not items:
        raise ValueError("Acceptance-criteria section has no list items")
    return {item["line"]: (item["state"], "\n".join([item["text"], *item["continuations"]]))
            for item in items}
