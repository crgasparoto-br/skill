#!/usr/bin/env python3
"""Valida a politica e as garantias do contrato de handoff de release.

O contrato existe para tornar a passagem `develop` -> `main` verificavel sem conceder autoridade de merge.
Este validador confere que a politica declara a evidencia exigida com motivo, que nenhum item se repete,
que o contrato nao declara autoridade de merge, tag ou publicacao e que o proprio script nao executa essas
acoes. Tambem exercita o contrato sobre uma evidencia sintetica, para provar que ele aprova e reprova.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

POLICY_RELATIVE = "config/release-handoff.json"
SCRIPT_RELATIVE = "scripts/release_handoff.py"
FORBIDDEN_COMMANDS = (
    "gh pr merge",
    "gh release",
    "git push",
    "git tag",
    "git merge",
    "git commit",
)
REQUIRED_IDS = frozenset(
    {"issues-delivered", "develop-sha", "gates", "independent-audit", "divergence"}
)
SHA_DEVELOP = "a" * 40
SHA_MAIN = "b" * 40


def load_object(path: Path) -> dict:
    """Le um JSON de objeto, falhando fechado."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERRO: nao foi possivel ler {path}: {error}") from error
    if not isinstance(document, dict):
        raise SystemExit(f"ERRO: {path} nao contem um objeto JSON")
    return document


def policy_errors(policy: dict) -> list[str]:
    """Problemas da politica declarada."""
    errors = []
    if policy.get("policy_version") != 1:
        errors.append("a politica nao declara `policy_version` 1")
    errors.extend(authority_errors(policy))
    errors.extend(item_errors(policy, "required"))
    errors.extend(item_errors(policy, "optional"))
    errors.extend(missing_required_errors(policy))
    errors.extend(verdict_errors(policy))
    return errors


def authority_errors(policy: dict) -> list[str]:
    """O contrato nao pode declarar autoridade de merge, tag ou publicacao."""
    authority = policy.get("authority")
    if not isinstance(authority, dict):
        return ["a politica nao declara o bloco `authority`"]
    errors = []
    for key in ("merges", "tags", "publishes"):
        if authority.get(key) is not False:
            errors.append(f"a politica precisa declarar `authority.{key}` como falso")
    return errors


def item_errors(policy: dict, key: str) -> list[str]:
    """Itens declarados precisam de identificador unico, descricao e motivo."""
    items = policy.get(key)
    if not isinstance(items, list):
        return [f"a politica nao declara a lista `{key}`"]
    errors = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            errors.append(f"item de `{key}` nao e um objeto")
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            errors.append(f"item de `{key}` sem identificador")
            continue
        if item_id in seen:
            errors.append(f"identificador repetido em `{key}`: `{item_id}`")
        seen.add(item_id)
        for field in ("description", "reason"):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"item `{item_id}` sem `{field}`")
    return errors


def missing_required_errors(policy: dict) -> list[str]:
    """A evidencia exigida pelo contrato precisa estar declarada na politica."""
    declared = {
        item.get("id")
        for item in policy.get("required", [])
        if isinstance(item, dict)
    }
    return [f"a politica nao declara o item obrigatorio `{item}`" for item in sorted(REQUIRED_IDS - declared)]


def verdict_errors(policy: dict) -> list[str]:
    """Os pareceres de auditoria aceitos precisam estar declarados."""
    verdicts = policy.get("verdicts")
    approved = verdicts.get("audit_approved") if isinstance(verdicts, dict) else None
    if not isinstance(approved, list) or not approved:
        return ["a politica nao declara `verdicts.audit_approved`"]
    return [f"parecer invalido em `verdicts.audit_approved`: {item!r}" for item in approved if not isinstance(item, str)]


def script_errors(root: Path) -> list[str]:
    """O contrato nao pode executar merge, tag ou publicacao."""
    path = root / SCRIPT_RELATIVE
    if not path.is_file():
        return [f"o contrato de handoff nao existe: {SCRIPT_RELATIVE}"]
    text = path.read_text(encoding="utf-8")
    errors = []
    for command in FORBIDDEN_COMMANDS:
        if command in text:
            errors.append(f"o contrato de handoff menciona comando proibido: `{command}`")
    for call in ("subprocess", "os.system"):
        if re.search(rf"^\s*(import|from)\s+{call.split('.')[0]}\b", text, re.MULTILINE) and call in text:
            errors.append(f"o contrato de handoff usa `{call}`, que permite executar comando externo")
    return errors


