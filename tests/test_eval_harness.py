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


CANONICAL_SHIM = '__all__ = ["__version__"]\n__version__ = "0.3.0"\n'


def _package(tmp_path: Path, body: str) -> Path:
    package = tmp_path / "evals"
    package.mkdir()
    (package / "__init__.py").write_text(body, encoding="utf-8")
    return tmp_path


def _copia_do_repositorio(tmp_path: Path, corpo: str) -> Path:
    copia = tmp_path / "copia"
    shutil.copytree(ROOT, copia, ignore=shutil.ignore_patterns(".git", ".ruff_cache", "__pycache__"))
    (copia / "evals" / "__init__.py").write_text(corpo, encoding="utf-8")
    return copia


def test_harness_version_matches_the_manifest() -> None:
    """A versao exportada pelo pacote de avaliacoes nao pode divergir do manifesto do harness."""
    manifest = json.loads((ROOT / "evals" / "manifest.json").read_text(encoding="utf-8"))
    assert harness_version_errors(ROOT, manifest) == []


@pytest.mark.parametrize(
    "corpo",
    [
        CANONICAL_SHIM,
        '"""Versioned behavioral-evaluation harness for the skills catalog."""\n' + CANONICAL_SHIM,
    ],
)
def test_harness_version_canonical_envelope_is_accepted(tmp_path: Path, corpo: str) -> None:
    root = _package(tmp_path, corpo)
    assert harness_version_errors(root, {"harness_version": "0.3.0"}) == []


def test_harness_version_divergence_is_rejected(tmp_path: Path) -> None:
    root = _package(tmp_path, '__all__ = ["__version__"]\n__version__ = "9.9.9"\n')
    problems = harness_version_errors(root, {"harness_version": "0.3.0"})
    assert problems and "9.9.9" in problems[0] and "0.3.0" in problems[0]


@pytest.mark.parametrize(
    "corpo",
    [
        '__all__ = ["__version__"]\n__version__ = build()\n',
        '__all__ = ["__version__"]\n',
        '__version__ = "0.3.0"\n',
        '__all__ = ["other"]\n__version__ = "0.3.0"\n',
        '__all__ = ("__version__",)\n__version__ = "0.3.0"\n',
        '__all__ = ["__version__", 1]\n__version__ = "0.3.0"\n',
        '__all__ = alias = ["__version__"]\n__version__ = "0.3.0"\n',
        '__version__ = alias = "0.3.0"\n__all__ = ["__version__"]\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\n__version__ = "9.9.9"\n',
        '__all__ = ["__version__"]\n__version__: str = "0.3.0"\n',
        '__all__ = ["__version__"]\n__version__ += "-x"\n',
        '__all__ = ["__version__"]\n__version__, alias = "0.3.0", "x"\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nif True:\n    __version__ = "9.9.9"\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nfor __version__ in ["9.9.9"]:\n    pass\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nwith open("x") as __version__:\n    pass\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\ndel __version__\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nimport os as __version__\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\ndef __version__():\n    pass\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nclass __version__:\n    pass\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\ntype __version__ = str\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\ntry:\n    1 / 0\nexcept Exception as __version__:\n    pass\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nmatch 9:\n    case __version__:\n        pass\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\ndef f(__version__):\n    return __version__\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nfor __all__[0] in ["x"]:\n    pass\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nalias = __all__\nalias.clear()\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nglobals()["__version__"] = "9.9.9"\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nexec("__version__ = \'9.9.9\'")\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nfrom os import *\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\n__all__.append(42)\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\n__all__[0] = "outro"\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nimport sys\nsys.modules[__name__].__version__ = "9.9.9"\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\noutro = 1\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nprint("oi")\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\nimport importlib\nimportlib.import_module("os")\n',
        '__all__ = ["__version__"]\n__version__ = "0.3.0"\n[1 for _ in range(1)]\n',
    ],
)
def test_harness_version_outside_canonical_envelope_is_rejected(tmp_path: Path, corpo: str) -> None:
    """Fora do envelope canonico nao ha forma aceita de religar `__version__` ou `__all__`."""
    root = _package(tmp_path, corpo)
    assert harness_version_errors(root, {"harness_version": "0.3.0"})


