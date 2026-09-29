#!/usr/bin/env python3
"""Run or validate versioned behavioral-evaluation cases."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import selectors
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
MAX_PROVIDER_OUTPUT_BYTES = 1_000_000


class HarnessError(ValueError):
    """Raised when the harness inputs or its own contracts are invalid."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"{label} inválido: {exc}") from exc
    if not isinstance(value, dict):
        raise HarnessError(f"{label} deve conter um objeto JSON")
    return value


def load_schema(root: Path, name: str) -> dict[str, Any]:
    return load_json(root / "evals" / "schemas" / name, f"schema {name}")


def schema_errors(value: Any, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors: list[str] = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path)):
        path = ".".join(str(part) for part in error.path) or "$"
        errors.append(f"{path}: {error.message}")
    return errors


def load_harness_manifest(root: Path) -> dict[str, Any]:
    manifest = load_json(root / "evals" / "manifest.json", "evals/manifest.json")
    errors = schema_errors(manifest, load_schema(root, "eval-manifest.schema.json"))
    if errors:
        raise HarnessError("evals/manifest.json: " + "; ".join(errors))
    return manifest


def discover_cases(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    cases_dir = root / "evals" / "cases"
    if not cases_dir.is_dir():
        raise HarnessError("evals/cases ausente")
    paths = sorted(cases_dir.glob("*.json"))
    if not paths:
        raise HarnessError("nenhum caso JSON encontrado em evals/cases")
    schema = load_schema(root, "eval-case.schema.json")
    cases: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for path in paths:
        case = load_json(path, f"caso {path}")
        errors = schema_errors(case, schema)
        if errors:
            raise HarnessError(f"caso {path}: " + "; ".join(errors))
        case_id = str(case["case_id"])
        if case_id in seen:
            raise HarnessError(f"case_id duplicado: {case_id}")
        seen.add(case_id)
        cases.append((path, case))
    return cases


def _record(case: dict[str, Any], status: str, observed: str | None, *reasons: str) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "status": status,
        "expected_outcome": case["expected"]["outcome"],
        "observed_outcome": observed,
        "reasons": list(reasons),
    }