def synthetic_evidence(verdict: str, develop: str, main: str) -> dict:
    """Evidencia sintetica completa, usada para exercitar o contrato."""
    return {
        "schema_version": 1,
        "main": main,
        "items": {
            "issues-delivered": {"value": "45", "source": "github"},
            "develop-sha": {"value": develop, "source": "git"},
            "gates": {"value": "ok", "source": "local"},
            "independent-audit": {"value": verdict, "source": "auditar-issue"},
            "divergence": {"value": "sim", "source": "git"},
        },
    }


def run_contract(root: Path, evidence: dict, develop: str, main: str) -> tuple[int, str]:
    """Executa o contrato sobre uma evidencia e devolve codigo de saida e saida padrao."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "evidence.json"
        path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
        # O comando usa o interpretador atual e o caminho do proprio repositorio, sem entrada de usuario.
        result = subprocess.run(
            [
                sys.executable,
                str(root / SCRIPT_RELATIVE),
                "--root",
                str(root),
                "--evidence",
                str(path),
                "--develop",
                develop,
                "--main",
                main,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    return result.returncode, result.stdout


def behaviour_errors(root: Path) -> list[str]:
    """O contrato precisa aprovar evidencia completa e reprovar cada falta."""
    errors = []
    code, output = run_contract(
        root, synthetic_evidence("approved", SHA_DEVELOP, SHA_MAIN), SHA_DEVELOP, SHA_MAIN
    )
    if code != 0:
        errors.append(f"o contrato reprovou evidencia completa: {output.strip()}")
    code, _ = run_contract(root, synthetic_evidence("rejected", SHA_DEVELOP, SHA_MAIN), SHA_DEVELOP, SHA_MAIN)
    if code == 0:
        errors.append("o contrato aprovou auditoria nao aprovada")
    code, _ = run_contract(root, synthetic_evidence("approved", SHA_DEVELOP, SHA_DEVELOP), SHA_DEVELOP, SHA_DEVELOP)
    if code == 0:
        errors.append("o contrato aprovou `develop` igual a `main`")
    incomplete = synthetic_evidence("approved", SHA_DEVELOP, SHA_MAIN)
    incomplete["items"].pop("gates")
    code, _ = run_contract(root, incomplete, SHA_DEVELOP, SHA_MAIN)
    if code == 0:
        errors.append("o contrato aprovou evidencia obrigatoria ausente")
    unknown = synthetic_evidence("approved", SHA_DEVELOP, SHA_MAIN)
    unknown["items"]["extra"] = {"value": "x", "source": "manual"}
    code, _ = run_contract(root, unknown, SHA_DEVELOP, SHA_MAIN)
    if code == 0:
        errors.append("o contrato aprovou identificador desconhecido")
    return errors


def validate_release_handoff(root: Path) -> list[str]:
    """Erros de politica, de garantia e de comportamento do contrato de handoff.

    Ponto de entrada do validador agregado: a politica precisa existir, declarar a evidencia exigida com
    motivo, nao conceder autoridade de merge, tag ou publicacao, e o contrato precisa aprovar evidencia
    completa e reprovar cada falta.
    """
    path = root / POLICY_RELATIVE
    if not path.is_file():
        return [f"a politica do handoff nao existe: {POLICY_RELATIVE}"]
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"nao foi possivel ler {POLICY_RELATIVE}: {error}"]
    if not isinstance(policy, dict):
        return [f"{POLICY_RELATIVE} nao contem um objeto JSON"]
    return policy_errors(policy) + script_errors(root) + behaviour_errors(root)


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Argumentos do validador."""
    parser = argparse.ArgumentParser(description="Valida a politica do handoff de release.")
    parser.add_argument("--root", type=Path, default=Path(), help="Raiz do repositorio.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Valida politica e garantias do contrato, devolvendo 0 quando tudo passa."""
    arguments = parse_arguments(argv)
    root = arguments.root.resolve()
    errors = validate_release_handoff(root)
    if errors:
        for error in errors:
            print(f"ERRO: {error}")
        print(f"Handoff de release invalido: {len(errors)} erro(s).")
        return 1
    required = len(load_object(root / POLICY_RELATIVE).get("required", []))
    print(f"Handoff de release OK: {required} item(ns) obrigatorio(s) verificado(s), sem autoridade de merge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
