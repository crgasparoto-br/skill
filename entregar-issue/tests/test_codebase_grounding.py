from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_codebase_grounding.py"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def write(repo: Path, path: str, text: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


@pytest.fixture()
def candidate(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo, "src/money.py", "def format_money(value):\n    return f'{value:.2f}'\n")
    write(repo, "src/legacy_report.py", "def old_total(rows):\n    return sum(rows)\n")
    write(repo, "requirements.txt", "requests>=2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "src/report.py", "import requests\nfrom money import format_money\n\n\ndef total(rows):\n    return format_money(sum(rows))\n")
    write(repo, "tests/test_report.py", "from report import total\n")
    git(repo, "rm", "-q", "src/legacy_report.py")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "candidate")
    head = git(repo, "rev-parse", "HEAD")
    check = {"command": "pytest tests/test_report.py", "exit_code": 0}
    report = {
        "schema_version": 1,
        "subject_sha": head,
        "base_sha": base,
        "creations": [{
            "path": "src/report.py",
            "kind": "file",
            "search": {
                "queries": ["rg -n 'def .*total' src", "rg -n report src"],
                "scope": "src/",
                "candidates": [{"path": "src/money.py", "reason_not_reused": "formata valor; nao agrega linhas"}],
            },
            "decision": "create",
            "justification": "substitui legacy_report.py usando o formatador existente",
        }],
        "references": [
            {"symbol": "format_money", "kind": "local", "used_in": "src/report.py",
             "defined_at": {"path": "src/money.py", "line": 1}, "verified_by": check},
            {"symbol": "requests", "kind": "dependency", "used_in": "src/report.py",
             "manifest": {"path": "requirements.txt", "name": "requests"}, "verified_by": check},
        ],
        "replacements": [{"old_path": "src/legacy_report.py", "old_symbol": "old_total", "disposition": "removed"}],
    }
    return {"repo": repo, "base": base, "head": head, "report": report, "tmp": tmp_path}


def run(candidate: dict, report: dict | None = None, head: str | None = None):
    path = candidate["tmp"] / "codebase-grounding.json"
    path.write_text(json.dumps(candidate["report"] if report is None else report), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(candidate["repo"]), "--report", str(path),
         "--base-sha", candidate["base"], "--head-sha", head or candidate["head"]],
        capture_output=True, text=True,
    )


def mutated(candidate: dict, change) -> dict:
    report = copy.deepcopy(candidate["report"])
    change(report)
    return report


def test_grounded_candidate_is_ready(candidate):
    result = run(candidate)
    assert result.returncode == 0, result.stdout
    assert result.stdout.startswith("READY")


def test_added_code_file_without_search_record_blocks(candidate):
    result = run(candidate, mutated(candidate, lambda r: r["creations"].clear()))
    assert result.returncode == 2
    assert "added code file without search record: src/report.py" in result.stdout
    assert "tests/test_report.py" not in result.stdout


def test_invented_candidate_blocks(candidate):
    def change(report):
        report["creations"][0]["search"]["candidates"][0]["path"] = "src/totals.py"
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 2
    assert "candidate does not exist at head: src/totals.py" in result.stdout


def test_hallucinated_local_symbol_blocks(candidate):
    def change(report):
        report["references"][0]["defined_at"]["line"] = 2
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 2
    assert "format_money is not defined at src/money.py:2" in result.stdout


def test_symbol_not_used_by_declared_consumer_blocks(candidate):
    def change(report):
        report["references"][0]["used_in"] = "requirements.txt"
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 2
    assert "requirements.txt does not reference format_money" in result.stdout


def test_undeclared_dependency_blocks(candidate):
    def change(report):
        report["references"][1]["manifest"]["name"] = "httpx"
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 2
    assert "httpx is not declared in requirements.txt" in result.stdout


def test_name_prefix_is_not_proof_of_existence(candidate):
    def dependency(report):
        report["references"][1]["manifest"]["name"] = "request"
    def symbol(report):
        report["references"][0]["symbol"] = "format_mone"
    for change in (dependency, symbol):
        assert run(candidate, mutated(candidate, change)).returncode == 2


def test_replacement_declared_removed_but_present_blocks(candidate):
    def change(report):
        report["replacements"][0] = {"old_path": "src/money.py", "old_symbol": "format_money", "disposition": "removed"}
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 2
    assert "declared removed but still present: src/money.py format_money" in result.stdout


def test_kept_symbol_requires_real_consumer(candidate):
    def keep(consumer):
        def change(report):
            report["replacements"][0] = {"old_path": "src/money.py", "old_symbol": "format_money",
                                         "disposition": "kept", "consumer": consumer}
        return change
    assert run(candidate, mutated(candidate, keep("src/report.py"))).returncode == 0
    for consumer in ("src/money.py", "requirements.txt"):
        result = run(candidate, mutated(candidate, keep(consumer)))
        assert result.returncode == 2
        assert "kept symbol has no real consumer" in result.stdout


def test_stale_subject_sha_blocks(candidate):
    result = run(candidate, mutated(candidate, lambda r: r.update(subject_sha=candidate["base"])))
    assert result.returncode == 2
    assert "stale for material head" in result.stdout


def test_unverified_reference_is_schema_violation(candidate):
    def change(report):
        report["references"][0]["verified_by"]["exit_code"] = 1
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 2
    assert "schema violation" in result.stdout


def test_missing_commit_is_unknown_not_approval(candidate):
    result = run(candidate, head="0" * 40)
    assert result.returncode == 3
    assert result.stdout.startswith("UNKNOWN")


def test_gate_is_registered_and_loaded_progressively():
    registry = json.loads((ROOT / "contracts" / "gate-registry.json").read_text(encoding="utf-8"))
    gate = next(item for item in registry["gates"] if item["id"] == "codebase-grounding")
    assert gate["activate_when"] == {"kind": "classification", "field": "code_touched", "equals": True}
    assert gate["controls"] == ["GROUND-REUSE-001", "GROUND-EXIST-001", "GROUND-DEAD-001"]
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "references/codebase-grounding-gate.md" in skill
    assert "scripts/validate_codebase_grounding.py" in skill
    reference = (ROOT / "references" / "codebase-grounding-gate.md").read_text(encoding="utf-8")
    for control in gate["controls"]:
        assert control in reference


def test_planner_requires_gate_only_when_code_is_touched():
    from plan_execution import required_gates_from_registry
    registry = json.loads((ROOT / "contracts" / "gate-registry.json").read_text(encoding="utf-8"))
    def gates(code_touched):
        return required_gates_from_registry(
            registry, profile="standard", signals=set(),
            classification={"code_touched": code_touched, "behavioral_change": code_touched},
        )
    assert "codebase-grounding" in gates(True)
    assert "codebase-grounding" not in gates(False)
