from __future__ import annotations

import copy
import hashlib
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


def passed_verification(repo: Path, head: str, test_path: str) -> dict:
    command = f"python -m pytest -q {test_path}"
    check = subprocess.run([sys.executable, "-m", "pytest", "-q", test_path],
                           cwd=repo, capture_output=True, text=True, check=False)
    assert check.returncode == 0, check.stdout + check.stderr
    proof = (f"HEAD: {head}\nCOMMAND: {command}\nEXIT_CODE: 0\n"
             f"REACHED: {test_path}\n" + check.stdout + check.stderr)
    write(repo, "verification.log", proof)
    return {"status": "passed", "command": command, "exit_code": 0,
            "subject_sha": head, "reached_tests": [test_path],
            "evidence_path": "verification.log",
            "evidence_sha256": hashlib.sha256(proof.encode()).hexdigest()}


@pytest.fixture()
def candidate(tmp_path: Path) -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    write(repo, "src/money.py", "def format_money(value):\n    return f'{value:.2f}'\n")
    write(repo, "src/legacy_report.py", "def old_total(rows):\n    return sum(rows)\n")
    write(repo, "requirements.txt", "requests>=2\n")
    write(repo, ".gitignore", "__pycache__/\n.pytest_cache/\n*.pyc\nverification.log\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "src/report.py", "import requests\nfrom money import format_money\n\n\ndef total(rows):\n    return format_money(sum(rows))\n")
    write(repo, "tests/test_report.py",
          "import sys, types\nfrom pathlib import Path\n"
          "sys.modules.setdefault('requests', types.ModuleType('requests'))\n"
          "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n"
          "from report import total\n\ndef test_formatted_total():\n"
          "    assert total([1, 2]) == '3.00'\n")
    git(repo, "rm", "-q", "src/legacy_report.py")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "candidate")
    head = git(repo, "rev-parse", "HEAD")
    check = {"command": "pytest tests/test_report.py", "exit_code": 0}
    report = {
        "schema_version": 2,
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
        "test_decisions": [{
            "path": "tests/test_report.py", "operation": "added",
            "scenario": "formatacao de somatorio", "requirement": "somatorio formatado",
            "search": {"queries": ["rg -n total tests"], "scope": "tests/",
                       "runner": "pytest", "candidates": []},
            "decision": "new-test-required", "justification": "novo comportamento agregado sem cenario previo",
            "disposition": "keep",
            "verification": passed_verification(repo, head, "tests/test_report.py"),
        }],
    }
    return {"repo": repo, "base": base, "head": head, "report": report, "tmp": tmp_path}


def run(candidate: dict, report: dict | None = None, head: str | None = None):
    path = candidate["tmp"] / "codebase-grounding.json"
    path.write_text(json.dumps(candidate["report"] if report is None else report), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(candidate["repo"]), "--report", str(path),
         "--base-sha", candidate["base"], "--head-sha", head or candidate["head"]],
        check=False, capture_output=True, text=True,
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
    assert gate["activate_when"]["kind"] == "any"
    assert {rule["field"] for rule in gate["activate_when"]["rules"]} == {"code_touched", "tests_touched"}
    assert gate["controls"] == ["GROUND-REUSE-001", "GROUND-EXIST-001", "GROUND-DEAD-001", "GROUND-TEST-001"]
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "references/codebase-grounding-gate.md" in skill
    assert "scripts/validate_codebase_grounding.py" in skill
    reference = (ROOT / "references" / "codebase-grounding-gate.md").read_text(encoding="utf-8")
    for control in gate["controls"]:
        assert control in reference


def test_planner_requires_gate_for_code_or_test_changes():
    from plan_execution import required_gates_from_registry
    registry = json.loads((ROOT / "contracts" / "gate-registry.json").read_text(encoding="utf-8"))
    def gates(code_touched, tests_touched=False):
        return required_gates_from_registry(
            registry, profile="standard", signals=set(),
            classification={"code_touched": code_touched, "tests_touched": tests_touched, "behavioral_change": code_touched},
        )
    assert "codebase-grounding" in gates(True)
    assert "codebase-grounding" not in gates(False)
    assert "codebase-grounding" in gates(False, True)


def test_missing_test_decision_blocks_even_for_test_only_diff(candidate):
    result = run(candidate, mutated(candidate, lambda r: r["test_decisions"].clear()))
    assert result.returncode == 2
    assert "test diff lacks decision: tests/test_report.py" in result.stdout


def test_legacy_v1_is_explicitly_rejected_for_test_diff(candidate):
    def change(report):
        report["schema_version"] = 1
        report.pop("test_decisions")
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 2
    assert "legacy v1 accepted only without test changes" in result.stdout


