from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from risk_inference import (  # noqa: E402 - local scripts dir is initialized above
    derive_families_from_text,
    derive_surfaces,
    requires_benchmark_path_fidelity,
)

from validate_requirement_attack_matrix import required_performance_surfaces  # noqa: E402

NON_PERFORMANCE = [
    "As subissues podem referenciar o SHA integrado como baseline de codigo.",
    "O documento mostra a Golden Screen aprovada, nao um candidato antigo.",
    "Check the candidate SHA before and after the merge.",
    "Keep the Git baseline aligned with develop.",
]

REAL_PERFORMANCE = [
    "Benchmark the same productive path before/after optimizing p95 latency.",
    "Baseline of p95 latency, measured before and after the optimization.",
    "O harness deve exercitar o mesmo caminho produtivo usado pela aplicacao.",
]


def test_git_baseline_and_visual_candidate_do_not_imply_benchmark() -> None:
    for source in NON_PERFORMANCE:
        assert not requires_benchmark_path_fidelity([source]), source
        assert not required_performance_surfaces({"source_texts": [source]}), source
        assert not any(
            entry["surface"] == "benchmark-path-fidelity"
            for entry in derive_surfaces([source])
        ), source


def test_real_benchmarks_still_require_productive_path_fidelity() -> None:
    for source in REAL_PERFORMANCE:
        assert requires_benchmark_path_fidelity([source]), source
        assert ("structural-contract", "benchmark-path-fidelity") in required_performance_surfaces(
            {"source_texts": [source]}
        ), source
        assert "structural-contract" in derive_families_from_text(source), source
        assert any(
            entry["surface"] == "benchmark-path-fidelity"
            for entry in derive_surfaces([source])
        ), source


def test_generator_and_validator_do_not_invent_performance_for_git_baseline() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        closure = root / "closure.json"
        closure.write_text(json.dumps({
            "obligations": [
                {
                    "id": f"OBL-{i:03d}",
                    "disposition": "covered",
                    "source_text": source,
                    "flags": [],
                    "requirement_ids": [f"REQ-{i:03d}"],
                }
                for i, source in enumerate(NON_PERFORMANCE, start=1)
            ]
        }), encoding="utf-8")
        output = root / "attack-matrix.json"
        run = subprocess.run([
            sys.executable, str(SCRIPTS / "init_requirement_attack_matrix.py"),
            "--requirement-closure", str(closure),
            "--head-sha", "a" * 40,
            "--out", str(output),
        ], check=False, capture_output=True, text=True)
        assert run.returncode == 0, run.stdout + run.stderr
        matrix = json.loads(output.read_text(encoding="utf-8"))
        assert all(
            "performance_contract" not in item
            and all(surface["surface"] != "benchmark-path-fidelity" for surface in item["risk_surfaces"])
            for item in matrix["requirements"]
        )
        assert all(not required_performance_surfaces(item) for item in matrix["requirements"])

