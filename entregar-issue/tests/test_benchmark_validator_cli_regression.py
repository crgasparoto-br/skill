"""End-to-end generator/validator regression for false benchmark inference.

The incomplete matrix must fail closed for absent controls; this test proves
that only genuine performance obligations inherit performance gates.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
HEAD = "a" * 40


def run_tool(name: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def generate_and_validate(tmp_path: Path, source: str) -> tuple[dict, subprocess.CompletedProcess[str]]:
    closure = tmp_path / "closure.json"
    matrix = tmp_path / "matrix.json"
    closure.write_text(
        json.dumps({"obligations": [{
            "id": "OBL-001",
            "disposition": "covered",
            "source_text": source,
            "flags": [],
            "requirement_ids": ["R-001"],
        }]}),
        encoding="utf-8",
    )
    generated = run_tool(
        "init_requirement_attack_matrix.py", "--requirement-closure", str(closure),
        "--head-sha", HEAD, "--out", str(matrix),
    )
    assert generated.returncode == 0, generated.stdout + generated.stderr
    data = json.loads(matrix.read_text(encoding="utf-8"))["requirements"][0]
    validated = run_tool(
        "validate_requirement_attack_matrix.py", "--requirement-closure", str(closure),
        "--attack-matrix", str(matrix),
    )
    return data, validated


@pytest.mark.parametrize("source", [
    "As subissues podem referenciar o SHA integrado como baseline de codigo.",
    "O documento de referencia mostra a Golden Screen aprovada, nao um candidato antigo.",
])
def test_documentary_baselines_do_not_trigger_benchmark_in_generator_or_cli(tmp_path: Path, source: str) -> None:
    item, validated = generate_and_validate(tmp_path, source)
    assert "performance_contract" not in item
    assert not any(s["surface"] == "benchmark-path-fidelity" for s in item["risk_surfaces"])
    assert "benchmark-path-fidelity" not in validated.stdout
    assert validated.returncode == 2  # Incomplete controls are still rejected.
    assert "positive control is missing" in validated.stdout


@pytest.mark.parametrize("source", [
    "Benchmark the same productive path before/after optimizing p95 latency.",
    "Baseline of p95 latency, measured before and after the optimization.",
    "The same productive path must be measured at the production entrypoint.",
])
def test_real_benchmark_requires_fidelity_in_generator_and_cli(tmp_path: Path, source: str) -> None:
    item, validated = generate_and_validate(tmp_path, source)
    assert item["performance_contract"]["operations"] == []
    assert any(s["surface"] == "benchmark-path-fidelity" for s in item["risk_surfaces"])
    assert validated.returncode == 2
    assert "benchmark-path-fidelity" in validated.stdout
    assert "performance_contract" in validated.stdout
