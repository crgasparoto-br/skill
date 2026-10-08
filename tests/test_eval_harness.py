from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from evals import run_evals as eval_harness
from evals.run_evals import evaluate_result, run_evaluations, verify_report
from scripts.validate_evals import harness_version_errors, validate_evals

ROOT = Path(__file__).resolve().parents[1]
CASE_ID = "V030-001-runner-contract-001"


def total_case_count() -> int:
    return len(list((ROOT / "evals" / "cases").glob("*.json")))


def fixture_result() -> dict:
    return json.loads(
        (ROOT / "evals" / "fixtures" / "results" / f"{CASE_ID}.json").read_text(encoding="utf-8")
    )


def fixture_case() -> dict:
    return json.loads(
        (ROOT / "evals" / "cases" / f"{CASE_ID}.json").read_text(encoding="utf-8")
    )


def assert_pid_dead(pid_file: Path) -> None:
    pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise AssertionError(f"processo {pid} permaneceu vivo após o runner retornar")


def test_eval_harness_validates_cases_and_fixture_replay() -> None:
    assert validate_evals(ROOT) == []


def test_fixture_replay_passes_every_case() -> None:
    report = run_evaluations(ROOT, results_dir=ROOT / "evals" / "fixtures" / "results")
    assert report["mode"] == "replay"
    assert report["summary"] == {
        "total": total_case_count(),
        "passed": total_case_count(),
        "failed": 0,
        "not_run": 0,
        "invalid": 0,
    }
    assert report["cases"][0]["case_id"] == CASE_ID
    assert all(record["status"] == "PASS" for record in report["cases"])


def test_validate_only_never_declares_behavioral_pass() -> None:
    report = run_evaluations(ROOT, validate_only=True)
    assert report["mode"] == "validate-only"
    assert report["summary"]["passed"] == 0
    assert report["summary"]["not_run"] == total_case_count()


def test_missing_runtime_is_not_run_not_pass(tmp_path: Path) -> None:
    report = run_evaluations(ROOT, results_dir=tmp_path)
    assert report["summary"]["not_run"] == total_case_count()
    assert report["summary"]["invalid"] == 0
    assert report["cases"][0]["status"] == "NOT_RUN"


def test_invalid_result_is_invalid(tmp_path: Path) -> None:
    (tmp_path / f"{CASE_ID}.json").write_text("{}\n", encoding="utf-8")
    report = run_evaluations(ROOT, results_dir=tmp_path)
    assert report["summary"]["invalid"] == 1
    assert report["summary"]["not_run"] == total_case_count() - 1
    assert report["cases"][0]["status"] == "INVALID"


def test_provider_invalid_json_object_is_invalid_not_runner_crash(tmp_path: Path) -> None:
    provider = tmp_path / "provider.py"
    provider.write_text("print('{}')\n", encoding="utf-8")
    report = run_evaluations(ROOT, provider_command=f"{sys.executable} {provider}")
    assert report["summary"]["invalid"] == total_case_count()
    assert all(record["status"] == "INVALID" for record in report["cases"])


@pytest.mark.parametrize("payload", ["null", "[]", "not-json"])
def test_provider_non_object_or_invalid_json_is_invalid(tmp_path: Path, payload: str) -> None:
    provider = tmp_path / "provider.py"
    provider.write_text(f"print({payload!r})\n", encoding="utf-8")
    report = run_evaluations(ROOT, provider_command=f"{sys.executable} {provider}")
    assert report["summary"]["invalid"] == total_case_count()


def test_provider_stdout_limit_is_enforced_during_capture(tmp_path: Path) -> None:
    provider = tmp_path / "provider.py"
    provider.write_text("print('x' * 1000001)\n", encoding="utf-8")
    report = run_evaluations(ROOT, provider_command=f"{sys.executable} {provider}")
    assert report["summary"]["invalid"] == total_case_count()


def test_provider_stdout_is_reassembled_incrementally(tmp_path: Path) -> None:
    provider = tmp_path / "provider.py"
    provider.write_text(
        "import json, sys, time\n"
        "case = json.load(sys.stdin)\n"
        "result = {'schema_version': 1, 'case_id': case['case_id'], 'outcome': 'PASS',\n"
        "  'selected_skill': None, 'loaded_references': [], 'actions': [],\n"
        "  'evidence': ['case-contract-valid'], 'response_text': 'Harness contract validated.',\n"
        "  'metrics': {'external_calls': 0, 'duration_ms': 1, 'context_chars': 512},\n"
        "  'runtime': {'status': 'available', 'provider': 'test-provider', 'model': 'test-model',\n"
        "    'adapter': 'generic', 'trust': 'provider-untrusted', 'attestation': None}}\n"
        "raw = json.dumps(result)\n"
        "for index in range(0, len(raw), 7):\n"
        "  sys.stdout.write(raw[index:index + 7]); sys.stdout.flush(); time.sleep(0.005)\n",
        encoding="utf-8",
    )
    report = run_evaluations(ROOT, provider_command=f"{sys.executable} {provider}")
    assert report["summary"]["not_run"] == total_case_count()
    assert report["summary"]["invalid"] == 0