def _attestation_payload(result: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(result)
    payload["runtime"]["attestation"] = None
    return payload


def _trust_errors(case: dict[str, Any], result: dict[str, Any], *, allow_fixture: bool) -> list[str]:
    runtime = result["runtime"]
    provider = runtime["provider"]
    trust = runtime["trust"]
    errors: list[str] = []
    if provider != "fixture" and not runtime.get("model"):
        errors.append("runtime.model é obrigatório para provider diferente de fixture")
    if trust == "fixture":
        if not allow_fixture or provider != "fixture" or case["case_id"] != "V030-001-runner-contract-001":
            errors.append("trust=fixture só é permitido para o fixture canônico V030-001-runner-contract-001")
        if runtime["attestation"] is not None:
            errors.append("fixture não deve declarar attestation")
    elif trust == "attested":
        attestation = runtime["attestation"]
        if not isinstance(attestation, dict):
            errors.append("trust=attested exige attestation")
        else:
            if attestation["case_id"] != case["case_id"]:
                errors.append("attestation.case_id diverge do caso")
            if attestation["result_sha256"] != sha256_json(_attestation_payload(result)):
                errors.append("attestation.result_sha256 não corresponde ao resultado")
    elif trust == "provider-untrusted" and runtime["attestation"] is not None:
        errors.append("provider-untrusted não pode declarar attestation")
    return errors


def validate_result_payload(case: dict[str, Any], result: Any, schema: dict[str, Any], *, allow_fixture: bool) -> list[str]:
    errors = schema_errors(result, schema)
    if errors:
        return errors
    assert isinstance(result, dict)
    runtime = result["runtime"]
    if result["case_id"] != case["case_id"]:
        errors.append("result.case_id diverge do case_id solicitado")
    if runtime["adapter"] != case["adapter"]:
        errors.append("runtime.adapter diverge do adapter do caso")
    errors.extend(_trust_errors(case, result, allow_fixture=allow_fixture))
    return errors


def evaluate_result(
    case: dict[str, Any],
    result: dict[str, Any] | None,
    *,
    reason: str | None = None,
    source_mode: str,
) -> dict[str, Any]:
    if result is None:
        return _record(case, "NOT_RUN", None, reason or "runtime não produziu resultado")

    runtime = result["runtime"]
    if runtime["status"] != "available":
        return _record(case, "NOT_RUN", result["outcome"], f"runtime indisponível: {runtime['status']}")
    if source_mode == "provider" or runtime["trust"] == "provider-untrusted":
        return _record(case, "NOT_RUN", result["outcome"], "resultado de provider-command não é uma atestação confiável")
    if runtime["trust"] == "attested":
        return _record(case, "NOT_RUN", result["outcome"], "verificador criptográfico de atestação ainda não está habilitado")

    expected = case["expected"]
    observed = result["outcome"]
    reasons: list[str] = []
    if observed != expected["outcome"]:
        reasons.append(f"outcome esperado {expected['outcome']}, observado {observed}")
    if result["selected_skill"] != expected["selected_skill"]:
        reasons.append("selected_skill diverge do caso")
    if result["loaded_references"] != expected["loaded_references"]:
        reasons.append("loaded_references diverge do caso")
    forbidden = set(expected["forbidden_actions"]) & set(result["actions"])
    if forbidden:
        reasons.append("ações proibidas observadas: " + ", ".join(sorted(forbidden)))
    missing_evidence = set(expected["required_evidence"]) - set(result["evidence"])
    if missing_evidence:
        reasons.append("evidências obrigatórias ausentes: " + ", ".join(sorted(missing_evidence)))

    response_minimum = expected["response_minimum"]
    response_text = result["response_text"]
    if len(response_text) < response_minimum["min_chars"]:
        reasons.append("response_text abaixo do mínimo de caracteres")
    missing_markers = [marker for marker in response_minimum["required_markers"] if marker.casefold() not in response_text.casefold()]
    if missing_markers:
        reasons.append("marcadores ausentes em response_text: " + ", ".join(missing_markers))

    metrics = result["metrics"]
    budgets = case["budgets"]
    for key, label in (
        ("external_calls", "chamadas externas"),
        ("duration_ms", "duração"),
        ("context_chars", "contexto"),
    ):
        if metrics[key] > budgets[f"max_{key}"]:
            reasons.append(f"orçamento excedido para {label}: {metrics[key]} > {budgets[f'max_{key}']}")

    return _record(case, "PASS" if not reasons else "FAIL", observed, *(reasons or ["resultado observável compatível com o contrato"]))


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def invoke_provider(command: str, case: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, int]:
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return None, f"provider-command inválido: {exc}", 0
    if not argv:
        return None, "provider-command vazio", 0

    started = time.monotonic()
    input_bytes = (canonical_json(case) + "\n").encode("utf-8")
    try:
        with tempfile.TemporaryDirectory(prefix="skill-eval-provider-") as workdir:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                start_new_session=True,
            )
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            try:
                process.stdin.write(input_bytes)
                process.stdin.close()
            except BrokenPipeError:
                pass

            stdout = bytearray()
            stderr = bytearray()
            deadline = started + (case["budgets"]["max_duration_ms"] / 1000)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        _terminate_process_group(process)
                        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
                        return None, "provider indisponível: timeout excedido", elapsed_ms
                    events = selector.select(remaining)
                    if not events:
                        _terminate_process_group(process)
                        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
                        return None, "provider indisponível: timeout excedido", elapsed_ms
                    for key, _ in events:
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if key.data == "stdout":
                            stdout.extend(chunk)
                            if len(stdout) > MAX_PROVIDER_OUTPUT_BYTES:
                                _terminate_process_group(process)
                                elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
                                return None, "provider-result-invalid: stdout excedeu o limite", elapsed_ms
                        elif len(stderr) < MAX_PROVIDER_OUTPUT_BYTES:
                            stderr.extend(chunk[: MAX_PROVIDER_OUTPUT_BYTES - len(stderr)])
            _terminate_process_group(process)
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
                return None, "provider indisponível: processo não encerrou após fechar streams", elapsed_ms
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"provider indisponível: {exc}", max(0, int((time.monotonic() - started) * 1000))

    elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
    if process.returncode != 0:
        detail = bytes(stderr).decode("utf-8", errors="replace").strip() or f"exit code {process.returncode}"
        return None, f"provider falhou: {detail}", elapsed_ms
    try:
        result = json.loads(bytes(stdout).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"provider-result-invalid: JSON inválido: {exc}", elapsed_ms
    if not isinstance(result, dict):
        return None, "provider-result-invalid: saída deve ser um objeto JSON", elapsed_ms
    if isinstance(result.get("metrics"), dict):
        result["metrics"]["duration_ms"] = elapsed_ms
    return result, None, elapsed_ms


def load_result(path: Path, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    try:
        result = load_json(path, f"resultado {path}")
    except HarnessError as exc:
        return None, str(exc)
    errors = schema_errors(result, schema)
    if errors:
        return None, f"resultado {path}: " + "; ".join(errors)
    return result, None


def report_for(harness_version: str, mode: str, cases: list[tuple[Path, dict[str, Any]]], records: list[dict[str, Any]], inputs: list[Any]) -> dict[str, Any]:
    release_versions = sorted({str(case["release_version"]) for _, case in cases})
    run_id = sha256_json({"harness_version": harness_version, "mode": mode, "inputs": inputs})
    summary = {
        "total": len(records),
        "passed": sum(record["status"] == "PASS" for record in records),
        "failed": sum(record["status"] == "FAIL" for record in records),
        "not_run": sum(record["status"] == "NOT_RUN" for record in records),
        "invalid": sum(record["status"] == "INVALID" for record in records),
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "harness_version": harness_version,
        "mode": mode,
        "release_versions": release_versions,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "content_sha256": "",
        "cases": records,
        "summary": summary,
    }
    digest_input = {key: value for key, value in report.items() if key not in {"generated_at", "content_sha256"}}
    report["content_sha256"] = sha256_json(digest_input)
    return report


def _validate_report_consistency(report: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors = schema_errors(report, schema)
    if errors:
        return errors
    digest_input = {key: value for key, value in report.items() if key not in {"generated_at", "content_sha256"}}
    if report["content_sha256"] != sha256_json(digest_input):
        errors.append("content_sha256 diverge do conteúdo lógico do relatório")
    records = report["cases"]
    expected_summary = {
        "total": len(records),
        "passed": sum(record["status"] == "PASS" for record in records),
        "failed": sum(record["status"] == "FAIL" for record in records),
        "not_run": sum(record["status"] == "NOT_RUN" for record in records),
        "invalid": sum(record["status"] == "INVALID" for record in records),
    }
    if report["summary"] != expected_summary:
        errors.append("summary não corresponde aos status dos casos")
    case_ids = [record["case_id"] for record in records]
    if len(case_ids) != len(set(case_ids)):
        errors.append("relatório contém case_id duplicado")
    return errors


def verify_report(root: Path, report_path: Path) -> list[str]:
    try:
        report = load_json(report_path, f"relatório {report_path}")
    except HarnessError as exc:
        return [str(exc)]
    return _validate_report_consistency(report, load_schema(root, "eval-report.schema.json"))


def run_evaluations(
    root: Path,
    *,
    results_dir: Path | None = None,
    provider_command: str | None = None,
    provider_id: str = "untrusted-command",
    validate_only: bool = False,
) -> dict[str, Any]:
    if results_dir is not None and provider_command is not None:
        raise HarnessError("use apenas um entre --results-dir e --provider-command")
    manifest = load_harness_manifest(root)
    cases = discover_cases(root)
    result_schema = load_schema(root, "eval-result.schema.json")
    mode = "validate-only" if validate_only else "replay" if results_dir is not None else "provider"
    records: list[dict[str, Any]] = []
    inputs: list[Any] = []

    expected_result_names = {f"{case['case_id']}.json" for _, case in cases}
    if results_dir is not None and results_dir.is_dir():
        extras = sorted(path.name for path in results_dir.iterdir() if path.name not in expected_result_names)
        if extras:
            raise HarnessError("resultados sem caso correspondente: " + ", ".join(extras))
        non_regular = sorted(
            path.name
            for path in results_dir.iterdir()
            if path.name in expected_result_names and (path.is_symlink() or not path.is_file())
        )
        if non_regular:
            raise HarnessError("resultados esperados devem ser arquivos regulares: " + ", ".join(non_regular))

    canonical_fixture_dir = (root / "evals" / "fixtures" / "results").resolve()
    allow_fixture = results_dir is not None and results_dir.resolve() == canonical_fixture_dir

    for _, case in cases:
        inputs.append({"case_id": case["case_id"], "case_sha256": sha256_json(case)})
        if validate_only:
            records.append(_record(case, "NOT_RUN", None, "modo validate-only não executa runtime"))
            continue

        result: dict[str, Any] | None = None
        error: str | None = None
        source_mode = mode
        if results_dir is not None:
            result_path = results_dir / f"{case['case_id']}.json"
            if result_path.is_symlink():
                raise HarnessError(f"resultado esperado não pode ser symlink: {result_path.name}")
            if result_path.is_file():
                result, error = load_result(result_path, result_schema)
                inputs.append({"case_id": case["case_id"], "result_sha256": sha256_bytes(result_path.read_bytes())})
            else:
                error = f"runtime não produziu resultado: {result_path.name}"
                inputs.append({"case_id": case["case_id"], "result_sha256": None})
        elif provider_command is not None:
            result, error, elapsed_ms = invoke_provider(provider_command, case)
            inputs.append({"case_id": case["case_id"], "provider_id": provider_id, "elapsed_ms": elapsed_ms, "result_sha256": sha256_json(result) if result is not None else None})
        else:
            error = "nenhum runtime fornecido; use --results-dir ou --provider-command"
            inputs.append({"case_id": case["case_id"], "result_sha256": None})

        if result is not None:
            result_errors = validate_result_payload(case, result, result_schema, allow_fixture=allow_fixture)
            if result_errors:
                records.append(_record(case, "INVALID", result.get("outcome"), *result_errors))
                continue
        elif error and (error.startswith("resultado ") or error.startswith("provider-result-invalid:")):
            records.append(_record(case, "INVALID", None, error))
            continue
        records.append(evaluate_result(case, result, reason=error, source_mode=source_mode))

    report = report_for(manifest["harness_version"], mode, cases, records, inputs)
    report_errors = _validate_report_consistency(report, load_schema(root, "eval-report.schema.json"))
    if report_errors:
        raise HarnessError("relatório inválido: " + "; ".join(report_errors))
    return report


def _write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--provider-command")
    parser.add_argument("--provider-id", default="untrusted-command")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.verify_report:
        report_path = args.verify_report if args.verify_report.is_absolute() else root / args.verify_report
        errors = verify_report(root, report_path)
        if errors:
            print("REPORT_INVALID: " + "; ".join(errors), file=sys.stderr)
            return 1
        print("Evaluation report verification OK.")
        return 0

    try:
        report = run_evaluations(
            root,
            results_dir=(root / args.results_dir if args.results_dir and not args.results_dir.is_absolute() else args.results_dir),
            provider_command=args.provider_command,
            provider_id=args.provider_id,
            validate_only=args.validate_only,
        )
    except HarnessError as exc:
        print(f"EVAL_HARNESS_ERROR: {exc}", file=sys.stderr)
        return 1

    if args.report:
        report_path = args.report if args.report.is_absolute() else root / args.report
        _write_report(report, report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.validate_only:
        return 0
    if report["summary"]["invalid"] or report["summary"]["failed"]:
        return 1
    if report["summary"]["not_run"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
