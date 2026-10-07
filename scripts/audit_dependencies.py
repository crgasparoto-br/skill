#!/usr/bin/env python3
"""Auditar vulnerabilidades nos lockfiles e aplicar a política de exceção declarada.

Este utilitário existe porque a checagem de vulnerabilidade depende de banco externo, e o
repositório trata indisponibilidade como `UNKNOWN` e nunca como sucesso. Ele roda fora da
sequência obrigatória: o gate determinístico é `scripts/validate_dependency_locks.py`.

Regras de saída:

- nenhuma vulnerabilidade fora da política: código 0;
- vulnerabilidade sem exceção declarada: código 1, com identificador e pacote;
- banco indisponível, ferramenta ausente ou saída ilegível: código 2, com `UNKNOWN` explícito,
  porque ausência de verificação não é verificação de ausência.

Vulnerabilidade coberta por exceção é reportada e não reprova, e a validade da exceção — data
de revisão incluída — é assunto de `scripts/validate_dependency_locks.py`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

POLICY_RELATIVE = "config/dependency-policy.json"
LOCK_GLOB = "*/requirements*.lock.txt"
UNKNOWN = 2


def load_exceptions(root: Path) -> dict[str, str]:
    """Mapa identificador de aviso -> pacote, a partir da política declarada."""
    path = root / POLICY_RELATIVE
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    exceptions = {}
    for item in data.get("exceptions") or []:
        if isinstance(item, dict) and item.get("id"):
            exceptions[str(item["id"]).strip()] = str(item.get("package", "")).strip().lower()
    return exceptions


def audit(lock: Path) -> tuple[dict | None, str]:
    """Rodar pip-audit sobre o lockfile. Devolve o relatório e o motivo de UNKNOWN."""
    if not shutil.which("pip-audit") and not _module_available("pip_audit"):
        return None, "pip-audit nao esta instalado"
    command = [
        sys.executable, "-m", "pip_audit",
        "--requirement", str(lock),
        "--disable-pip",
        "--format", "json",
        "--progress-spinner", "off",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode not in (0, 1):
        detail = (completed.stderr or completed.stdout).strip().splitlines()
        return None, f"pip-audit nao concluiu (codigo {completed.returncode}): {detail[-1] if detail else 'sem detalhe'}"
    try:
        return json.loads(completed.stdout), ""
    except json.JSONDecodeError:
        return None, "pip-audit produziu saida ilegivel"


def _module_available(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def findings(report: dict) -> list[dict]:
    """Normalizar o relatório do pip-audit em uma lista de achados."""
    result = []
    for dependency in report.get("dependencies") or []:
        for vulnerability in dependency.get("vulns") or []:
            result.append({
                "package": str(dependency.get("name", "")),
                "version": str(dependency.get("version", "")),
                "id": str(vulnerability.get("id", "")),
                "fix_versions": vulnerability.get("fix_versions") or [],
                "aliases": vulnerability.get("aliases") or [],
            })
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auditar vulnerabilidades nos lockfiles.")
    parser.add_argument("--root", default=".", help="raiz do repositorio")
    parser.add_argument("--report", help="gravar o relatorio normalizado em JSON")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    locks = sorted(path for path in root.glob(LOCK_GLOB) if path.is_file())
    if not locks:
        print("UNKNOWN: nenhum lockfile encontrado para auditar", file=sys.stderr)
        return UNKNOWN

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
    for finding in collected:
        identifiers = [finding["id"], *finding["aliases"]]
        (covered if any(identifier in exceptions for identifier in identifiers) else uncovered).append(finding)

    for finding in covered:
        print(f"coberto por excecao: {finding['id']} em {finding['package']}=={finding['version']} ({finding['lock']})")
    for finding in uncovered:
        fixes = ", ".join(finding["fix_versions"]) or "sem correcao publicada"
        print(f"vulnerabilidade sem excecao: {finding['id']} em {finding['package']}=={finding['version']} ({fixes})", file=sys.stderr)

    if uncovered:
        print(f"auditoria reprovada: {len(uncovered)} achado(s) fora da politica", file=sys.stderr)
        return 1

    print(f"Auditoria OK: {len(locks)} lockfile(s) verificados, {len(covered)} achado(s) cobertos por excecao.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())