def test_distinct_oracle_is_not_rejected_by_nominal_similarity(candidate):
    def change(report):
        record = report["test_decisions"][0]
        record["search"]["candidates"] = [{
            "path": "src/money.py", "case": "unit formatting",
            "oracle": "format_money decimals", "comparison": "unit does not cover aggregate"
        }]
        record["justification"] = "independent integration oracle"
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 0, result.stdout


def test_added_test_cannot_claim_covered_by_existing_without_any_candidate(candidate):
    def change(report):
        record = report["test_decisions"][0]
        record["decision"] = "covered-by-existing"
        record["search"]["candidates"] = []
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 2
    assert "covered-by-existing lacks an identified existing test" in result.stdout
    assert "added test cannot be classified covered-by-existing" in result.stdout


def test_added_test_cannot_claim_covered_by_existing_with_real_candidate(candidate):
    def change(report):
        record = report["test_decisions"][0]
        record["decision"] = "covered-by-existing"
        record["search"]["candidates"] = [{
            "path": "src/money.py", "case": "unit formatting",
            "oracle": "format_money decimals", "comparison": "unit does not cover aggregate"
        }]
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 2
    assert "added test cannot be classified covered-by-existing" in result.stdout


def test_dynamic_runner_unavailable_is_unknown_not_ready(candidate):
    def change(report):
        record = report["test_decisions"][0]
        record["search"]["runner"] = "dynamic plugin discovery"
        record["verification"] = {"status": "unknown", "reason": "runtime runner not accessible"}
    result = run(candidate, mutated(candidate, change))
    assert result.returncode == 3
    assert "UNKNOWN" in result.stdout


def test_deleted_test_requires_preserved_controls(candidate):
    repo = candidate["repo"]
    write(repo, "tests/test_replacement.py", "def test_preserved_control():\n    assert 1 + 2 == 3\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed replacement")
    deletion_base = git(repo, "rev-parse", "HEAD")
    git(repo, "rm", "-q", "tests/test_report.py")
    git(repo, "commit", "-q", "-m", "remove test")
    new_head = git(repo, "rev-parse", "HEAD")
    scenario = {**candidate, "base": deletion_base, "head": new_head}
    report = copy.deepcopy(candidate["report"])
    report.update(subject_sha=new_head, base_sha=deletion_base, creations=[], references=[], replacements=[])
    record = report["test_decisions"][0]
    record.update(operation="deleted", decision="covered-by-existing", disposition="remove-candidate")
    assert "coverage_before" in run(scenario, report).stdout
    record.update(coverage_before=["positive", "negative"], coverage_after=["positive", "negative"],
                  replacement_tests=["tests/test_replacement.py"])
    record["verification"] = passed_verification(repo, new_head, "tests/test_replacement.py")
    assert run(scenario, report).returncode == 0
    invalid = copy.deepcopy(report)
    invalid["test_decisions"][0]["verification"]["command"] = "pytest tests/test_report.py"
    assert "command targets only deleted test" in run(scenario, invalid).stdout
    invalid = copy.deepcopy(report)
    invalid["test_decisions"][0]["coverage_after"] = ["positive"]
    assert "loses documented control IDs" in run(scenario, invalid).stdout
    invalid = copy.deepcopy(report)
    invalid["test_decisions"][0]["verification"]["subject_sha"] = candidate["head"]
    assert "not bound to head" in run(scenario, invalid).stdout
    invalid = copy.deepcopy(report)
    invalid["test_decisions"][0]["verification"]["evidence_sha256"] = "f" * 64
    assert "evidence hash mismatch" in run(scenario, invalid).stdout


def test_renamed_test_requires_source_at_base(candidate):
    repo = candidate["repo"]
    git(repo, "mv", "tests/test_report.py", "tests/test_totals.py")
    git(repo, "commit", "-q", "-m", "rename test")
    head = git(repo, "rev-parse", "HEAD")
    scenario = {**candidate, "base": candidate["head"], "head": head}
    report = copy.deepcopy(candidate["report"])
    report.update(subject_sha=head, base_sha=candidate["head"], creations=[], references=[], replacements=[])
    record = report["test_decisions"][0]
    record.update(path="tests/test_totals.py", operation="renamed", prior_path="tests/test_report.py",
                  decision="covered-by-existing", justification="only renamed, assertions unchanged")
    record["verification"] = passed_verification(repo, head, "tests/test_totals.py")
    assert run(scenario, report).returncode == 0


def test_test_only_feature_diff_triggers_gate_without_global_hygiene():
    from plan_execution import classify_changes
    classification = classify_changes(["features/checkout.feature"], set())
    assert classification["tests_touched"]
    assert not classification["hygiene_applicable"]
    assert not classification["code_touched"]


