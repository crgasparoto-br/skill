#!/usr/bin/env python3
"""Stage reviewed semantic evidence for the existing GitHub Actions handoff gate.

The test index is factual, not a semantic oracle. This producer never changes a
pending obligation to covered or a control to passed without a reviewed input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

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


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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
    tests = {entry["id"]: entry["status"] for entry in index["tests"]}
    if not tests or index.get("requirement_mapping") != "UNKNOWN":
        raise ValueError("test index must be factual and unclassified")
    return tests, index


def load_reviewed_manifest(root: Path, source: Path, event: Path, target: dict) -> tuple[dict, str, list[str]]:
    if not source.is_dir() or source.is_symlink():
        raise ValueError(f"reviewed semantic evidence not supplied under {source.relative_to(root)}")
    manifest = read_json(source / "manifest.json")
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported reviewed evidence manifest")
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
    covered = {rid for item in closure["obligations"] if item["disposition"] == "covered"
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


def produce(root: Path, out: Path, event: Path, base_ref: str) -> None:
    from prepare_actions_handoff import check_checkout, read_event

    repository, pr, issue, head, base = read_event(event, base_ref)
    check_checkout(root, head)
    identity = read_json(out / "handoff-preflight.json").get("identity") or {}
    expected = {"repository": repository, "issue_number": issue,
                "pull_request_number": pr, "material_head_sha": head, "base_sha": base}
    if any(identity.get(key) != val for key, val in expected.items()):
        raise ValueError("preflight identity differs from the exact PR material")
    tests, _ = collect_exact_tests(out, head)
    audit = out / ".audit" / "entregar-issue"
    starter = read_json(audit / "requirement-closure.json")
    write_json(out / "semantic-evidence-candidates.json", {
        "schema_version": 1, "subject_sha": head,
        "obligations": [{"id": entry["id"], "candidate_key": entry["candidate_key"],
                         "source_text": entry["source_text"]} for entry in starter["obligations"]],
        "test_candidates": len(tests), "mapping": "UNKNOWN",
    })
    source = root / ".github" / "handoff-evidence" / f"issue-{issue}"
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
    validate_test_bindings(manifest.get("test_bindings"), closure, tests)
    staged = {name: bind_identity(verified_source(root, source, name, hashes), head, start)
              for name in sorted(set(hashes) - {"reviewed-closure.json"})}
    write_json(audit / "requirement-closure.json", closure)
    for name, report in staged.items():
        write_json(audit / name, report)
    if touched_code:
        command = [sys.executable, str(Path(__file__).with_name("check_code_growth.py")),
                   "--repo", str(root), "--base-sha", start, "--head-sha", head,
                   "--out", str(audit / "code-growth.json")]
        subprocess.run(command, check=True)
    inputs = {"subject_sha": head, "work_item_start_sha": start, "base_ref": base_ref,
              "head_ref": manifest["head_ref"], "evidence_profile": manifest["evidence_profile"],
              "audit_history": manifest["audit_history"]}
    if "remediation_mode" in manifest:
        inputs["remediation_mode"] = manifest["remediation_mode"]
    write_json(out / "certification-inputs.json", inputs)
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
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        write_json(args.out.resolve() / "handoff-producer-status.json",
                   {"status": "blocked", "reason": str(exc), "semantic_validation": "UNKNOWN"})
        print(f"BLOCK: {exc}", file=sys.stderr)
        return 2
    print("STAGED: reviewed evidence assembled; no certificate or approval asserted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
