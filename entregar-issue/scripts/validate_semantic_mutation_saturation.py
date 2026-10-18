#!/usr/bin/env python3
"""Fail-closed, language-neutral validation of exact-head semantic saturation."""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from risk_inference import requires_semantic_mutation_saturation
from specification import extract_candidates, sha256_file

AXES = ("origin", "binding", "transformation", "control_flow", "consumption", "boundary")
EXPECTED = {"violation": "reject", "benign": "accept", "mutation": "reject"}
SHA = re.compile(r"^[0-9a-f]{40,64}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def check_file(root: Path, relative: object, digest: object, label: str,
               errors: list[str], *, json_proof: bool) -> dict:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        errors.append(f"{label}: invalid relative evidence path")
        return {}
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        errors.append(f"{label}: missing evidence or path escapes workspace")
        return {}
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        errors.append(f"{label}: invalid sha256")
        return {}
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        errors.append(f"{label}: sha256 mismatch")
        return {}
    if not json_proof:
        return {}
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        errors.append(f"{label}: invalid proof JSON")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label}: proof must be JSON object")
        return {}
    return value





def trusted_script_interpreter(command: str) -> str | None:
    """Only known language runtimes may execute a hashed script as argv[1].

    The resolved executable must be the running Python interpreter or an
    installed system runtime, not a same-named wrapper from the workspace.
    """
    resolved = shutil.which(command)
    if not resolved:
        return None
    binary = Path(resolved).resolve()
    if binary == Path(sys.executable).resolve():
        return str(binary)
    permitted = {"sh", "bash", "node", "ruby", "perl", "php", "pwsh"}
    if binary.name not in permitted and not re.fullmatch(r"python3?(?:\\.\\d+)?", binary.name):
        return None
    if not any(binary.is_relative_to(Path(directory))
               for directory in ("/usr/bin", "/usr/local/bin", "/bin")):
        return None
    return str(binary)


