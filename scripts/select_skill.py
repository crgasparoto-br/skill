#!/usr/bin/env python3
"""Rank catalog skills for a request without pretending to replace semantic judgment."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from .catalog import ROOT, load_catalog, validate_catalog
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT, load_catalog, validate_catalog

WORD_RE = re.compile(r"[\wÀ-ÿ]+", flags=re.UNICODE)


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def rank_skills(
    query: str,
    catalog: dict[str, Any],
    available_capabilities: set[str] | None = None,
) -> dict[str, Any]:
    normalized_query = normalize(query)
    results: list[dict[str, Any]] = []
    for item in catalog.get("skills", []):
        positive = [trigger for trigger in item["positive_triggers"] if normalize(trigger) in normalized_query]
        negative = [trigger for trigger in item["negative_triggers"] if normalize(trigger) in normalized_query]
        query_tokens = set(WORD_RE.findall(normalized_query))
        token_hits = sum(1 for trigger in item["positive_triggers"] if query_tokens.intersection(WORD_RE.findall(normalize(trigger))))
        score = len(positive) * 5 + token_hits - len(negative) * 7
        results.append({
            "skill": item["id"],
            "score": score,
            "matched_positive": positive,
            "matched_negative": negative,
            "status": item["status"],
            "read_only": item["read_only"],
            "missing_capabilities": sorted(
                set(item["required_capabilities"]) - available_capabilities
            ) if available_capabilities is not None else [],
        })
    results.sort(key=lambda value: (-value["score"], value["skill"]))
    direct_results = [result for result in results if result["matched_positive"]]
    if not direct_results:
        decision = "UNKNOWN"
        reason = "no catalog trigger matched the request"
    elif len(direct_results) > 1 and direct_results[0]["score"] - direct_results[1]["score"] < 5:
        decision = "UNKNOWN"
        reason = "multiple direct catalog triggers matched; require semantic disambiguation"
    else:
        selected = direct_results[0]
        if selected["missing_capabilities"]:
            decision = "BLOCKED"
            reason = "selected skill requires unavailable capabilities"
        else:
            decision = selected["skill"]
            reason = "highest explainable trigger score"
    return {"decision": decision, "reason": reason, "candidates": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--available-capability", action="append", default=[])
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate_catalog(root)
    if errors:
        print("Cannot select from an invalid catalog:")
        for error in errors:
            print(f"- {error}")
        return 2
    available = set(args.available_capability) if args.available_capability else None
    result = rank_skills(args.query, load_catalog(root), available)
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"decision={result['decision']} reason={result['reason']}")
        for candidate in result["candidates"][:3]:
            print(f"{candidate['skill']}: score={candidate['score']} positive={candidate['matched_positive']} negative={candidate['matched_negative']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