def test_harness_version_module_missing_is_rejected(tmp_path: Path) -> None:
    problems = harness_version_errors(tmp_path, {"harness_version": "0.3.0"})
    assert problems and "ilegivel" in problems[0]


def test_version_divergence_is_reported_without_executing_the_package(tmp_path: Path) -> None:
    """A paridade e estatica: divergencia reprova antes de qualquer importacao do pacote auditado."""
    root = _package(
        tmp_path,
        '__all__ = ["__version__"]\n__version__ = "9.9.9"\nraise RuntimeError("PACOTE_EXECUTADO")\n',
    )
    (root / "evals" / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "harness_version": "0.3.0"}), encoding="utf-8"
    )
    problems = validate_evals(root)
    assert problems
    assert not any("PACOTE_EXECUTADO" in problem for problem in problems)


@pytest.mark.parametrize(
    "excecao",
    ['raise RuntimeError("PACOTE_EXECUTADO")', 'raise BaseException("PACOTE_EXECUTADO")'],
)
def test_broken_harness_import_is_reported_readably(tmp_path: Path, excecao: str) -> None:
    """Envelope canonico e harness que falha ao importar viram reprovacao legivel, sem traceback."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    (copia / "evals" / "run_evals.py").write_text(excecao + "\n", encoding="utf-8")
    resultado = subprocess.run(
        [sys.executable, "scripts/validate_evals.py", "--root", "."],
        cwd=copia,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 1
    assert "nao pode ser importado" in resultado.stdout
    assert "Traceback" not in resultado.stderr


@pytest.mark.parametrize(
    "injecao",
    [
        'import evals\nevals.__version__ = "9.9.9"\n',
        'import evals\nevals.__all__ = ["pwned"]\n',
    ],
)
def test_sibling_module_mutation_is_rejected(tmp_path: Path, injecao: str) -> None:
    """Envelope estatico nao basta: alteracao efetiva feita por modulo irmao precisa reprovar."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    alvo = copia / "evals" / "run_evals.py"
    texto = alvo.read_text(encoding="utf-8")
    alvo.write_text(
        texto.replace("from __future__ import annotations\n", "from __future__ import annotations\n" + injecao, 1),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [sys.executable, "scripts/validate_evals.py", "--root", "."],
        cwd=copia,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 1
    assert "tempo de execucao" in resultado.stdout


@pytest.mark.parametrize(
    "corpo",
    [
        '__all__ = ["__version__", "__version__"]\n__version__ = "0.3.0"\n',
        '__all__ = ["__version__", ""]\n__version__ = "0.3.0"\n',
    ],
)
def test_harness_all_with_repetition_or_empty_name_is_rejected(tmp_path: Path, corpo: str) -> None:
    root = _package(tmp_path, corpo)
    assert harness_version_errors(root, {"harness_version": "0.3.0"})


INJECOES_EFETIVAS = {
    "all-item-nao-texto": 'import evals\nevals.__all__ = ["__version__", 1]\n',
    "all-com-repeticao": 'import evals\nevals.__all__ = ["__version__", "__version__", ""]\n',
    "eq-forjado": (
        "import evals\n"
        "class EqualVersion:\n"
        "    def __eq__(self, other):\n"
        '        return other == "0.3.0"\n'
        "evals.__version__ = EqualVersion()\n"
    ),
    "subclasse-de-list": (
        "import evals\n"
        "class ExportList(list):\n"
        "    def __contains__(self, item):\n"
        "        return True\n"
        'evals.__all__ = ExportList(["subclass-rogue"])\n'
    ),
    "classe-de-modulo-explosiva": (
        "import types, evals\n"
        "class Exploding(types.ModuleType):\n"
        "    def __getattribute__(self, name):\n"
        '        if name == "__version__":\n'
        '            raise BaseException("EXPLODE")\n'
        "        return super().__getattribute__(name)\n"
        "evals.__class__ = Exploding\n"
    ),
}


@pytest.mark.parametrize("injecao", INJECOES_EFETIVAS.values(), ids=list(INJECOES_EFETIVAS))
def test_effective_export_divergence_is_rejected_readably(tmp_path: Path, injecao: str) -> None:
    """Valor efetivo fora do envelope precisa reprovar com mensagem legivel, nunca com traceback."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    alvo = copia / "evals" / "run_evals.py"
    texto = alvo.read_text(encoding="utf-8")
    alvo.write_text(
        texto.replace("from __future__ import annotations\n", "from __future__ import annotations\n" + injecao, 1),
        encoding="utf-8",
    )
    resultado = subprocess.run(
        [sys.executable, "scripts/validate_evals.py", "--root", "."],
        cwd=copia,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "tempo de execucao" in resultado.stdout


def test_foreign_package_outside_root_is_rejected(tmp_path: Path) -> None:
    """Pacote resolvido fora da raiz auditada nao pode ser aceito como o harness do repositorio."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    falso = tmp_path / "falso" / "evals"
    falso.mkdir(parents=True)
    (falso / "__init__.py").write_text(CANONICAL_SHIM, encoding="utf-8")
    (falso / "run_evals.py").write_text("def run_evaluations(**kwargs):\n    return {}\n", encoding="utf-8")
    ambiente = dict(os.environ, PYTHONPATH=str(falso.parent))
    resultado = subprocess.run(
        [sys.executable, "scripts/validate_evals.py", "--root", "."],
        cwd=copia,
        capture_output=True,
        text=True,
        check=False,
        env=ambiente,
    )
    assert resultado.returncode == 1
    assert "fora da raiz auditada" in resultado.stdout


@pytest.mark.parametrize("manifesto", ["[]", "null", '"0.3.0"'])
def test_non_object_manifest_is_reported_readably(tmp_path: Path, manifesto: str) -> None:
    """Manifesto JSON valido mas que nao e objeto precisa reprovar sem traceback."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    (copia / "evals" / "manifest.json").write_text(manifesto + "\n", encoding="utf-8")
    resultado = subprocess.run(
        [sys.executable, "scripts/validate_evals.py", "--root", "."],
        cwd=copia,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "objeto JSON" in resultado.stdout


@pytest.mark.parametrize(
    "retorno",
    [
        "def run_evaluations(*args, **kwargs):\n    return {}\n",
        "def run_evaluations(*args, **kwargs):\n    return {'summary': {}}\n",
        "def run_evaluations(*args, **kwargs):\n    return None\n",
    ],
)
def test_malformed_runner_result_is_reported_readably(tmp_path: Path, retorno: str) -> None:
    """Resumo ausente ou sem contagem inteira precisa reprovar sem erro de indexacao."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    with (copia / "evals" / "run_evals.py").open("a", encoding="utf-8") as arquivo:
        arquivo.write("\n\n" + retorno)
    resultado = subprocess.run(
        [sys.executable, "scripts/validate_evals.py", "--root", "."],
        cwd=copia,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "resumo" in resultado.stdout


def _executa(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/validate_evals.py", *argv],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "argv",
    [["--desconhecido"], ["--root"], ["--root="], ["--root", "  "]],
    ids=["argumento-desconhecido", "root-sem-valor", "root-vazio", "root-em-branco"],
)
def test_invalid_cli_arguments_exit_with_status_one(argv: list[str]) -> None:
    """Argumento invalido precisa reprovar com status 1 e mensagem legivel, nunca com status 2."""
    resultado = _executa(argv)
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "falhou" in resultado.stdout


def test_boolean_counts_are_not_integers(tmp_path: Path) -> None:
    """Booleano nao e contagem inteira declarada, mesmo sendo subclasse de int."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    with (copia / "evals" / "run_evals.py").open("a", encoding="utf-8") as arquivo:
        arquivo.write(
            "\n\ndef run_evaluations(*args, **kwargs):\n"
            "    return {'summary': {'total': True, 'passed': True, 'failed': False,"
            " 'invalid': False, 'not_run': False}}\n"
        )
    resultado = _executa(["--root", "."], cwd=copia)
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "contagem inteira" in resultado.stdout


def test_symlink_loop_in_root_is_reported_readably(tmp_path: Path) -> None:
    """Raiz em ciclo de links precisa reprovar com status 1 e mensagem legivel."""
    (tmp_path / "a").symlink_to("b")
    (tmp_path / "b").symlink_to("a")
    resultado = _executa(["--root", str(tmp_path / "a")])
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "inacessivel" in resultado.stdout


def test_missing_root_is_reported_readably(tmp_path: Path) -> None:
    resultado = _executa(["--root", str(tmp_path / "inexistente")])
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr


def _executa_harness(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "evals/run_evals.py", *argv],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_results_dir_that_is_not_a_directory_is_reported_readably(tmp_path: Path) -> None:
    """Item 2 da issue #64: `--results-dir` apontando para arquivo precisa reprovar com status 1.

    A guarda existe no CLI do harness; sem teste regressivo, voltar a aceitar o caminho invalido
    passaria despercebido e o modo replay seguiria sem diretorio de resultados.
    """
    alvo = tmp_path / "nao-e-diretorio.json"
    alvo.write_text("{}\n", encoding="utf-8")
    resultado = _executa_harness(["--results-dir", str(alvo)])
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "--results-dir precisa apontar para um diretorio" in resultado.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="permissao de leitura nao restringe root")
def test_unreadable_fixture_is_reported_readably(tmp_path: Path) -> None:
    """Item 2 da issue #64: fixture sem permissao de leitura precisa reprovar sem traceback.

    Exercita a guarda `fixture nao pode ser lido`, que existia sem teste. A leitura continua
    fail-closed: o gate nao pode tratar a fixture ilegivel como verificacao satisfeita.
    """
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    fixtures = sorted((copia / "evals" / "fixtures" / "results").glob("*.json"))
    assert fixtures, "o repositorio precisa ter fixtures de resultado"
    alvo = fixtures[0]
    alvo.chmod(0)
    try:
        resultado = _executa(["--root", "."], cwd=copia)
    finally:
        alvo.chmod(0o644)
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "fixture nao pode ser lido" in resultado.stdout
    assert alvo.name in resultado.stdout


@pytest.mark.skipif(os.geteuid() == 0, reason="permissao de leitura nao restringe root")
def test_unreadable_result_is_reported_readably(tmp_path: Path) -> None:
    """Item 2 da issue #64: resultado sem permissao de leitura precisa reprovar sem traceback.

    O caso alimenta a guarda `resultado nao pode ser lido` no modo replay, que antes nao tinha
    teste que a provocasse.
    """
    resultados = tmp_path / "resultados"
    shutil.copytree(ROOT / "evals" / "fixtures" / "results", resultados)
    arquivos = sorted(resultados.glob("*.json"))
    assert arquivos, "o repositorio precisa ter resultados de fixture"
    alvo = arquivos[0]
    alvo.chmod(0)
    try:
        resultado = _executa_harness(["--root", str(ROOT), "--results-dir", str(resultados)])
    finally:
        alvo.chmod(0o644)
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "resultado nao pode ser lido" in resultado.stderr
    assert alvo.name in resultado.stderr


def test_extreme_integer_manifest_is_reported_readably(tmp_path: Path) -> None:
    """Numero JSON fora do limite de digitos precisa reprovar de forma legivel."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    (copia / "evals" / "manifest.json").write_text("9" * 5000 + "\n", encoding="utf-8")
    resultado = _executa(["--root", "."], cwd=copia)
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "ilegivel" in resultado.stdout


def test_float_schema_version_is_rejected(tmp_path: Path) -> None:
    """schema_version precisa ser inteiro exato, e nao equivalente numerico."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    manifesto = json.loads((copia / "evals" / "manifest.json").read_text(encoding="utf-8"))
    manifesto["schema_version"] = 1.0
    (copia / "evals" / "manifest.json").write_text(json.dumps(manifesto), encoding="utf-8")
    resultado = _executa(["--root", "."], cwd=copia)
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "inteiro exato" in resultado.stdout


def test_case_without_category_is_reported_readably(tmp_path: Path) -> None:
    """Caso descoberto sem categoria precisa reprovar de forma legivel."""
    copia = _copia_do_repositorio(tmp_path, CANONICAL_SHIM)
    with (copia / "evals" / "run_evals.py").open("a", encoding="utf-8") as arquivo:
        arquivo.write(
            '\n\ndef discover_cases(root):\n    return [(root / "x.json", {"case_id": "V030-002-x"})]\n'
        )
    resultado = _executa(["--root", "."], cwd=copia)
    assert resultado.returncode == 1
    assert "Traceback" not in resultado.stderr
    assert "sem categoria" in resultado.stdout or "indisponivel" in resultado.stdout
