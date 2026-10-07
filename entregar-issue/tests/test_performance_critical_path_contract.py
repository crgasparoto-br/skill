import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_execution import classify_changes, infer_signals, required_gates_from_registry  # noqa: E402 - sys.path ajustado acima antes do import local


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_skill_activates_performance_critical_path_gate():
    skill = read("SKILL.md")
    reference = read("references/performance-critical-path-gate.md")
    workflow = read("references/implementation-workflow.md")
    registry = json.loads(read("contracts/gate-registry.json"))
    gates = {item["id"]: item for item in registry["gates"]}

    assert "performance-critical-path-gate.md" in skill
    assert "stage-attribution-completeness" in skill
    assert "critical-path-necessity" in skill
    assert "benchmark-path-fidelity" in skill
    assert "performance_contract" in skill
    assert "PERF-STAGE-ATTR-001" in skill
    assert "PERF-CRITICAL-WORK-001" in skill
    assert "PERF-BENCH-PATH-001" in skill
    assert "todas" in reference and "operacoes" in reference
    assert "zero invocacoes" in reference
    assert "production_entrypoint" in reference
    assert "omitted_operation_ids" in reference
    assert "metrica parcial" in workflow
    assert gates["performance-critical-path"]["controls"] == [
        "PERF-STAGE-ATTR-001",
        "PERF-CRITICAL-WORK-001",
        "PERF-BENCH-PATH-001",
    ]


def test_planner_infers_performance_signal_and_registry_gate_from_requirements():
    signals = infer_signals(
        set(),
        ["server/question.ts"],
        "Reduzir latência p90 com benchmark before/after e instrumentação db_ms sem remover trabalho obrigatório.",
    )
    assert "performance" in signals
    classification = classify_changes(["server/question.ts"], signals)
    registry = json.loads(read("contracts/gate-registry.json"))
    gates = required_gates_from_registry(
        registry,
        profile="standard",
        classification=classification,
        signals=signals,
    )
    assert "performance-critical-path" in gates


def test_performance_gate_rejects_benchmark_only_reasoning():
    reference = read("references/performance-critical-path-gate.md")
    adversarial = read("references/controller-adversarial-evidence.md")
    assert "Melhora quantitativa nao substitui" in reference
    assert "Tempo agregado menor nao comprova ausencia de trabalho" in adversarial
    assert "Run exact-head control" in adversarial
    assert "Observed pass" in adversarial