def test_provider_command_is_never_accepted_as_trusted_pass(tmp_path: Path) -> None:
    provider = tmp_path / "provider.py"
    provider.write_text(
        "import json, sys\n"
        "case = json.load(sys.stdin)\n"
        "print(json.dumps({\n"
        "  'schema_version': 1, 'case_id': case['case_id'], 'outcome': 'PASS',\n"
        "  'selected_skill': None, 'loaded_references': [], 'actions': [],\n"
        "  'evidence': ['case-contract-valid'], 'response_text': 'Harness contract validated.',\n"
        "  'metrics': {'external_calls': 0, 'duration_ms': 1, 'context_chars': 512},\n"
        "  'runtime': {'status': 'available', 'provider': 'test-provider', 'model': 'test-model',\n"
        "              'adapter': 'generic', 'trust': 'provider-untrusted', 'attestation': None}\n"
        "}))\n",
        encoding="utf-8",
    )
    report = run_evaluations(ROOT, provider_command=f"{sys.executable} {provider}")
    assert report["summary"]["passed"] == 0
    assert report["summary"]["not_run"] == total_case_count()


def test_timeout_kills_descendant_after_provider_leader_exits(tmp_path: Path) -> None:
    provider = tmp_path / "provider.py"
    pid_file = tmp_path / "child.pid"
    provider.write_text(
        "import pathlib, subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "print('{}', flush=True)\n",
        encoding="utf-8",
    )
    report = run_evaluations(ROOT, provider_command=f"{sys.executable} {provider} {pid_file}")
    assert report["summary"]["not_run"] == total_case_count()
    assert_pid_dead(pid_file)


