import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tenant_scoped_performance_gate_rejects_global_denominator():
    evidence = (ROOT / "references" / "performance-critical-path-gate.md").read_text(encoding="utf-8")
    assert "total global" in evidence
    assert "ruido deliberado fora do escopo" in evidence
    assert "consulta estruturalmente identica" in evidence


def test_gate_registry_is_machine_readable_and_has_unique_ids():
    registry = json.loads((ROOT / "contracts" / "gate-registry.json").read_text())
    ids = [item["id"] for item in registry["gates"]]
    assert len(ids) == len(set(ids))
    assert "input-parser-controls" in ids
    assert "negative-controls" in ids
    assert registry["governance"]["runtime_source_of_truth"] == "contracts/gate-registry.json"


def test_efficiency_report_uses_runtime_metrics(tmp_path):
    context = tmp_path / "context.json"
    subprocess.run([
        sys.executable, str(ROOT / "scripts/controller_cli.py"), "init-context",
        "--repository", "owner/repo", "--repository-path", str(tmp_path),
        "--issue", "1", "--base-ref", "main", "--branch", "issue-1", "--out", str(context),
    ], check=True)
    subprocess.run([
        sys.executable, str(ROOT / "scripts/controller_cli.py"), "refresh-context",
        "--context", str(context),
        "--metric", "planning_runs=1", "--metric", "focused_checks=3",
        "--metric", "full_suites=1", "--metric", "material_commits=1",
        "--metric", "handoff_commits=1", "--metric", "remote_collections=1",
    ], check=True)
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(["src/service.py"]))
    plan = tmp_path / "plan.json"
    subprocess.run([
        sys.executable, str(ROOT / "scripts/plan_execution.py"),
        "--controller-context", str(context), "--changed-files", str(changed), "--out", str(plan),
    ], check=True)
    report = tmp_path / "efficiency.json"
    subprocess.run([
        sys.executable, str(ROOT / "scripts/report_controller_efficiency.py"),
        "--context", str(context), "--plan", str(plan), "--out", str(report),
    ], check=True)
    payload = json.loads(report.read_text())
    assert payload["kpis"]["planning_amplification"] == 1.0
    assert payload["kpis"]["publication_amplification"] == 2.0
    assert payload["plan_counts"]["stages"] >= 1
