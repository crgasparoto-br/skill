#!/usr/bin/env python3
"""Independently fail closed when normative Markdown list items vanish from requirement closure."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from audit_artifact_io import load_json_artifact

NORMATIVE_HEADING_RE = re.compile(
    r"\b(escopo|scope|requisitos?|requirements?|crit[eé]rios?(?:\s+de)?\s+aceite|"
    r"acceptance\s+criteria|invariantes?|invariants?|comportamento\s+esperado|expected\s+behavio(?:u)?r)\b",
    re.IGNORECASE,
)
NON_NORMATIVE_HEADING_RE = re.compile(
    r"\b(fora\s+de\s+escopo|out\s+of\s+scope|refer[eê]ncias?|references?)\b",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
LIST_ITEM_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")


def normalize(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^[-*+]\s+", "", value)
    value = re.sub(r"^\d+[.)]\s+", "", value)
    value = re.sub(r"^- \[[ xX]\]\s+", "", value)
    value = value.strip("| ")
    return re.sub(r"\s+", " ", value)


def load_object(path: Path) -> dict:
    value = load_json_artifact(path)
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def source_path(snapshot_path: Path, source: dict) -> Path:
    value = Path(str(source.get("path") or ""))
    return value if value.is_absolute() else (snapshot_path.parent / value).resolve()


def normative_list_items(snapshot_path: Path, snapshot: dict) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for source in snapshot.get("sources") or []:
        if not isinstance(source, dict) or source.get("textual") is not True:
            continue
        sid = str(source.get("id") or "").strip()
        if not sid:
            continue
        path = source_path(snapshot_path, source)
        if not path.is_file():
            raise FileNotFoundError(f"specification source file missing: {sid}: {path}")
        heading = ""
        for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = raw.strip()
            match = HEADING_RE.match(stripped)
            if match:
                heading = normalize(match.group(1))
                continue
            if not LIST_ITEM_RE.match(raw.lstrip()):
                continue
            if not heading or NON_NORMATIVE_HEADING_RE.search(heading):
                continue
            if not NORMATIVE_HEADING_RE.search(heading):
                continue
            text = normalize(raw)
            if text:
                found.append({"source_id": sid, "source_line": line_no, "source_text": text})
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--specification-snapshot", required=True)
    parser.add_argument("--requirement-closure", required=True)
    args = parser.parse_args()

    snapshot_path = Path(args.specification_snapshot).resolve()
    closure_path = Path(args.requirement_closure).resolve()
    try:
        snapshot = load_object(snapshot_path)
        closure = load_object(closure_path)
        expected = normative_list_items(snapshot_path, snapshot)
    except Exception as exc:
        print(f"BLOCK: cannot verify normative section coverage: {exc}")
        return 2

    observed = {
        (
            str(item.get("source_id") or ""),
            int(item.get("source_line") or 0),
            str(item.get("source_text") or ""),
        )
        for item in closure.get("obligations") or []
        if isinstance(item, dict)
    }
    missing = [
        item
        for item in expected
        if (str(item["source_id"]), int(item["source_line"]), str(item["source_text"])) not in observed
    ]
    if missing:
        for item in missing:
            print(
                "BLOCK: normative specification list item missing from requirement closure: "
                f"{item['source_id']}:{item['source_line']}: {item['source_text']}"
            )
        return 2

    print(f"READY: independent normative-section coverage verified ({len(expected)} list items)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