def test_closed_provider_streams_still_kill_running_process(tmp_path: Path) -> None:
    provider = tmp_path / "provider.py"
    pid_file = tmp_path / "provider.pid"
    provider.write_text(
        "import os, pathlib, sys, time\n"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "sys.stdout.close(); sys.stderr.close()\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    report = run_evaluations(ROOT, provider_command=f"{sys.executable} {provider} {pid_file}")
    assert report["summary"]["not_run"] == total_case_count()
    assert_pid_dead(pid_file)


def test_closed_streams_kill_descendant_after_leader_exit(tmp_path: Path) -> None:
    provider = tmp_path / "provider.py"
    pid_file = tmp_path / "child.pid"
    provider.write_text(
        "import pathlib, subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "print('{}', flush=True)\n"
        "sys.stdout.close(); sys.stderr.close()\n",
        encoding="utf-8",
    )
    report = run_evaluations(ROOT, provider_command=f"{sys.executable} {provider} {pid_file}")
    assert report["summary"]["invalid"] == total_case_count()
    assert_pid_dead(pid_file)


def test_cleanup_attempts_sigkill_when_sigterm_group_is_already_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    class FakeProcess:
        pid = 12345

        def wait(self, timeout: float | None = None) -> int:
            if timeout == 0.25:
                raise subprocess.TimeoutExpired("fake", timeout)
            return 0

    def fake_killpg(_pid: int, sig: int) -> None:
        calls.append(sig)
        if sig == eval_harness.signal.SIGTERM:
            raise ProcessLookupError

    monkeypatch.setattr(eval_harness.os, "killpg", fake_killpg)
    eval_harness._terminate_process_group(FakeProcess())  # noqa: SLF001 - teste cobre funcao interna do modulo por decisao declarada de cobertura
    assert calls == [eval_harness.signal.SIGTERM, eval_harness.signal.SIGKILL]


def test_provider_result_with_wrong_case_id_is_invalid(tmp_path: Path) -> None:
    provider = tmp_path / "provider.py"
    provider.write_text(
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({\n"
        "  'schema_version': 1, 'case_id': 'V030-999-other-case', 'outcome': 'PASS',\n"
        "  'selected_skill': None, 'loaded_references': [], 'actions': [],\n"
        "  'evidence': ['case-contract-valid'], 'response_text': 'Harness contract validated.',\n"
        "  'metrics': {'external_calls': 0, 'duration_ms': 1, 'context_chars': 512},\n"
        "  'runtime': {'status': 'available', 'provider': 'test-provider', 'model': 'test-model',\n"
        "              'adapter': 'generic', 'trust': 'provider-untrusted', 'attestation': None}\n"
        "}))\n",
        encoding="utf-8",
    )
    report = run_evaluations(ROOT, provider_command=f"{sys.executable} {provider}")
    assert report["summary"]["invalid"] == total_case_count()


def test_replay_rejects_wrong_adapter(tmp_path: Path) -> None:
    result = fixture_result()
    result["runtime"]["adapter"] = "openai"
    (tmp_path / f"{CASE_ID}.json").write_text(json.dumps(result), encoding="utf-8")
    report = run_evaluations(ROOT, results_dir=tmp_path)
    assert report["summary"]["invalid"] == 1
    assert report["summary"]["not_run"] == total_case_count() - 1


def test_mismatched_outcome_fails(tmp_path: Path) -> None:
    result = fixture_result()
    result["outcome"] = "UNKNOWN"
    record = evaluate_result(fixture_case(), result, source_mode="replay")
    assert record["status"] == "FAIL"


def test_response_minimum_and_marker_are_enforced(tmp_path: Path) -> None:
    result = fixture_result()
    result["response_text"] = "short"
    record = evaluate_result(fixture_case(), result, source_mode="replay")
    assert record["status"] == "FAIL"
    assert any("response_text" in reason for reason in record["reasons"])


def test_forbidden_action_is_a_failure() -> None:
    result = fixture_result()
    result["actions"] = ["merge"]
    record = evaluate_result(fixture_case(), result, source_mode="replay")
    assert record["status"] == "FAIL"
    assert any("ações proibidas" in reason for reason in record["reasons"])


def test_required_evidence_is_a_failure_when_missing() -> None:
    result = fixture_result()
    result["evidence"] = []
    record = evaluate_result(fixture_case(), result, source_mode="replay")
    assert record["status"] == "FAIL"
    assert any("evidências obrigatórias" in reason for reason in record["reasons"])


def test_each_declared_budget_is_enforced() -> None:
    case = fixture_case()
    for key in ("external_calls", "duration_ms", "context_chars"):
        result = fixture_result()
        result["metrics"][key] = case["budgets"][f"max_{key}"] + 1
        record = evaluate_result(case, result, source_mode="replay")
        assert record["status"] == "FAIL"
        assert any("orçamento excedido" in reason for reason in record["reasons"])


def test_extra_result_file_is_rejected(tmp_path: Path) -> None:
    shutil.copy(
        ROOT / "evals" / "fixtures" / "results" / f"{CASE_ID}.json",
        tmp_path / f"{CASE_ID}.json",
    )
    (tmp_path / "notes.txt").write_text("stale\n", encoding="utf-8")
    try:
        run_evaluations(ROOT, results_dir=tmp_path)
    except ValueError as exc:
        assert "resultados sem caso correspondente" in str(exc)
    else:
        raise AssertionError("fixture extra não foi rejeitado")


def test_expected_result_name_must_be_regular_file(tmp_path: Path) -> None:
    (tmp_path / f"{CASE_ID}.json").mkdir()
    with pytest.raises(ValueError, match="arquivos regulares"):
        run_evaluations(ROOT, results_dir=tmp_path)


def test_expected_result_symlink_is_rejected(tmp_path: Path) -> None:
    source = ROOT / "evals" / "fixtures" / "results" / f"{CASE_ID}.json"
    (tmp_path / f"{CASE_ID}.json").symlink_to(source)
    with pytest.raises(ValueError, match="arquivos regulares"):
        run_evaluations(ROOT, results_dir=tmp_path)


def test_run_id_is_stable_across_result_directories(tmp_path: Path) -> None:
    first_dir = tmp_path / "one"
    second_dir = tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    source = ROOT / "evals" / "fixtures" / "results" / f"{CASE_ID}.json"
    shutil.copy(source, first_dir / source.name)
    shutil.copy(source, second_dir / source.name)
    first = run_evaluations(ROOT, results_dir=first_dir)
    second = run_evaluations(ROOT, results_dir=second_dir)
    assert first["summary"]["invalid"] == 1
    assert second["summary"]["invalid"] == 1
    assert first["run_id"] == second["run_id"]
    assert first["content_sha256"] == second["content_sha256"]


def test_manifest_is_the_runner_version_source(tmp_path: Path) -> None:
    shutil.copytree(ROOT / "evals", tmp_path / "evals")
    manifest_path = tmp_path / "evals" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["harness_version"] = "9.9.9"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = run_evaluations(tmp_path, validate_only=True)
    assert report["harness_version"] == "9.9.9"


def test_attested_result_remains_not_run_without_verifier() -> None:
    result = fixture_result()
    result["runtime"]["trust"] = "attested"
    result["runtime"]["provider"] = "test-provider"
    result["runtime"]["model"] = "test-model"
    result["runtime"]["attestation"] = {
        "case_id": CASE_ID,
        "result_sha256": "0" * 64,
        "producer": "test",
        "subject_sha": "0" * 40,
        "observed_at": "2026-09-29T13:00:00Z",
    }
    record = evaluate_result(fixture_case(), result, source_mode="replay")
    assert record["status"] == "NOT_RUN"


def test_report_verification_rejects_tampering(tmp_path: Path) -> None:
    report = run_evaluations(ROOT, results_dir=ROOT / "evals" / "fixtures" / "results")
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert verify_report(ROOT, report_path) == []
    report["summary"]["passed"] = 0
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert verify_report(ROOT, report_path)


def test_run_id_and_content_hash_are_stable_for_same_inputs() -> None:
    results = ROOT / "evals" / "fixtures" / "results"
    first = run_evaluations(ROOT, results_dir=results)
    second = run_evaluations(ROOT, results_dir=results)
    assert first["run_id"] == second["run_id"]
    assert first["content_sha256"] == second["content_sha256"]


def test_harness_version_matches_the_manifest() -> None:
    """A versao exportada pelo pacote de avaliacoes nao pode divergir do manifesto do harness."""
    manifest = json.loads((ROOT / "evals" / "manifest.json").read_text(encoding="utf-8"))
    assert harness_version_errors(ROOT, manifest) == []


def test_harness_version_divergence_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "evals"
    package.mkdir()
    (package / "__init__.py").write_text(
        '__all__ = ["__version__"]\n__version__ = "0.1.0"\n', encoding="utf-8"
    )
    problems = harness_version_errors(tmp_path, {"harness_version": "0.3.0"})
    assert problems and "0.1.0" in problems[0] and "0.3.0" in problems[0]


def test_harness_version_without_literal_is_rejected(tmp_path: Path) -> None:
    """Valor calculado nao serve como declaracao verificavel da versao do harness."""
    package = tmp_path / "evals"
    package.mkdir()
    (package / "__init__.py").write_text("__version__ = build_version()\n", encoding="utf-8")
    problems = harness_version_errors(tmp_path, {"harness_version": "0.3.0"})
    assert problems and "literal" in problems[0]


def test_harness_version_module_missing_is_rejected(tmp_path: Path) -> None:
    problems = harness_version_errors(tmp_path, {"harness_version": "0.3.0"})
    assert problems and "ilegivel" in problems[0]


def test_harness_version_non_literal_after_literal_is_rejected(tmp_path: Path) -> None:
    """Atribuicao nao literal depois da literal nao pode passar: o valor efetivo seria calculado."""
    package = tmp_path / "evals"
    package.mkdir()
    (package / "__init__.py").write_text(
        'def build_version():\n    return "9.9.9"\n\n__version__ = "0.3.0"\n__version__ = build_version()\n',
        encoding="utf-8",
    )
    problems = harness_version_errors(tmp_path, {"harness_version": "0.3.0"})
    assert problems and "literal" in problems[0]


def test_harness_version_assigned_twice_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "evals"
    package.mkdir()
    (package / "__init__.py").write_text(
        '__version__ = "0.1.0"\n__version__ = "0.3.0"\n', encoding="utf-8"
    )
    problems = harness_version_errors(tmp_path, {"harness_version": "0.3.0"})
    assert problems and "mais de uma vez" in problems[0]


def test_harness_version_annotated_assignment_divergence_is_rejected(tmp_path: Path) -> None:
    """Atribuicao anotada depois da literal tambem define o valor efetivo e precisa reprovar."""
    package = tmp_path / "evals"
    package.mkdir()
    (package / "__init__.py").write_text(
        '__version__ = "0.3.0"\n__version__: str = "9.9.9"\n', encoding="utf-8"
    )
    problems = harness_version_errors(tmp_path, {"harness_version": "0.3.0"})
    assert problems


def test_harness_version_augmented_assignment_is_rejected(tmp_path: Path) -> None:
    package = tmp_path / "evals"
    package.mkdir()
    (package / "__init__.py").write_text('__version__ = "0.3.0"\n__version__ += "-x"\n', encoding="utf-8")
    problems = harness_version_errors(tmp_path, {"harness_version": "0.3.0"})
    assert problems and "aumentada" in problems[0]
