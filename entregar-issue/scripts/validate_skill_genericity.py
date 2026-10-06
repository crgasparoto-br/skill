#!/usr/bin/env python3
"""Reject concrete coupling in permanent skill assets.

A permanent asset is reused across repositories and domains, so anything that
encodes one origin makes the asset non-portable: an issue number, a machine path,
a domain identifier stated as normative prose, or an internal hostname.

Rules, all blocking:

1. a test file numbered by issue (`test_issue_123_*.py`) encodes one issue;
2. a heading derived from an issue number states a permanent rule from history;
3. an absolute host path encodes one machine: a POSIX home or mount root, or a
   Windows user root;
4. a concrete camelCase identifier in Markdown prose encodes one domain, unless it
   appears inside an inline code span or a fenced block, where it is a delimited
   example rather than a normative statement;
5. an external host that is neither a reserved example domain nor a declared
   generic host encodes one organization.

Rule 5 reads the whole document, not only prose, because a concrete host is
rejectable even inside an example. Reserved example domains are the correct
mechanism for illustrative hosts, so they are always allowed.

Rule 3 deliberately covers only unambiguous forms. A bare drive-letter pattern
cannot be told apart from an escape sequence or from regex source such as
`^name:\\s*([^\\n]+)$`, so the Windows form requires an explicit user root.

This file excludes itself from the scan: it declares the very patterns it blocks.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

NUMBERED_TEST = re.compile(r"^test_issue_[0-9]+.*\.py$", re.IGNORECASE)
DERIVED_HEADING = re.compile(r"derivad[oa]s?\s+(?:da|de)\s+issue\s+#?\d+", re.IGNORECASE)
HOST_PATH = re.compile(
    r"(?:/Users/|/home/[A-Za-z0-9_.-]+/|/Volumes/|/private/var/"
    r"|[A-Za-z]:\\{1,2}(?:Users|Documents and Settings)\\{1,2}[^\s\\\"']+)"
)
CAMEL_IDENTIFIER = re.compile(r"\b[a-z]+[A-Z][a-zA-Z0-9]*\b")
FENCE = re.compile(r"^\s*(?:```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
URL = re.compile(r"https?://([^\s`)\"'<>/]+)")

GENERIC_HOSTS = frozenset({
    "github.com",
    "raw.githubusercontent.com",
    "docs.github.com",
    "json-schema.org",
    "www.json-schema.org",
    "pypi.org",
    "python.org",
    "docs.python.org",
})
RESERVED_HOSTS = frozenset({"localhost", "example.com", "example.org", "example.net"})
RESERVED_SUFFIXES = (".invalid", ".example", ".test", ".localhost")
TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".txt"}
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".git", "node_modules"}


def host_is_generic(host: str) -> bool:
    normalized = host.casefold().split(":")[0]
    if normalized in GENERIC_HOSTS or normalized in RESERVED_HOSTS:
        return True
    return any(normalized.endswith(suffix) for suffix in RESERVED_SUFFIXES)


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Return Markdown lines with fenced blocks and inline code spans removed."""
    lines: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        lines.append((number, INLINE_CODE.sub(" ", line)))
    return lines


def validate_skill_genericity(root: Path) -> list[str]:
    errors: list[str] = []
    self_path = Path(__file__).resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.resolve() == self_path:
            continue
        relative = path.relative_to(root)
        if NUMBERED_TEST.match(path.name):
            errors.append(f"numbered issue-specific test filename: {relative}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if DERIVED_HEADING.search(text):
            errors.append(f"historical issue-derived permanent rule: {relative}")
        for match in sorted(set(HOST_PATH.findall(text))):
            errors.append(f"absolute host path {match!r}: {relative}")
        hosts = {host.casefold().split(":")[0] for host in URL.findall(text)}
        for host in sorted(host for host in hosts if not host_is_generic(host)):
            errors.append(
                f"concrete external host {host!r}: {relative}; "
                "use a reserved example domain or declare a generic host"
            )
        if path.suffix.lower() == ".md":
            for number, line in prose_lines(text):
                for identifier in sorted(set(CAMEL_IDENTIFIER.findall(line))):
                    errors.append(f"concrete identifier {identifier!r} in prose at line {number}: {relative}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill-root", required=True)
    args = parser.parse_args()
    errors = validate_skill_genericity(Path(args.skill_root).resolve())
    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print("READY: skill permanent assets are free of concrete coupling")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