def test_test_scope_and_handoff_match_for_non_code_conventions():
    from plan_execution import is_test_path
    from validate_handoff_certificate import scope_touches_code, scope_touches_tests

    examples = [
        "spec/cases.json",
        "tests/fixtures/report.json",
        "features/payment.feature",
        "e2e/smoke.robot",
        "pytest.ini",
        "vitest.config.ts",
        "src/report.test.json",
        "src/payment.cy.ts",
        "src/login.e2e.ts",
    ]
    for path in examples:
        assert is_test_path(path), path
        assert scope_touches_tests([path]), path
    for path in ("docs/guide.md", "src/README.txt", "pytest.ini.backup"):
        assert not is_test_path(path)
        assert not scope_touches_tests([path])
    assert not scope_touches_code(["spec/cases.json"])


def test_go_test_only_and_runner_manifests_activate_gate():
    from plan_execution import classify_changes, is_test_path
    for filename in ("pkg/payment_test.go", "pkg/payment_test.py", "e2e/smoke.ts",
                     "cypress/login.cy.ts", "src/payment.cy.ts", "src/login.e2e.ts"):
        classification = classify_changes([filename], set())
        assert is_test_path(filename)
        assert classification["tests_touched"]
        assert classification["test_only"]
        assert not classification["hygiene_applicable"]
    for manifest in ("pyproject.toml", "package.json"):
        classification = classify_changes([manifest], set())
        assert classification["tests_touched"]
        assert not classification["test_only"]
    from validate_handoff_certificate import scope_touches_tests
    assert scope_touches_tests(["pkg/payment_test.go", "package.json", "pyproject.toml"])


def test_blocked_scenario_cannot_report_passed(candidate):
    report = copy.deepcopy(candidate["report"])
    report["test_decisions"][0]["decision"] = "not-testable/blocked"
    report["test_decisions"][0]["verification"]["reason"] = "runner unavailable"
    result = run(candidate, report)
    assert result.returncode == 2
    assert "blocked scenario cannot claim passed" in result.stdout


@pytest.mark.parametrize("field", ["subject_sha", "reached_tests", "evidence_path", "evidence_sha256"])
def test_passed_test_requires_execution_proof_fields(candidate, field):
    report = copy.deepcopy(candidate["report"])
    report["test_decisions"][0]["verification"].pop(field)
    assert run(candidate, report).returncode == 2


def test_non_deleted_test_rejects_stale_head_even_with_valid_log_hash(candidate):
    report = copy.deepcopy(candidate["report"])
    report["test_decisions"][0]["verification"]["subject_sha"] = candidate["base"]
    result = run(candidate, report)
    assert result.returncode == 2
    assert "execution not bound to head" in result.stdout


def test_non_deleted_test_rejects_unreached_case(candidate):
    report = copy.deepcopy(candidate["report"])
    report["test_decisions"][0]["verification"]["reached_tests"] = ["tests/test_other.py"]
    result = run(candidate, report)
    assert result.returncode == 2
    assert "changed test not recorded as reached" in result.stdout


def test_non_deleted_test_rejects_rehashed_log_with_stale_head(candidate):
    report = copy.deepcopy(candidate["report"])
    record = report["test_decisions"][0]["verification"]
    proof = (candidate["repo"] / "verification.log").read_text()
    proof = proof.replace(f"HEAD: {candidate['head']}", "HEAD: " + candidate["base"])
    write(candidate["repo"], "verification.log", proof)
    record["evidence_sha256"] = hashlib.sha256(proof.encode()).hexdigest()
    result = run(candidate, report)
    assert result.returncode == 2
    assert "raw evidence missing exact head" in result.stdout


