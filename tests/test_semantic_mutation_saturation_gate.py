"""Behavioral regressions for fail-closed semantic mutation saturation."""
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "entregar-issue/scripts/validate_semantic_mutation_saturation.py"
HEAD = "a" * 40
AXES = ("origin", "binding", "transformation", "control_flow", "consumption", "boundary")


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, sort_keys=True).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def fixture(tmp_path):
    gate = tmp_path / "gate.py"
    gate.write_text("import sys\nfrom pathlib import Path\n"
                    "source = Path(sys.argv[1]).read_text()\n"
                    "sys.exit(0 if 'safe' in source else 2)\n", encoding="utf-8")
    transform = tmp_path / "transform.py"
    transform.write_text("import sys\nfrom pathlib import Path\n"
                         "source = Path(sys.argv[1]).read_text()\n"
                         "sys.stdout.write(source.replace('direct', 'alias'))\n", encoding="utf-8")
    variants = {axis: ["default"] for axis in AXES}
    variants["transformation"] = ["direct", "alias"]
    cases = []
    for cid, kind, transformation in (
        ("direct", "violation", "direct"),
        ("alias", "violation", "alias"),
        ("safe", "benign", "direct"),
        ("mutant", "mutation", "alias"),
    ):
        observed = "accept" if kind == "benign" else "reject"
        procedure = f"Execute isolated {cid} fixture through the gate"
        proof = {
            "case_id": cid, "head_sha": HEAD,
            "observed": observed, "procedure": procedure,
            "exit_code": 0 if kind == "benign" else 2,
            "stdout_sha256": hashlib.sha256(b"").hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
        }
        src = tmp_path / f"probes/{cid}.txt"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(f"independent {cid} source fixture", encoding="utf-8")
        case = {
            "id": cid, "kind": kind, "expected": observed, "observed": observed,
            "head_sha": HEAD, "status": "passed", "procedure": procedure,
            "run": {"entrypoint": "gate.py",
                    "entrypoint_sha256": hashlib.sha256(gate.read_bytes()).hexdigest(),
                    "argv": [sys.executable, "gate.py", "{source}"]},
            "axes": {**dict.fromkeys(AXES, "default"), "transformation": transformation},
            "proof_path": f"proofs/{cid}.json",
            "proof_sha256": write(tmp_path / f"proofs/{cid}.json", proof),
            "source_path": f"probes/{cid}.txt",
            "source_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
        }
        if kind == "mutation":
            case["mutation_id"] = "M-001"
        cases.append(case)
    manifest = {
        "schema_version": 1, "head_sha": HEAD,
        "rules": [{
            "requirement_id": "R-1", "risk_family": "structural-contract",
            "surface": "semantic-mutation-saturation", "status": "covered",
            "oracle": {"accept_exit_codes": [0], "reject_exit_codes": [2]},
            "axis_variants": variants, "cases": cases,
            "metamorphic_pairs": [{
                "left": "direct", "right": "alias",
                "relation_id": "transparent-alias-rewrite",
                "invariant": "Renaming direct to alias does not change rule violation",
                "transform": {
                    "entrypoint": "transform.py",
                    "entrypoint_sha256": hashlib.sha256(transform.read_bytes()).hexdigest(),
                    "argv": [sys.executable, "transform.py", "{source}"],
                },
            }],
        }],
    }
    matrix = {
        "head_sha": HEAD,
        "requirements": [{
            "requirement_id": "R-1", "risk_surfaces": [{
                "risk_family": "structural-contract", "surface": "static-verifier",
                "semantic_saturation_required": True,
            }],
        }],
    }
    return manifest, matrix


def run(tmp_path, manifest, matrix, head=HEAD):
    manifest_path = tmp_path / "manifest.json"
    matrix_path = tmp_path / "matrix.json"
    write(manifest_path, manifest)
    write(matrix_path, matrix)
    write(tmp_path / "closure.json", {"obligations": [{"id": "O-1",
        "requirement_ids": ["R-1"], "source_text": "Static verifier must reject invalid origin",
        "disposition": "covered"}]})
    return subprocess.run([
        sys.executable, str(SCRIPT), "--manifest", str(manifest_path),
        "--attack-matrix", str(matrix_path),
        "--requirement-closure", str(tmp_path / "closure.json"), "--head-sha", head,
        "--root", str(tmp_path),
    ], capture_output=True, text=True, check=False)