def replay(argv: object, entrypoint: object, entrypoint_sha256: object,
           root: Path, source: Path,
           label: str, errors: list[str]) -> subprocess.CompletedProcess | None:
    """Run the actual gate/transformer without a shell in a bounded workspace."""
    if (not isinstance(argv, list) or len(argv) < 2
            or any(not isinstance(a, str) or not a for a in argv)
            or argv.count("{source}") != 1):
        errors.append(f"{label}: replay argv must include executable and {{source}} exactly once")
        return None
    if (not isinstance(entrypoint, str) or not entrypoint
            or Path(entrypoint).is_absolute()):
        errors.append(f"{label}: replay entrypoint must be a workspace-relative file")
        return None
    direct = argv[0] == entrypoint
    interpreted = len(argv) >= 3 and argv[1] == entrypoint and not direct
    interpreter = trusted_script_interpreter(argv[0]) if interpreted else None
    if not direct and not interpreter:
        errors.append(f"{label}: replay must invoke declared gate entrypoint directly or via a trusted interpreter")
        return None
    if not source.is_relative_to(root) or not source.is_file():
        errors.append(f"{label}: replay source escapes workspace or is missing")
        return None
    gate = (root / entrypoint).resolve()
    if not gate.is_relative_to(root) or not gate.is_file():
        errors.append(f"{label}: replay gate entrypoint missing or escapes workspace")
        return None
    if (not isinstance(entrypoint_sha256, str)
            or not DIGEST.fullmatch(entrypoint_sha256)
            or sha256(gate.read_bytes()) != entrypoint_sha256):
        errors.append(f"{label}: replay gate hash missing or stale")
        return None
    expanded = [str(source) if item == "{source}" else item for item in argv]
    # The checked file is executed, never bypassed by /bin/true, -c or a PATH shim.
    entrypoint_index = 0 if direct else 1
    expanded[entrypoint_index] = str(gate)
    if interpreter:
        expanded[0] = interpreter
    try:
        return subprocess.run(
            expanded, cwd=root, capture_output=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        errors.append(f"{label}: replay could not execute: {exc}")
        return None


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_replay(case: dict, proof: dict, root: Path, verdict: str,
                    oracle: dict, label: str, errors: list[str]) -> None:
    source = (root / str(case.get("source_path") or "")).resolve()
    run = case.get("run")
    if not isinstance(run, dict):
        errors.append(f"{label}: executable replay is mandatory")
        return
    executed = replay(run.get("argv"), run.get("entrypoint"),
                      run.get("entrypoint_sha256"), root, source, label, errors)
    if executed is None:
        return
    expected_codes = oracle.get(verdict + "_exit_codes", [])
    if executed.returncode not in expected_codes:
        errors.append(f"{label}: observed gate behavior disagrees with {verdict}")
    if (proof.get("exit_code") != executed.returncode
            or proof.get("stdout_sha256") != sha256(executed.stdout)
            or proof.get("stderr_sha256") != sha256(executed.stderr)):
        errors.append(f"{label}: proof transcript does not match actual gate replay")


def validate_case(case: object, ci: int, tag: str, variants: dict,
                  root: Path, head: str, ids: set[str], oracle: dict,
                  errors: list[str]) -> tuple[str, dict] | None:
    label = f"{tag} case {ci}"
    if not isinstance(case, dict):
        errors.append(f"{label}: invalid case")
        return None
    cid = case.get("id")
    if not isinstance(cid, str) or not cid or cid in ids:
        errors.append(f"{label}: missing or duplicated ID")
        return None
    ids.add(cid)
    kind = case.get("kind")
    verdict = EXPECTED.get(kind) if isinstance(kind, str) else None
    if verdict is None or case.get("expected") != verdict or case.get("observed") != verdict:
        errors.append(f"{label}: mutant survivor, false positive or incorrect oracle")
    if case.get("status") != "passed" or case.get("head_sha") != head:
        errors.append(f"{label}: not executed on exact head")
    if kind == "mutation" and not str(case.get("mutation_id") or "").strip():
        errors.append(f"{label}: missing mutation ID")
    procedure = case.get("procedure")
    if not isinstance(procedure, str) or len(procedure.strip()) < 12:
        errors.append(f"{label}: non-reproducible procedure")
    axes = case.get("axes")
    if not isinstance(axes, dict) or set(axes) != set(AXES):
        errors.append(f"{label}: incomplete axis values")
        return None
    if any(axes[a] not in variants[a] for a in AXES):
        errors.append(f"{label}: undeclared axis value")
        return None
    proof = check_file(root, case.get("proof_path"), case.get("proof_sha256"),
                       label, errors, json_proof=True)
    if (proof.get("case_id") != cid or proof.get("head_sha") != head
            or proof.get("observed") != case.get("observed")
            or proof.get("procedure") != procedure):
        errors.append(f"{label}: proof contradicts recorded result")
    check_file(root, case.get("source_path"), case.get("source_sha256"),
               label, errors, json_proof=False)
    validate_replay(case, proof, root, verdict, oracle, label, errors)
    return kind, axes


def validate_transform_contrast(transform: dict, root: Path, source: Path,
                                tag: str, errors: list[str]) -> None:
    # A constant-output or source-ignoring transformer is not metamorphic evidence.
    contrast_path = transform.get("contrast_source_path")
    contrast_digest = transform.get("contrast_source_sha256")
    check_file(root, contrast_path, contrast_digest, tag + " contrast",
               errors, json_proof=False)
    if not isinstance(contrast_path, str) or not contrast_path or Path(contrast_path).is_absolute():
        return
    contrast = (root / contrast_path).resolve()
    if (not contrast.is_relative_to(root) or not contrast.is_file()
            or contrast == source or contrast.read_bytes() == source.read_bytes()):
        errors.append(f"{tag}: metamorphic contrast must be a distinct source")
        return
    original_bytes, contrast_bytes = source.read_bytes(), contrast.read_bytes()
    if len(original_bytes) != len(contrast_bytes):
        errors.append(f"{tag}: metamorphic contrast must preserve byte length to exclude size-only transforms")
        return
    # ABA on the same inode/path, stable size and mtime. A metadata-only,
    # time-dependent or path-dependent transform cannot establish this proof.
    stable_ns = 1_700_000_000_000_000_000
    with tempfile.TemporaryDirectory(prefix=".semantic-probe-", dir=source.parent) as work:
        probe = Path(work) / source.name
        outcomes = []
        for step, payload in (("original", original_bytes),
                              ("contrast", contrast_bytes),
                              ("restored", original_bytes)):
            probe.write_bytes(payload)
            os.utime(probe, ns=(stable_ns, stable_ns))
            outcomes.append(replay(transform.get("argv"), transform.get("entrypoint"),
                                   transform.get("entrypoint_sha256"), root, probe,
                                   tag + " " + step + " probe", errors))
    if (any(result is None for result in outcomes)
            or any(result.returncode != 0 for result in outcomes if result is not None)):
        errors.append(f"{tag}: metamorphic contrast could not be transformed")
    elif (outcomes[0].stdout != outcomes[2].stdout
          or outcomes[0].stderr != outcomes[2].stderr
          or outcomes[0].returncode != outcomes[2].returncode):
        errors.append(f"{tag}: metamorphic transform depends on changing metadata or non-deterministic state")
    elif outcomes[0].stdout == outcomes[1].stdout:
        errors.append(f"{tag}: metamorphic transform does not depend on source bytes")



def validate_metamorphic_pair(pair: object, tag: str, by_id: dict,
                              root: Path, errors: list[str]) -> None:
    if not isinstance(pair, dict):
        errors.append(f"{tag}: metamorphic pair needs explicit transformation contract")
        return
    left, right = by_id.get(pair.get("left")), by_id.get(pair.get("right"))
    if not left or not right or left is right:
        errors.append(f"{tag}: invalid metamorphic pair")
        return
    if (left.get("axes") == right.get("axes")
            or any(c.get("observed") != "reject"
                   or c.get("kind") not in ("violation", "mutation")
                   for c in (left, right))):
        errors.append(f"{tag}: metamorphic pair not discriminating")
    invariant = pair.get("invariant")
    if (not isinstance(invariant, str) or len(invariant.strip()) < 25
            or not isinstance(pair.get("relation_id"), str)
            or not pair["relation_id"].strip()):
        errors.append(f"{tag}: missing semantic invariant or relation identity")
    transform = pair.get("transform")
    if not isinstance(transform, dict):
        errors.append(f"{tag}: metamorphic transformation replay required")
        return
    source = (root / str(left.get("source_path") or "")).resolve()
    target = (root / str(right.get("source_path") or "")).resolve()
    if (not source.is_relative_to(root) or not target.is_relative_to(root)
            or not source.is_file() or not target.is_file()
            or source == target):
        errors.append(f"{tag}: invalid metamorphic source and target")
        return
    outcome = replay(transform.get("argv"), transform.get("entrypoint"),
                     transform.get("entrypoint_sha256"), root, source,
                     tag + " metamorphic", errors)
    if outcome is None:
        return
    if outcome.returncode != 0 or outcome.stdout != target.read_bytes():
        errors.append(f"{tag}: transformed bytes do not reproduce the sibling")

    validate_transform_contrast(transform, root, source, tag, errors)

def validate_comparisons(tag: str, rule: dict, variants: dict, covered: set,
                         kinds: set, by_id: dict, root: Path, errors: list[str]) -> None:
    for kind in EXPECTED:
        if kind not in kinds:
            errors.append(f"{tag}: missing {kind} control")
    for a, b in itertools.combinations(AXES, 2):
        for va, vb in itertools.product(variants[a], variants[b]):
            if (a, va, b, vb) not in covered:
                errors.append(f"{tag}: uncovered pairwise {a}={va} x {b}={vb}")
    pairs = rule.get("metamorphic_pairs")
    if not isinstance(pairs, list) or not pairs:
        errors.append(f"{tag}: metamorphic pairs missing")
        return
    for pair in pairs:
        validate_metamorphic_pair(pair, tag, by_id, root, errors)


def validate_rule(rule: object, ri: int, required: set[tuple[str, str, str]],
                  seen: set[tuple[str, str, str]], ids: set[str], root: Path,
                  head: str, errors: list[str]) -> None:
    tag = f"rule {ri}"
    if not isinstance(rule, dict):
        errors.append(f"{tag}: invalid rule")
        return
    identity = tuple(str(rule.get(k) or "") for k in ("requirement_id", "risk_family", "surface"))
    if identity in seen or identity not in required:
        errors.append(f"{tag}: duplicate or undeclared semantic surface")
    seen.add(identity)
    if rule.get("status") != "covered":
        errors.append(f"{tag}: required surface not covered")
    oracle = rule.get("oracle")
    if (not isinstance(oracle, dict)
            or any(not isinstance(oracle.get(k), list) or not oracle[k]
                   or any(type(n) is not int for n in oracle[k])
                   for k in ("accept_exit_codes", "reject_exit_codes"))
            or set(oracle["accept_exit_codes"]) & set(oracle["reject_exit_codes"])):
        errors.append(f"{tag}: gate oracle must distinguish accept and reject exit codes")
        return
    variants = rule.get("axis_variants")
    if not isinstance(variants, dict) or set(variants) != set(AXES):
        errors.append(f"{tag}: missing six axis variants")
        return
    if any(not isinstance(variants[a], list) or not variants[a]
           or any(not isinstance(v, str) or not v.strip() for v in variants[a])
           or len(set(variants[a])) != len(variants[a]) for a in AXES):
        errors.append(f"{tag}: invalid axis variants")
        return
    if all(len(variants[a]) == 1 for a in AXES):
        errors.append(f"{tag}: missing metamorphic variation")
    cases = rule.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append(f"{tag}: cases missing")
        return
    covered = set()
    kinds = set()
    by_id = {}
    for ci, case in enumerate(cases):
        result = validate_case(case, ci, tag, variants, root, head, ids, oracle, errors)
        if result is None:
            continue
        kind, axes = result
        kinds.add(kind)
        by_id[case["id"]] = case
        for a, b in itertools.combinations(AXES, 2):
            covered.add((a, axes[a], b, axes[b]))
    validate_comparisons(tag, rule, variants, covered, kinds, by_id, root, errors)


def validate_closure_obligations(closure: dict, candidates: list[dict],
                                 errors: list[str]) -> None:
    expected = {c["candidate_key"]: c for c in candidates}
    actual: dict[str, dict] = {}
    obligations = closure.get("obligations")
    if not isinstance(obligations, list):
        errors.append("canonical closure must have an obligation list")
        return
    for obligation in obligations:
        if not isinstance(obligation, dict):
            errors.append("canonical closure obligation is invalid")
            continue
        key = obligation.get("candidate_key")
        if not isinstance(key, str) or key in actual:
            errors.append("canonical closure has invalid or duplicate candidate key")
            continue
        actual[key] = obligation
    if expected.keys() != actual.keys():
        errors.append("canonical closure omitted or invented specification obligations")
    for key in expected.keys() & actual.keys():
        for field in ("source_id", "source_sha256", "source_line", "source_text", "flags"):
            if expected[key][field] != actual[key].get(field):
                errors.append(f"canonical closure changed source evidence: {key} {field}")
        obligation = actual[key]
        if obligation.get("disposition") != "not-applicable" and not obligation.get("requirement_ids"):
            errors.append(f"canonical obligation has no bound requirement: {key}")



def validate_canonical_closure(closure: dict, snapshot_path: Path,
                               errors: list[str]) -> None:
    """Re-derive obligations from the caller's canonical specification, not the matrix."""
    if closure.get("schema_version") != 3:
        errors.append("canonical requirement closure schema_version must be 3")
        return
    marker = closure.get("specification_snapshot")
    if (not isinstance(marker, dict) or not snapshot_path.is_file()
            or marker.get("sha256") != sha256_file(snapshot_path)):
        errors.append("canonical specification snapshot is missing or hash-divergent")
        return
    source_errors: list[str] = []
    snapshot, _, candidates = extract_candidates(snapshot_path, source_errors)
    errors.extend(source_errors)
    if source_errors or not candidates:
        errors.append("canonical specification has no verifiable candidates")
        return
    if closure.get("primary_issue_source_id") != snapshot.get("primary_source_id"):
        errors.append("canonical primary specification source diverges")
    validate_closure_obligations(closure, candidates, errors)

def validate(manifest: dict, matrix: dict, closure: dict, root: Path,
             head: str, specification_snapshot: Path) -> list[str]:
    errors: list[str] = []
    validate_canonical_closure(closure, specification_snapshot, errors)
    if not SHA.fullmatch(head):
        errors.append("invalid current head SHA")
    if manifest.get("schema_version") != 1 or manifest.get("head_sha") != head:
        errors.append("manifest schema or head is stale")
    if matrix.get("head_sha") != head:
        errors.append("attack matrix head is stale")
    required = set()
    for req in matrix.get("requirements", []):
        if not isinstance(req, dict):
            errors.append("invalid matrix requirement")
            continue
        for surface in req.get("risk_surfaces", []):
            if isinstance(surface, dict) and surface.get("semantic_saturation_required") is True:
                required.add((str(req.get("requirement_id") or ""),
                              str(surface.get("risk_family") or ""),
                              str(surface.get("surface") or "")))
    canonical: set[tuple[str, str, str]] = set()
    obligations = closure.get("obligations")
    if not isinstance(obligations, list):
        errors.append("canonical requirement closure has no obligations")
    else:
        for obligation in obligations:
            if not isinstance(obligation, dict):
                errors.append("invalid canonical closure obligation")
                continue
            if obligation.get("disposition") == "not-applicable":
                continue
            if requires_semantic_mutation_saturation([str(obligation.get("source_text") or "")]):
                for rid in obligation.get("requirement_ids") or []:
                    canonical.add((str(rid), "structural-contract", "semantic-mutation-saturation"))
    if canonical - required:
        errors.append(f"canonical semantic surfaces omitted or disabled: {sorted(canonical - required)}")
    if not required:
        errors.append("no semantic saturation surfaces declared in attack matrix")
    rules = manifest.get("rules")
    if not isinstance(rules, list) or not rules:
        return [*errors, "missing semantic saturation evidence rules"]
    seen = set()
    ids = set()
    for ri, rule in enumerate(rules):
        validate_rule(rule, ri, required, seen, ids, root, head, errors)
    if required - seen:
        errors.append(f"omitted semantic surfaces: {sorted(required - seen)}")
    return errors


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--attack-matrix", required=True)
    p.add_argument("--requirement-closure", required=True)
    p.add_argument("--specification-snapshot", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--root", default=".")
    a = p.parse_args()
    try:
        errors = validate(load(Path(a.manifest)), load(Path(a.attack_matrix)),
                          load(Path(a.requirement_closure)), Path(a.root).resolve(),
                          a.head_sha, Path(a.specification_snapshot).resolve())
    except (OSError, ValueError, TypeError) as exc:
        errors = [f"missing or invalid evidence: {exc}"]
    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print("READY: exact-head semantic mutation, benign controls and pairwise coverage verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