def test_test_only_cypress_outside_conventional_folder_triggers_gate(candidate):
    repo = candidate["repo"]
    write(repo, "src/payment.cy.ts", "describe('payment', () => { it('works', () => {}) })\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "test-only custom location")
    head = git(repo, "rev-parse", "HEAD")
    scenario = {**candidate, "base": candidate["head"], "head": head}
    report = copy.deepcopy(candidate["report"])
    report.update(subject_sha=head, base_sha=candidate["head"], creations=[],
                  references=[], replacements=[])
    record = report["test_decisions"][0]
    record.update(path="src/payment.cy.ts", operation="added",
                  verification={"status": "unknown", "reason": "Cypress runner unavailable"})
    result = run(scenario, report)
    assert result.returncode == 3
    assert "src/payment.cy.ts" in result.stdout


@pytest.mark.parametrize("config_path,config_body", [
    ("pytest.ini", "[pytest]\\npython_files = smoke.py\\n"),
    ("pyproject.toml", '[tool.pytest.ini_options]\\npython_files = ["smoke.py"]\\n'),
    ("tox.ini", "[pytest]\\npython_files = smoke.py\\n"),
    ("setup.cfg", "[tool:pytest]\\npython_files = smoke.py\\n"),
    ("checks/pytest.ini", "[pytest]\\npython_files = smoke.py\\n"),
])
def test_configured_pytest_filename_is_a_test(candidate, config_path, config_body):
    from plan_execution import classify_changes, is_test_path, pytest_discovery_configs

    repo = candidate["repo"]
    write(repo, config_path, config_body.replace("\\n", "\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "configure pytest filename discovery")
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "checks/smoke.py", "def test_smoke():\\n    assert 2 + 2 == 4\\n".replace("\\n", "\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "add discovered test")
    head = git(repo, "rev-parse", "HEAD")

    pytest_configs = pytest_discovery_configs(
        ["checks/smoke.py"],
        lambda path: (repo / path).read_text() if (repo / path).is_file() else None,
    )
    assert is_test_path("checks/smoke.py", pytest_configs=pytest_configs)
    classified = classify_changes(["checks/smoke.py"], set(), pytest_configs=pytest_configs)
    assert classified["tests_touched"] and classified["test_only"]
    assert not classified["hygiene_applicable"]

    collection = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "checks"],
        cwd=repo, capture_output=True, text=True, check=False,
    )
    assert collection.returncode == 0, collection.stdout + collection.stderr
    assert "smoke.py::test_smoke" in collection.stdout

    scenario = {**candidate, "base": base, "head": head}
    report = copy.deepcopy(candidate["report"])
    report.update(subject_sha=head, base_sha=base, creations=[], references=[], replacements=[])
    report["test_decisions"][0].update(
        path="checks/smoke.py", operation="added", scenario="runner configured filename",
        requirement="configured test discovery", search={
            "queries": ["pytest --collect-only -q checks/smoke.py"], "scope": "checks/",
            "runner": "pytest", "candidates": [],
        },
        verification=passed_verification(repo, head, "checks/smoke.py"),
    )
    assert run(scenario, report).returncode == 0
    report["test_decisions"] = []
    result = run(scenario, report)
    assert result.returncode == 2
    assert "test diff lacks decision: checks/smoke.py" in result.stdout


def test_non_test_package_metadata_change_does_not_require_test_decision(candidate):
    repo = candidate["repo"]
    write(repo, "package.json", '{"name":"sample","version":"1.0.0","scripts":{"test":"vitest"}}\\n'.replace("\\n", "\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed package manifest")
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "package.json", '{"name":"sample","version":"1.0.1","scripts":{"test":"vitest"}}\\n'.replace("\\n", "\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change unrelated package metadata")
    head = git(repo, "rev-parse", "HEAD")
    report = {
        "schema_version": 1,
        "subject_sha": head, "base_sha": base,
        "creations": [], "references": [], "replacements": [],
    }
    result = run({**candidate, "base": base, "head": head}, report)
    assert result.returncode == 0, result.stdout


def test_package_test_script_change_requires_decision(candidate):
    repo = candidate["repo"]
    write(repo, "package.json", '{"scripts":{"test":"vitest"}}\\n'.replace("\\n", "\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed test command")
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "package.json", '{"scripts":{"test":"vitest run"}}\\n'.replace("\\n", "\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "modify test command")
    head = git(repo, "rev-parse", "HEAD")
    report = {
        "schema_version": 2, "subject_sha": head, "base_sha": base,
        "creations": [], "references": [], "replacements": [], "test_decisions": [],
    }
    result = run({**candidate, "base": base, "head": head}, report)
    assert result.returncode == 2
    assert "test diff lacks decision: package.json" in result.stdout


def test_runner_pattern_is_scoped_to_config_directory():
    from plan_execution import is_test_path, pytest_discovery_configs
    configs = pytest_discovery_configs(
        ["checks/smoke.py", "src/smoke.py"],
        lambda path: "[pytest]\\npython_files = smoke.py\\n".replace("\\n", "\n")
        if path == "checks/pytest.ini" else None,
    )
    assert is_test_path("checks/smoke.py", pytest_configs=configs)
    assert not is_test_path("src/smoke.py", pytest_configs=configs)


def test_unparseable_pytest_discovery_is_unknown(candidate):
    repo = candidate["repo"]
    write(repo, "pytest.ini", "[pytest\\npython_files = smoke.py\\n".replace("\\n", "\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed invalid test config")
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "src/money.py", "def format_money(value):\\n    return f'{value:.3f}'\\n".replace("\\n", "\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change implementation with unknown test discovery")
    head = git(repo, "rev-parse", "HEAD")
    report = {
        "schema_version": 1, "subject_sha": head, "base_sha": base,
        "creations": [], "references": [], "replacements": [],
    }
    result = run({**candidate, "base": base, "head": head}, report)
    assert result.returncode == 3, result.stdout
    assert "runner discovery UNKNOWN" in result.stdout
