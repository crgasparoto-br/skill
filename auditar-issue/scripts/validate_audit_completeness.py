#!/usr/bin/env python3
"""Fail-closed audit inventory reconciliation before publishing a verdict."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
VERDICTS = {
    "APROVADA", "APROVADA COM RESSALVAS", "APROVADA INTERNAMENTE",
    "INCONCLUSIVA", "REPROVADA",
}
STATES = {"covered", "not-applicable", "not-executed"}
HISTORY = {"resolved", "still-open", "regressed", "not-applicable"}
DISPOSITIONS = {
    "blocking", "actionable-recommendation", "optional-recommendation",
    "out-of-scope", "invalid-finding",
}


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def check_evidence(root: Path, row: dict, label: str, errors: list[str]) -> None:
    relative = row.get("evidence_path")
    digest = row.get("evidence_sha256")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        errors.append(f"{label}: evidence path missing or absolute")
        return
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        errors.append(f"{label}: evidence missing or escapes workspace")
        return
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        errors.append(f"{label}: evidence SHA-256 missing")
        return
    if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        errors.append(f"{label}: evidence hash mismatch")


def require_reason(row: dict, label: str, errors: list[str]) -> None:
    reason = row.get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < 20:
        errors.append(f"{label}: substantive reason required")


def indexed(rows: object, label: str, errors: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    if not isinstance(rows, list):
        errors.append(f"{label}: list required")
        return result
    for n, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"{label}[{n}]: object required")
            continue
        key = row.get("id")
        if not isinstance(key, str) or not key.strip() or key in result:
            errors.append(f"{label}[{n}]: missing or repeated ID")
            continue
        result[key] = row
    return result


def validate_identity(inventory: dict, report: dict, head: str, errors: list[str]) -> None:
    source = inventory.get("identity")
    observed = report.get("identity")
    if not isinstance(source, dict) or not isinstance(observed, dict):
        errors.append("identity objects required in inventory and report")
        return
    required = ("repository", "base_sha", "head_sha")
    if any(not source.get(key) for key in required):
        errors.append("incomplete frozen identity")
    if source != observed or source.get("head_sha") != head:
        errors.append("identity mismatch or stale HEAD")
    if not SHA.fullmatch(head) or not SHA.fullmatch(str(source.get("base_sha", ""))):
        errors.append("invalid immutable SHA")


def validate_sources(inventory: dict, root: Path, errors: list[str]) -> set[str]:
    sources = indexed(inventory.get("sources"), "sources", errors)
    kinds = set()
    for key, source in sources.items():
        if source.get("kind") not in {"specification", "diff", "contract"}:
            errors.append(f"source {key}: unknown kind")
        kinds.add(source.get("kind"))
        check_evidence(root, source, f"source {key}", errors)
    if not {"specification", "diff"} <= kinds:
        errors.append("independent specification and diff sources required")
    diff_sources = [s for s in sources.values() if s.get("kind") == "diff"]
    if len(diff_sources) != 1:
        errors.append("exactly one immutable Git diff inventory is required")
    else:
        diff_source = diff_sources[0]
        try:
            snapshot = read_json(root / str(diff_source["evidence_path"]))
            identity = inventory.get("identity", {})
            paths = snapshot.get("changed_paths")
            if (snapshot.get("base_sha") != identity.get("base_sha")
                    or snapshot.get("head_sha") != identity.get("head_sha")
                    or not isinstance(paths, list) or not paths
                    or len(set(paths)) != len(paths)
                    or set(paths) != set(inventory.get("discovery", {}).get("changed_paths", []))):
                errors.append("changed-path inventory diverges from immutable Git diff")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(f"invalid immutable Git diff inventory: {exc}")
    discovery = inventory.get("discovery")
    if not isinstance(discovery, dict):
        errors.append("independent discovery is required")
    else:
        if discovery.get("mode") != "independent-rederivation":
            errors.append("inventory must be independently rederived")
        if not isinstance(discovery.get("procedure"), str) or len(discovery["procedure"].strip()) < 30:
            errors.append("discovery procedure must be reproducible")
        if not discovery.get("changed_paths") or not isinstance(discovery["changed_paths"], list):
            errors.append("changed-path inventory is required")
    return set(sources)


def validate_inventory(inventory: dict, source_ids: set[str],
                       errors: list[str]) -> tuple[dict, dict, dict]:
    requirements = indexed(inventory.get("requirements"), "inventory requirements", errors)
    surfaces = indexed(inventory.get("surfaces"), "inventory surfaces", errors)
    historical = indexed(inventory.get("previous_findings"), "inventory previous_findings", errors)
    if not requirements or not surfaces:
        errors.append("inventory lacks atomic requirements or material surfaces")
    for key, req in requirements.items():
        if req.get("source_id") not in source_ids:
            errors.append(f"requirement {key}: unknown canonical source")
    for key, surface in surfaces.items():
        if surface.get("requirement_id") not in requirements:
            errors.append(f"surface {key}: requirement missing")
        if not all(isinstance(surface.get(k), str) and surface[k].strip()
                   for k in ("risk_family", "boundary")):
            errors.append(f"surface {key}: risk family or boundary missing")
        if surface.get("cost") not in {"cheap", "expensive"}:
            errors.append(f"surface {key}: invalid cost tier")
    for key, previous in historical.items():
        if not isinstance(previous.get("source_url"), str) or not previous["source_url"].strip():
            errors.append(f"previous finding {key}: authentic source required")
    return requirements, surfaces, historical


def validate_rows(name: str, expected: dict, actual: object, root: Path,
                  errors: list[str], *, allow_skipped_expensive: bool) -> bool:
    rows = indexed(actual, f"report {name}", errors)
    for key in sorted(expected.keys() - rows.keys()):
        errors.append(f"{name}: omitted {key}")
    for key in sorted(rows.keys() - expected.keys()):
        errors.append(f"{name}: undeclared {key}")
    limited = False
    for key, row in rows.items():
        status = row.get("status")
        if status not in STATES:
            errors.append(f"{name} {key}: invalid coverage state")
            continue
        if status == "not-executed":
            limited = True
            require_reason(row, f"{name} {key}", errors)
            if not allow_skipped_expensive or expected.get(key, {}).get("cost") != "expensive":
                errors.append(f"{name} {key}: cheap or mandatory coverage not executed")
        elif status == "not-applicable":
            require_reason(row, f"{name} {key}", errors)
            check_evidence(root, row, f"{name} {key}", errors)
        else:
            check_evidence(root, row, f"{name} {key}", errors)
    return limited


def validate_changed_paths(inventory: dict, report: dict, surfaces: dict,
                           root: Path, errors: list[str]) -> None:
    discovery = inventory.get("discovery", {})
    expected = set(discovery.get("changed_paths", []))
    reviews = indexed(report.get("changed_path_reviews"), "report changed_path_reviews", errors)
    for key in sorted(expected - reviews.keys()):
        errors.append(f"changed path not reviewed: {key}")
    for key in sorted(reviews.keys() - expected):
        errors.append(f"unexpected reviewed path: {key}")
    for key, row in reviews.items():
        status = row.get("status")
        if status not in {"covered", "not-applicable"}:
            errors.append(f"changed path {key}: requires completed review")
            continue
        if status == "not-applicable":
            require_reason(row, f"changed path {key}", errors)
        else:
            affected = row.get("surface_ids")
            if not isinstance(affected, list) or not affected or set(affected) - surfaces.keys():
                errors.append(f"changed path {key}: known surfaces not linked")
        check_evidence(root, row, f"changed path {key}", errors)


def validate_history(expected: dict, reported: object, root: Path,
                     errors: list[str]) -> None:
    rows = indexed(reported, "report previous_findings", errors)
    for key in sorted(expected.keys() - rows.keys()):
        errors.append(f"previous finding silently dropped: {key}")
    for key in sorted(rows.keys() - expected.keys()):
        errors.append(f"unrecognized historical finding: {key}")
    for key, row in rows.items():
        if row.get("disposition") not in HISTORY:
            errors.append(f"previous finding {key}: invalid disposition")
        require_reason(row, f"previous finding {key}", errors)
        check_evidence(root, row, f"previous finding {key}", errors)


def validate_findings(report: dict, requirements: dict, surfaces: dict,
                      root: Path, errors: list[str]) -> int:
    findings = indexed(report.get("findings"), "report findings", errors)
    blocking = set()
    for key, finding in findings.items():
        if finding.get("requirement_id") not in requirements:
            errors.append(f"finding {key}: unknown requirement")
        if finding.get("surface_id") not in surfaces:
            errors.append(f"finding {key}: unknown surface")
        if finding.get("disposition") not in DISPOSITIONS:
            errors.append(f"finding {key}: invalid disposition")
        if finding.get("disposition") == "blocking":
            blocking.add(key)
        if not isinstance(finding.get("root_cause"), str) or len(finding["root_cause"].strip()) < 12:
            errors.append(f"finding {key}: root cause missing")
        check_evidence(root, finding, f"finding {key}", errors)
    reported_blockers = report.get("blocking_ids")
    if not isinstance(reported_blockers, list) or len(set(reported_blockers)) != len(reported_blockers):
        errors.append("blocking_ids must be a unique list")
    elif set(reported_blockers) != blocking:
        errors.append("report blocker ledger does not match findings")
    return len(blocking)


def validate(inventory: dict, report: dict, root: Path, head: str) -> list[str]:
    errors: list[str] = []
    if inventory.get("schema_version") != 1 or report.get("schema_version") != 1:
        errors.append("unsupported schema_version")
    validate_identity(inventory, report, head, errors)
    source_ids = validate_sources(inventory, root, errors)
    requirements, surfaces, historical = validate_inventory(inventory, source_ids, errors)
    validate_changed_paths(inventory, report, surfaces, root, errors)
    blockers = validate_findings(report, requirements, surfaces, root, errors)
    verdict = report.get("verdict")
    if verdict not in VERDICTS:
        errors.append("invalid verdict")
    if blockers and verdict != "REPROVADA":
        errors.append("blocking findings require REPROVADA")
    if verdict == "REPROVADA" and not blockers:
        errors.append("REPROVADA without blocker")
    can_skip = blockers > 0 and verdict == "REPROVADA"
    limited_req = validate_rows("requirements", requirements, report.get("requirements"),
                                root, errors, allow_skipped_expensive=False)
    limited_surface = validate_rows("surfaces", surfaces, report.get("surfaces"),
                                    root, errors, allow_skipped_expensive=can_skip)
    validate_history(historical, report.get("previous_findings"), root, errors)
    expected_coverage = "limited" if limited_req or limited_surface else "comprehensive"
    if report.get("coverage") != expected_coverage:
        errors.append("coverage declaration does not match executed inventory")
    if verdict in {"APROVADA", "APROVADA COM RESSALVAS", "APROVADA INTERNAMENTE"} and expected_coverage == "limited":
        errors.append("limited coverage cannot approve")
    if report.get("discovery_closed") is not True:
        errors.append("all cheap risk families must be harvested before publication")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args()
    try:
        errors = validate(read_json(args.inventory), read_json(args.report_json),
                          args.root.resolve(), args.head_sha)
    except (OSError, ValueError, TypeError) as exc:
        errors = [f"unreadable or invalid audit inputs: {exc}"]
    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print("PASS: independent inventory and consolidated audit report reconciled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
