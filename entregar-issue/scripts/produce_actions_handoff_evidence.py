#!/usr/bin/env python3
"""Stage reviewed semantic evidence for the existing GitHub Actions handoff gate.

The test index is factual, not a semantic oracle. This producer never changes a
pending obligation to covered or a control to passed without a reviewed input.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from reviewed_phase_decision import MissingReviewedEvidenceError, _verify_deferred_phase, digest

SHA = re.compile(r"[0-9a-f]{40}\Z")
ALLOWED_REPORTS = frozenset({
    "standard-evidence.json", "requirement-attack-matrix.json",
    "risk-saturation.json", "inherited-controls.json",
    "codebase-grounding.json", "audit-remediation.json",
    "audit-source-result.json", "learning-closure.json",
    "audit-escape-closure.json", "previous-audit-escape-closure.json",
    "previous-inherited-controls.json", "evidence-provenance.json",
})
IDENTITY_TOKENS = {
    "head_sha": "__MATERIAL_HEAD_SHA__",
    "subject_sha": "__MATERIAL_HEAD_SHA__",
    "base_sha": "__WORK_ITEM_START_SHA__",
}
OBLIGATION_FIELDS = frozenset({
    "disposition", "requirement_ids", "inventory_ids", "assertion_ids",
    "scope_decision", "rationale",
})


def read_json(path: Path) -> dict:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise ValueError(f"missing or unsafe evidence file: {path.name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"evidence must be a JSON object: {path.name}")
    return data


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError(f"git {' '.join(args[:2])} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def verified_source(root: Path, source: Path, name: str, hashes: dict) -> dict:
    if name not in hashes or not re.fullmatch(r"[0-9a-f]{64}", str(hashes[name])):
        raise ValueError(f"missing SHA-256 declaration for {name}")
    path = source / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != source.resolve():
        raise ValueError(f"unsafe reviewed evidence path: {name}")
    raw = path.read_bytes()
    if not raw or digest(raw) != hashes[name]:
        raise ValueError(f"reviewed evidence digest mismatch: {name}")
    return read_json(path)


def bind_identity(value: object, head: str, start: str) -> object:
    if isinstance(value, list):
        return [bind_identity(item, head, start) for item in value]
    if isinstance(value, dict):
        return {key: (head if key in {"head_sha", "subject_sha"} and item == "__MATERIAL_HEAD_SHA__"
                      else start if key == "base_sha" and item == "__WORK_ITEM_START_SHA__"
                      else bind_identity(item, head, start))
                for key, item in value.items()}
    if isinstance(value, str) and value in set(IDENTITY_TOKENS.values()):
        raise ValueError("identity placeholder outside a declared identity field")
    return value


def merge_closure(starter: dict, reviewed: dict) -> dict:
    if set(reviewed) != {"schema_version", "obligations", "controls"} or reviewed["schema_version"] != 1:
        raise ValueError("reviewed closure must contain schema_version=1, obligations, controls")
    updates = reviewed["obligations"]
    if not isinstance(updates, dict):
        raise ValueError("reviewed obligations must be keyed by immutable candidate_key")
    originals = {item["candidate_key"] for item in starter["obligations"]}
    if set(updates) != originals:
        raise ValueError(f"reviewed obligation inventory incomplete: missing={len(originals - set(updates))}, extra={len(set(updates) - originals)}")
    for item in starter["obligations"]:
        patch = updates[item["candidate_key"]]
        if not isinstance(patch, dict) or set(patch) != OBLIGATION_FIELDS:
            raise ValueError(f"reviewed obligation fields invalid: {item['id']}")
        item.update(patch)
    controls = reviewed["controls"]
    editable = set(starter) - {
        "schema_version", "specification_snapshot", "primary_issue_source_id",
        "obligations", "source_coverage",
    }
    if not isinstance(controls, dict) or set(controls) != editable:
        raise ValueError("reviewed closure controls must supply exactly the canonical control families")
    starter.update(controls)
    return starter


def require_complete_semantic_review(
    closure: dict, *, issue_number: int | None = None,
    canonical_issue_body: str | None = None, parent_issue_open: bool = False,
) -> list[str]:
    """Prove pre-handoff closure; track independent review as unsatisfied."""
    deferred = [item for item in closure["obligations"]
                if item.get("disposition") == "deferred"]
    _verify_deferred_phase(closure, deferred, issue_number, canonical_issue_body,
                           parent_issue_open)
    unresolved = [item.get("id", "unknown") for item in closure["obligations"]
                  if item.get("disposition") not in {"covered", "not-applicable", "deferred"}]
    if unresolved:
        raise MissingReviewedEvidenceError(
            f"reviewed semantic closure incomplete: {len(unresolved)} unresolved "
            f"obligations ({', '.join(unresolved[:5])}); no certificate can be staged")
    unjustified = [item.get("id", "unknown") for item in closure["obligations"]
                   if item.get("disposition") == "not-applicable"
                   and not str(item.get("rationale") or "").strip()]
    if unjustified:
        raise MissingReviewedEvidenceError(
            "reviewed semantic closure has unjustified not-applicable "
            f"obligations ({', '.join(unjustified[:5])}); no certificate can be staged")
    return sorted(str(item["id"]) for item in deferred)


def validate_incomplete_review(source: Path, starter: dict,
                               tests: dict | None = None) -> dict:
    """Record progressive draft decisions, never issue a certification claim.

    Draft 'covered' decisions are mechanically cross-checked against actually
    passed JUnit IDs.  This does *not* establish semantic equivalence; the
    approved-dossier path and independent audit remain mandatory.
    """
    import copy

    manifest = read_json(source / "manifest.json")
    if manifest.get("review_state") != "incomplete":
        return {}
    draft = read_json(source / "reviewed-closure.json")
    canonical = {item["candidate_key"] for item in starter["obligations"]}
    provided = draft.get("obligations")
    if (draft.get("schema_version") != 1 or not isinstance(provided, dict)
            or set(provided) != canonical):
        raise ValueError("incomplete reviewed closure differs from canonical candidate inventory")
    if manifest.get("artifact_sha256"):
        raise ValueError("incomplete dossier must not present reviewed artifact hashes")
    merged = merge_closure(copy.deepcopy(starter), draft)
    obligations = merged["obligations"]
    permitted = {"pending", "covered", "deferred", "not-applicable"}
    if any(item.get("disposition") not in permitted for item in obligations):
        raise ValueError("incomplete reviewed closure has invalid disposition")
    provisional = [item for item in obligations if item["disposition"] == "covered"]
    if any(not item.get("requirement_ids") or len(str(item.get("rationale") or "").strip()) < 20
           for item in provisional):
        raise ValueError("draft covered obligation lacks requirement IDs or reviewed rationale")
    bindings = manifest.get("test_bindings")
    if tests is None and (provisional or bindings):
        raise ValueError("draft test bindings require exact-head JUnit facts")
    validate_test_bindings(bindings, merged, tests or {})
    return {"review_state": "incomplete", "pending_obligations": sum(
                item["disposition"] == "pending" for item in obligations),
            "deferred_obligations": sum(
                item["disposition"] == "deferred" for item in obligations),
            "provisional_obligations": len(provisional),
            "canonical_candidate_keys_verified": True,
            "semantic_certification": "NOT_ASSERTED"}


def code_growth_command(
    root: Path, start: str, head: str, comparison: str, out: Path, source: Path,
) -> list[str]:
    command = [sys.executable, str(Path(__file__).with_name("check_code_growth.py")),
               "--repo", str(root), "--base-sha", start, "--head-sha", head,
               "--comparison-base-sha", comparison, "--out", str(out)]
    justifications = source / "code-growth-justifications.json"
    if justifications.is_file() and not justifications.is_symlink():
        command.extend(["--justifications", str(justifications)])
    return command


def stage_draft_code_growth(root: Path, out: Path, source: Path, head: str,
                            comparison: str | None = None) -> dict:
    """Run the official diff-based code-growth control; never infer a pass."""
    manifest = read_json(source / "manifest.json")
    start = manifest.get("work_item_start_sha")
    if not isinstance(start, str) or not SHA.fullmatch(start):
        raise ValueError("draft evidence needs a valid work-item start SHA")
    git(root, "merge-base", "--is-ancestor", start, head)
    path = out / ".audit" / "entregar-issue" / "code-growth.json"
    command = code_growth_command(root, start, head, comparison or start, path, source)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode not in {0, 2, 3}:
        raise ValueError(f"official CODE-GROWTH-001 could not execute: {result.stderr.strip()}")
    report = read_json(path) if path.is_file() else {}
    if result.returncode in {0, 2} and (
            report.get("subject_sha") != head or report.get("base_sha") != start
            or report.get("status") not in {"passed", "blocked"}):
        raise ValueError("CODE-GROWTH-001 report provenance invalid")
    return {"exit_code": result.returncode, "status": report.get("status", "unknown"),
            "blocking_files": report.get("blocking_files", []),
            "report": ".audit/entregar-issue/code-growth.json" if report else None}


def collect_exact_tests(out: Path, head: str) -> tuple[dict, dict]:
    facts = read_json(out / "test-execution-facts.json")
    index = read_json(out / "test-candidate-index.json")
    log = out / "pytest-exact-head.log"
    junit = out / "pytest-exact-head.xml"
    if (facts.get("subject_sha") != head or index.get("subject_sha") != head
            or facts.get("execution", {}).get("exit_code") != 0
            or not log.is_file() or digest(log.read_bytes()) != facts["execution"].get("log_sha256")
            or not junit.is_file() or digest(junit.read_bytes()) != index.get("source", {}).get("sha256")):
        raise ValueError("exact-head test log/JUnit attestation failed")
    from build_test_candidate_index import collect
    if collect(junit, head) != index:
        raise ValueError("test candidate index differs from exact-head JUnit")
    tests = {entry["id"]: entry["status"] for entry in index["tests"]}
    if not tests or index.get("requirement_mapping") != "UNKNOWN":
        raise ValueError("test index must be factual and unclassified")
    return tests, index


def load_reviewed_manifest(root: Path, source: Path, event: Path, target: dict) -> tuple[dict, str, list[str]]:
    if not source.is_dir() or source.is_symlink():
        raise MissingReviewedEvidenceError(f"reviewed semantic evidence not supplied under {source.relative_to(root)}")
    if not source.resolve().is_relative_to(root) or git(
        root, "status", "--porcelain", "--", source.relative_to(root).as_posix()
    ):
        raise ValueError("reviewed evidence must match the clean material HEAD checkout")
    manifest = read_json(source / "manifest.json")
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported reviewed evidence manifest")
    if manifest.get("review_state") == "incomplete":
        raise MissingReviewedEvidenceError(
            "reviewed dossier is explicitly incomplete; complete and verify all mandatory reports before certification"
        )
    if manifest.get("review_state") not in (None, "approved"):
        raise ValueError("unrecognized reviewed evidence state; fail closed")
    expected = {key: value for key, value in target.items() if key != "head_sha"}
    expected["head_ref"] = json.loads(event.read_text())["pull_request"]["head"]["ref"]
    if any(manifest.get(key) != val for key, val in expected.items()):
        raise ValueError("reviewed evidence manifest targets a different PR")
    if (manifest.get("evidence_profile") not in {"light", "standard", "critical"}
            or manifest.get("audit_history") not in {"verified-no-rejection", "previous-rejection"}):
        raise ValueError("risk profile or verified audit history is missing")
    for key in ("risk_justification", "audit_history_evidence"):
        if not isinstance(manifest.get(key), str) or len(manifest[key].strip()) < 20:
            raise ValueError(f"reviewed evidence requires a concrete {key}")
    start = manifest.get("work_item_start_sha")
    if not isinstance(start, str) or not SHA.fullmatch(start):
        raise ValueError("invalid work item starting commit")
    git(root, "merge-base", "--is-ancestor", start, target["head_sha"])
    changed = git(root, "diff", "--name-only", "--no-renames", start, target["head_sha"]).splitlines()
    if not changed:
        raise ValueError("empty material diff cannot be certified")
    return manifest, start, changed


def required_reviewed_reports(manifest: dict, changed: list[str]) -> tuple[set[str], bool]:
    needed = {"reviewed-closure.json"}
    if manifest["evidence_profile"] == "standard":
        needed.add("standard-evidence.json")
    elif manifest["evidence_profile"] == "critical":
        needed.update({"requirement-attack-matrix.json", "risk-saturation.json", "inherited-controls.json"})
    if manifest["audit_history"] == "previous-rejection":
        needed.update({"audit-remediation.json", "audit-source-result.json", "learning-closure.json",
                       "audit-escape-closure.json", "previous-audit-escape-closure.json"})
    if manifest.get("remediation_mode") in {"systemic-remediation", "mixed-remediation"}:
        needed.add("previous-inherited-controls.json")
    touched_code = any(path.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".sh")) for path in changed)
    touched_tests = any("test" in path.lower() or path.endswith((".cy.ts", ".spec.ts")) for path in changed)
    if touched_code or touched_tests:
        needed.add("codebase-grounding.json")
    return needed, touched_code


def validate_test_bindings(binding: object, closure: dict, tests: dict) -> None:
    if not isinstance(binding, dict):
        raise ValueError("reviewed test bindings are required")
    # A partially deferred requirement still needs executed controls for its
    # implementable pre-handoff clause; the post-handoff approval stays open.
    covered = {rid for item in closure["obligations"]
               if item["disposition"] == "covered" or
               (item["disposition"] == "deferred" and isinstance(
                   (item.get("scope_decision") or {}).get("pre_handoff_coverage"), dict))
               for rid in item["requirement_ids"]}
    if set(binding) != covered:
        raise ValueError("test bindings must account for every covered requirement")
    for requirement, controls in binding.items():
        if not isinstance(controls, dict) or set(controls) != {"positive", "negative", "regression"}:
            raise ValueError(f"invalid control classes for {requirement}")
        for kind, names in controls.items():
            if not isinstance(names, list) or not names or len(names) != len(set(names)):
                raise ValueError(f"missing or duplicate {kind} controls for {requirement}")
            if any(tests.get(name) != "passed" for name in names):
                raise ValueError(f"unreached/skipped/nonpassing {kind} test for {requirement}")
        if set(controls["positive"]) & set(controls["negative"]):
            raise ValueError(f"positive and negative controls are not distinct for {requirement}")


def canonical_issue_context(out: Path, repository: str, issue: int) -> tuple[str, bool]:
    """Validate authenticated preflight source before making phase decisions."""
    preflight = read_json(out / "handoff-preflight.json")
    body_path = out / "issue-body.md"
    body = body_path.read_text(encoding="utf-8") if body_path.is_file() else ""
    source = preflight.get("source") or {}
    expected = {"issue_body_sha256": digest(body.encode("utf-8")),
                "uri": f"https://github.com/{repository}/issues/{issue}"}
    if not body or any(source.get(key) != value for key, value in expected.items()):
        raise MissingReviewedEvidenceError("canonical issue source binding is unavailable")
    return body, source.get("issue_state") == "open"


def with_deferred_completion(inputs: dict, deferred_ids: list[str], issue: int) -> dict:
    """Add provisional completion metadata without asserting final audit."""
    if deferred_ids:
        return {**inputs, "issue_completion": "partial",
                "deferred_obligation_ids": deferred_ids,
                "remaining_issue_ids": [issue], "parent_issue_must_remain_open": True}
    return inputs


def candidate_module_inventory(exact_index: dict) -> dict:
    """Group executed JUnit facts for navigation, never semantic approval."""
    modules: dict = {}
    for case in exact_index["tests"]:
        module = case["id"].split("::", 1)[0]
        entry = modules.setdefault(module, {"passed": 0, "other": 0, "examples": []})
        entry["passed" if case["status"] == "passed" else "other"] += 1
        if len(entry["examples"]) < 3:
            entry["examples"].append(case["id"])
    return modules


def stage_draft_review(root: Path, out: Path, source: Path, starter: dict,
                       tests: dict, head: str, base: str) -> None:
    if not source.is_dir() or not (source / "manifest.json").is_file():
        return
    draft_check = validate_incomplete_review(source, starter, tests)
    if draft_check:
        manifest = read_json(source / "manifest.json")
        start = manifest["work_item_start_sha"]
        changed = git(root, "diff", "--name-only", "--no-renames", start, head).splitlines()
        required, _ = required_reviewed_reports(manifest, changed)
        hashes = manifest.get("artifact_sha256") or {}
        reviewed = read_json(source / "reviewed-closure.json")
        controls = reviewed.get("controls") or {}
        draft_check["required_reports"] = sorted(required)
        draft_check["missing_reports"] = sorted(
            name for name in required if not (source / name).is_file())
        draft_check["unhashed_reports"] = sorted(
            name for name in required if name not in hashes)
        draft_check["pending_review_controls"] = sorted(
            name for name, value in controls.items()
            if (isinstance(value, dict) and value.get("status") in {"pending", "blocked"})
            or (isinstance(value, list) and not value))
        draft_check["subject_sha"] = head
        draft_check["code_growth"] = stage_draft_code_growth(root, out, source, head, base)
        write_json(out / "reviewed-dossier-inventory.json", draft_check)


def produce(root: Path, out: Path, event: Path, base_ref: str) -> None:
    from prepare_actions_handoff import check_checkout, read_event

    repository, pr, issue, head, base = read_event(event, base_ref)
    check_checkout(root, head)
    identity = read_json(out / "handoff-preflight.json").get("identity") or {}
    expected = {"repository": repository, "issue_number": issue,
                "pull_request_number": pr, "material_head_sha": head, "base_sha": base}
    if any(identity.get(key) != val for key, val in expected.items()):
        raise ValueError("preflight identity differs from the exact PR material")
    tests, exact_index = collect_exact_tests(out, head)
    # Factual candidate grouping does not assert an oracle or semantic coverage.
    modules = candidate_module_inventory(exact_index)
    write_json(out / "semantic-test-review-candidates.json", {
        "schema_version": 1, "subject_sha": head, "issue_number": issue,
        "pull_request_number": pr, "source": "verified exact-SHA JUnit index",
        "candidate_modules": modules, "semantic_mapping": "UNKNOWN",
        "warning": "Names are navigation aids; assertions and negative controls require review.",
    })
    audit = out / ".audit" / "entregar-issue"
    starter = read_json(audit / "requirement-closure.json")
    obligations = [{"id": entry["id"], "candidate_key": entry["candidate_key"],
                    "source_text": entry["source_text"], "source_id": entry.get("source_id"),
                    "disposition": "pending-review"} for entry in starter["obligations"]]
    write_json(out / "semantic-evidence-candidates.json", {
        "schema_version": 1, "subject_sha": head,
        "obligations": obligations, "test_candidates": len(tests),
        "mapping": "UNKNOWN", "certification": "NOT_ASSERTED",
    })
    changed_paths = sorted(set(git(root, "diff", "--name-only", "--no-renames",
                                  base, head).splitlines()))
    write_json(out / "material-change-index.json", {
        "schema_version": 1, "base_sha": base, "subject_sha": head,
        "scope": "current-PR-base-to-material-HEAD; not issue-local start",
        "changed_paths": changed_paths,
        "semantic_test_impact": "UNKNOWN",
        "certification": "NOT_ASSERTED",
    })
    write_json(out / "evidence-review-worklist.json", {
        "schema_version": 1, "subject_sha": head, "issue_number": issue,
        "pull_request_number": pr, "base_ref": base_ref,
        "reviewed_dossier_path": f".github/handoff-evidence/issue-{issue}",
        "required_review": [
            "Confirm all normative source candidates and dispositions",
            "Record positive, discriminating negative, and regression controls per requirement",
            "Reconcile changed files, codebase grounding, and CODE-GROWTH-001",
            "Determine risk profile, independent audit history, and inherited controls",
            "Review semantic report provenance and hashes before certification",
        ],
        "pending_obligations": obligations,
        "test_index": "test-candidate-index.json",
        "material_change_index": "material-change-index.json",
        "semantic_control_mapping": "UNKNOWN",
        "certification": "NOT_ASSERTED",
    })
    source = root / ".github" / "handoff-evidence" / f"issue-{issue}"
    stage_draft_review(root, out, source, starter, tests, head, base)
    target = {"repository": repository, "issue_number": issue, "pull_request_number": pr,
              "base_ref": base_ref, "head_sha": head}
    manifest, start, changed = load_reviewed_manifest(root, source, event, target)
    hashes = manifest.get("artifact_sha256")
    if not isinstance(hashes, dict) or not set(hashes).issubset(ALLOWED_REPORTS | {"reviewed-closure.json"}):
        raise ValueError("reviewed artifact allowlist invalid")
    needed, touched_code = required_reviewed_reports(manifest, changed)
    if not needed.issubset(hashes):
        raise ValueError(f"missing required reviewed reports: {sorted(needed - set(hashes))}")
    closure = merge_closure(starter, verified_source(root, source, "reviewed-closure.json", hashes))
    canonical_body, parent_open = canonical_issue_context(out, repository, issue)
    deferred_ids = require_complete_semantic_review(
        closure, issue_number=issue, canonical_issue_body=canonical_body,
        parent_issue_open=parent_open)
    validate_test_bindings(manifest.get("test_bindings"), closure, tests)
    staged = {name: bind_identity(verified_source(root, source, name, hashes), head, start)
              for name in sorted(set(hashes) - {"reviewed-closure.json"})}
    write_json(audit / "requirement-closure.json", closure)
    for name, report in staged.items():
        write_json(audit / name, report)
    if touched_code:
        command = code_growth_command(root, start, head, base, audit / "code-growth.json", source)
        subprocess.run(command, check=True)
    inputs = {"subject_sha": head, "work_item_start_sha": start, "base_ref": base_ref,
              "head_ref": manifest["head_ref"], "evidence_profile": manifest["evidence_profile"],
              "audit_history": manifest["audit_history"]}
    if "remediation_mode" in manifest:
        inputs["remediation_mode"] = manifest["remediation_mode"]
    write_json(out / "certification-inputs.json",
               with_deferred_completion(inputs, deferred_ids, issue))
    write_json(out / "handoff-producer-status.json", {
        "status": "staged-for-independent-validation", "subject_sha": head,
        "source": f".github/handoff-evidence/issue-{issue}", "reports": sorted(staged),
        "reviewed_test_bindings": len(manifest["test_bindings"]),
        "warning": "JUnit and producer cannot prove semantic equivalence; official validation and independent audit are mandatory.",
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--base-ref", default="develop")
    args = parser.parse_args()
    try:
        produce(args.root.resolve(), args.out.resolve(), args.event, args.base_ref)
    except MissingReviewedEvidenceError as exc:
        write_json(args.out.resolve() / "handoff-producer-status.json", {
            "status": "awaiting-reviewed-evidence", "reason": str(exc),
            "semantic_validation": "UNKNOWN", "certification": "NOT_ASSERTED",
        })
        print(f"REVIEW REQUIRED: {exc}; collection succeeded but certification remains blocked")
        return 0
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        write_json(args.out.resolve() / "handoff-producer-status.json",
                   {"status": "blocked-invalid-input", "reason": str(exc), "semantic_validation": "UNKNOWN"})
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2
    print("STAGED: reviewed evidence assembled; no certificate or approval asserted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
