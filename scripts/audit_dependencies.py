#!/usr/bin/env python3
"""Auditar lockfiles: integridade do digest e vulnerabilidade, com a política aplicada.

Este utilitário existe porque duas verificações dependem do artefato ou de banco externo, e o
repositório trata a impossibilidade de verificar como `UNKNOWN` e nunca como sucesso. Ele roda
fora da sequência obrigatória; o gate determinístico é `scripts/validate_dependency_locks.py`,
que verifica forma, vínculo entre nome, versão, artefato e digest, satisfação do especificador
e política, sem tocar a rede.

Verificações daqui:

- **integridade**: `pip download --require-hashes` sobre cada lockfile obtém o artefato e
  confere o digest. Hash que não corresponde à distribuição reprova, porque um digest
  arbitrário com formato válido só é detectável com o artefato em mãos;
- **vulnerabilidade**: `pip-audit` sobre cada lockfile, com a política de exceção aplicada.

A exceção precisa casar identificador **e** pacote **e** versão do achado. Exceção cujo
identificador não aparece em nenhum achado reprova: ela tolera algo que o banco não reporta, e
isso é ou erro de digitação ou aviso retirado.

Códigos de saída: 0 aprovado; 1 achado fora da política, digest divergente ou exceção órfã;
2 `UNKNOWN`, quando não é possível verificar — banco indisponível, ferramenta ausente ou saída
ilegível —, porque ausência de verificação não é verificação de ausência.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.lock_dependencies import normalize

POLICY_RELATIVE = "config/dependency-policy.json"
LOCK_GLOB = "*/requirements*.lock.txt"
UNKNOWN = 2
# Marca de divergência de digest do próprio pip; qualquer outra falha é `UNKNOWN`, porque
# classificar uma falha desconhecida como defeito do candidato seria fabricar evidência.
INTEGRITY_FAILURE_MARKERS = ("do not match the hashes", "hashmismatch", "these packages do not match")


def load_exceptions(root: Path) -> list[dict]:
    """Exceções declaradas, com identificador, pacote e versão."""
    path = root / POLICY_RELATIVE
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    exceptions = []
    for item in data.get("exceptions") or []:
        if isinstance(item, dict) and item.get("id"):
            exceptions.append({
                "id": str(item["id"]).strip(),
                "package": normalize(str(item.get("package", ""))),
                "version": str(item.get("version", "")).strip(),
            })
    return exceptions


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def verify_artifacts(lock: Path) -> tuple[bool, str]:
    """Conferir o digest de cada entrada contra o artefato real.

    Devolve (verificado, motivo). Motivo preenchido significa `UNKNOWN`.
    """
    with tempfile.TemporaryDirectory() as tmp:
        completed = run([
            sys.executable, "-m", "pip", "download",
            "--quiet", "--no-deps", "--require-hashes",
            "--dest", tmp, "-r", str(lock),
        ])
    if completed.returncode == 0:
        return True, ""
    output = f"{completed.stdout}\n{completed.stderr}".lower()
    if any(marker.lower() in output for marker in INTEGRITY_FAILURE_MARKERS):
        return False, ""
    detail = (completed.stderr or completed.stdout).strip().splitlines()
    return False, f"nao foi possivel verificar o digest: {detail[-1] if detail else 'sem detalhe'}"


def audit(lock: Path) -> tuple[dict | None, str]:
    """Rodar pip-audit sobre o lockfile. Devolve o relatório e o motivo de UNKNOWN."""
    if not shutil.which("pip-audit") and not module_available("pip_audit"):
        return None, "pip-audit nao esta instalado"
    completed = run([
        sys.executable, "-m", "pip_audit",
        "--requirement", str(lock),
        "--disable-pip",
        "--format", "json",
        "--progress-spinner", "off",
    ])
    if completed.returncode not in (0, 1):
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        return None, f"pip-audit nao concluiu (codigo {completed.returncode}): {detail[-1] if detail else 'sem detalhe'}"
    try:
        return json.loads(completed.stdout), ""
    except json.JSONDecodeError:
        return None, "pip-audit produziu saida ilegivel"


def findings(report: dict) -> list[dict]:
    """Normalizar o relatório do pip-audit em uma lista de achados."""
    result = []
    for dependency in report.get("dependencies") or []:
        for vulnerability in dependency.get("vulns") or []:
            result.append({
                "package": normalize(str(dependency.get("name", ""))),
                "version": str(dependency.get("version", "")),
                "id": str(vulnerability.get("id", "")),
                "aliases": [str(alias) for alias in vulnerability.get("aliases") or []],
                "fix_versions": vulnerability.get("fix_versions") or [],
            })
    return result


def matching_exception(finding: dict, exceptions: list[dict]) -> dict | None:
    """Exceção casa identificador, pacote e versão; só o identificador não basta."""
    identifiers = {finding["id"], *finding["aliases"]}
    for exception in exceptions:
        if exception["id"] not in identifiers:
            continue
        if exception["package"] != finding["package"]:
            continue
        if exception["version"] and exception["version"] != finding["version"]:
            continue
        return exception
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auditar integridade e vulnerabilidade dos lockfiles.")
    parser.add_argument("--root", default=".", help="raiz do repositorio")
    parser.add_argument("--report", help="gravar o relatorio normalizado em JSON")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    locks = sorted(path for path in root.glob(LOCK_GLOB) if path.is_file())
    if not locks:
        print("UNKNOWN: nenhum lockfile encontrado para auditar", file=sys.stderr)
        return UNKNOWN

    failures: list[str] = []
    for lock in locks:
        verified, unknown_reason = verify_artifacts(lock)
        if unknown_reason:
            print(f"UNKNOWN: {unknown_reason} ({lock.relative_to(root).as_posix()})", file=sys.stderr)
            return UNKNOWN
        if not verified:
            failures.append(f"digest nao corresponde ao artefato em {lock.relative_to(root).as_posix()}")

    exceptions = load_exceptions(root)
    collected: list[dict] = []
    for lock in locks:
        report, reason = audit(lock)
        if report is None:
            print(f"UNKNOWN: {reason} ({lock.relative_to(root).as_posix()})", file=sys.stderr)
            return UNKNOWN
        for finding in findings(report):
            finding["lock"] = lock.relative_to(root).as_posix()
            collected.append(finding)

    if args.report:
        Path(args.report).write_text(json.dumps(collected, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    covered, uncovered = [], []
    matched: set[int] = set()
    for finding in collected:
        exception = matching_exception(finding, exceptions)
        if exception is None:
            uncovered.append(finding)
        else:
            covered.append(finding)
            matched.add(id(exception))

    for finding in covered:
        print(f"coberto por excecao: {finding['id']} em {finding['package']}=={finding['version']} ({finding['lock']})")
    for finding in uncovered:
        fixes = ", ".join(finding["fix_versions"]) or "sem correcao publicada"
        print(
            f"vulnerabilidade sem excecao: {finding['id']} em {finding['package']}=={finding['version']} ({fixes})",
            file=sys.stderr,
        )

    orphan = sorted(exception["id"] for exception in exceptions if id(exception) not in matched)
    for identifier in orphan:
        print(f"excecao sem aviso correspondente: {identifier}", file=sys.stderr)

    for failure in failures:
        print(f"integridade reprovada: {failure}", file=sys.stderr)

    if failures or uncovered or orphan:
        print(
            f"auditoria reprovada: {len(failures)} falha(s) de integridade, "
            f"{len(uncovered)} achado(s) fora da politica, {len(orphan)} excecao(oes) sem aviso correspondente",
            file=sys.stderr,
        )
        return 1

    print(
        f"Auditoria OK: {len(locks)} lockfile(s) verificados, {len(covered)} achado(s) cobertos por excecao, "
        "digest conferido contra o artefato."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