def test_valid_language_neutral_gate(tmp_path):
    manifest, matrix = fixture(tmp_path)
    result = run(tmp_path, manifest, matrix)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_manifest_fails_closed(tmp_path):
    manifest, matrix = fixture(tmp_path)
    assert run(tmp_path, manifest, matrix).returncode == 0
    (tmp_path / "manifest.json").unlink()
    result = subprocess.run([
        sys.executable, str(SCRIPT), "--manifest", str(tmp_path / "manifest.json"),
        "--attack-matrix", str(tmp_path / "matrix.json"),
        "--requirement-closure", str(tmp_path / "closure.json"),
        "--head-sha", HEAD, "--root", str(tmp_path),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 2


def test_mismatch_head_and_proof_tampering(tmp_path):
    manifest, matrix = fixture(tmp_path)
    assert run(tmp_path, manifest, matrix, head="b" * 40).returncode == 2
    (tmp_path / "proofs/direct.json").write_text("tampered", encoding="utf-8")
    assert "sha256 mismatch" in run(tmp_path, manifest, matrix).stdout


def test_mutant_survival_and_false_positive_block(tmp_path):
    manifest, matrix = fixture(tmp_path)
    manifest["rules"][0]["cases"][3]["observed"] = "accept"
    assert "survivor" in run(tmp_path, manifest, matrix).stdout
    clean, matrix = fixture(tmp_path)
    clean["rules"][0]["cases"][2]["observed"] = "reject"
    assert "false positive" in run(tmp_path, clean, matrix).stdout


def test_missing_pairwise_and_metamorphic_blocks(tmp_path):
    manifest, matrix = fixture(tmp_path)
    manifest["rules"][0]["cases"][1]["axes"]["transformation"] = "direct"
    manifest["rules"][0]["cases"][3]["axes"]["transformation"] = "direct"
    output = run(tmp_path, manifest, matrix).stdout
    assert "uncovered pairwise" in output
    assert "metamorphic pair not discriminating" in output


def test_unexecuted_or_omitted_surface_blocks(tmp_path):
    manifest, matrix = fixture(tmp_path)
    manifest["rules"][0]["status"] = "not-executed"
    assert "not covered" in run(tmp_path, manifest, matrix).stdout
    manifest, matrix = fixture(tmp_path)
    extra = copy.deepcopy(matrix["requirements"][0]["risk_surfaces"][0])
    extra["surface"] = "another-surface"
    matrix["requirements"][0]["risk_surfaces"].append(extra)
    assert "omitted semantic surfaces" in run(tmp_path, manifest, matrix).stdout


def test_malformed_evidence_and_path_traversal_block(tmp_path):
    manifest, matrix = fixture(tmp_path)
    manifest["rules"][0]["cases"][0]["proof_path"] = "../external.json"
    assert "escapes workspace" in run(tmp_path, manifest, matrix).stdout
    manifest, matrix = fixture(tmp_path)
    manifest["rules"][0]["cases"][0]["proof_sha256"] = "0" * 64
    assert "sha256 mismatch" in run(tmp_path, manifest, matrix).stdout


def test_registry_activates_semantic_gate_for_parser_and_static_checker():
    sys.path.insert(0, str(ROOT / "entregar-issue/scripts"))
    from plan_execution import infer_signals, required_gates_from_registry

    registry = json.loads((ROOT / "entregar-issue/contracts/gate-registry.json").read_text(encoding="utf-8"))
    for text in ("parser of untrusted input", "static verifier checks source provenance"):
        signals = infer_signals(set(), [], text)
        required = required_gates_from_registry(
            registry, profile="standard", classification={"behavioral_change": True},
            signals=signals,
        )
        assert "semantic-mutation-saturation" in required
    ordinary = required_gates_from_registry(
        registry, profile="standard", classification={"behavioral_change": True},
        signals=set(),
    )
    assert "semantic-mutation-saturation" not in ordinary


def test_fake_successful_transcript_cannot_replace_replay(tmp_path):
    manifest, matrix = fixture(tmp_path)
    (tmp_path / "gate.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    output = run(tmp_path, manifest, matrix)
    assert output.returncode == 2
    assert "actual gate replay" in output.stdout or "disagrees" in output.stdout


def test_metamorphic_transform_must_reproduce_real_source(tmp_path):
    manifest, matrix = fixture(tmp_path)
    (tmp_path / "transform.py").write_text("print('unrelated')\n", encoding="utf-8")
    output = run(tmp_path, manifest, matrix)
    assert output.returncode == 2
    assert "transformed bytes do not reproduce" in output.stdout


def test_oracle_cannot_accept_and_reject_same_exit_code(tmp_path):
    manifest, matrix = fixture(tmp_path)
    manifest["rules"][0]["oracle"]["reject_exit_codes"] = [0]
    assert "must distinguish" in run(tmp_path, manifest, matrix).stdout


def test_canonical_parser_surface_cannot_be_disabled(tmp_path):
    manifest, matrix = fixture(tmp_path)
    matrix["requirements"][0]["risk_surfaces"][0]["semantic_saturation_required"] = False
    result = run(tmp_path, manifest, matrix)
    assert result.returncode == 2
    assert "canonical semantic surfaces omitted or disabled" in result.stdout
