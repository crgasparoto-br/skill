#!/usr/bin/env python3
"""Valida a politica e as garantias do contrato de handoff de release.

O contrato existe para tornar a passagem `develop` -> `main` verificavel sem conceder autoridade de merge.
Este validador confere que a politica declara a evidencia exigida com motivo, que nenhum item se repete,
que o contrato nao declara autoridade de merge, tag ou publicacao e que o proprio script nao executa essas
acoes. Tambem exercita o contrato sobre uma evidencia sintetica, para provar que ele aprova e reprova.
"""
from __future__ import annotations

import argparse
import ast
import json
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
ALLOWED_IMPORTS = frozenset({"__future__", "argparse", "json", "re", "stat", "sys", "unicodedata", "pathlib", "typing"})
FORBIDDEN_PRIMITIVES = frozenset(
    {
        "__builtins__",
        "__import__",
        "check_output",
        "eval",
        "exec",
        "getattr",
        "globals",
        "importlib",
        "locals",
        "modules",
        "open",
        "os",
        "popen",
        "setattr",
        "spawn",
        "subprocess",
        "system",
        "vars",
    }
)
REQUIRED_IDS = frozenset(
    {"issues-delivered", "develop-sha", "gates", "independent-audit", "divergence"}
)
SHA_DEVELOP = "a" * 40
SCHEMA_VERSION = 1
POLICY_VERSION = 1


def exact_version(value: object, expected: int) -> bool:
    """A versão declarada precisa ser o inteiro exato: `True` e `1.0` não são a versão 1."""
    return isinstance(value, int) and not isinstance(value, bool) and value == expected
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


def confined_errors(root: Path, path: Path, label: str) -> list[str]:
    """Arquivo do contrato precisa ser regular, sem componente simbolico e dentro da raiz auditada.

    O caminho final regular nao basta: `config -> ../../fora/config` mantem o arquivo final regular e
    leva a inspecao para fora da arvore do commit auditado, inclusive entre a leitura e a execucao.
    """
    for component in [*reversed(path.parents), path]:
        if component.is_symlink():
            return [f"`{label}` passa por link simbolico: {component}"]
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        return [f"`{label}` resolve para fora da raiz auditada: {resolved}"]
    return []


def policy_errors(policy: dict) -> list[str]:
    """Problemas da politica declarada."""
    errors = []
    if not exact_version(policy.get("policy_version"), POLICY_VERSION):
        errors.append("a politica nao declara `policy_version` como o inteiro 1")
    errors.extend(authority_errors(policy))
    errors.extend(item_errors(policy, "required"))
    errors.extend(item_errors(policy, "optional"))
    errors.extend(cross_section_errors(policy))
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


def cross_section_errors(policy: dict) -> list[str]:
    """Identificador precisa ser unico entre a evidencia obrigatoria e a opcional."""
    required = {item.get("id") for item in policy.get("required", []) if isinstance(item, dict)}
    optional = {item.get("id") for item in policy.get("optional", []) if isinstance(item, dict)}
    return [
        f"identificador repetido entre obrigatorios e opcionais: `{item}`"
        for item in sorted(required & optional)
    ]


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
    """O contrato nao pode executar merge, tag ou publicacao, nem adquirir esse poder em execucao.

    A prova tem tres partes: nenhum comando proibido no texto, nenhuma importacao fora da lista
    permitida e nenhuma primitiva de importacao ou execucao dinamica no codigo. Sem a terceira parte,
    `importlib.import_module("subprocess")` passaria pelas duas primeiras.
    """
    path = root / SCRIPT_RELATIVE
    errors = confined_errors(root, path, SCRIPT_RELATIVE)
    if errors or not path.is_file():
        return errors or [f"o contrato de handoff nao existe: {SCRIPT_RELATIVE}"]
    text = path.read_text(encoding="utf-8")
    errors += [
        f"o contrato de handoff menciona comando proibido: `{command}`"
        for command in FORBIDDEN_COMMANDS
        if command in text
    ]
    try:
        tree = ast.parse(text)
    except SyntaxError as error:
        return [*errors, f"o contrato de handoff nao e Python valido: {error}"]
    errors.extend(import_errors(tree))
    errors.extend(dynamic_errors(tree))
    return errors


def import_errors(tree: ast.Module) -> list[str]:
    """Toda importacao do contrato precisa estar na lista permitida."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module.split(".")[0])
    return [
        f"o contrato de handoff importa `{name}`, fora da lista permitida de {sorted(ALLOWED_IMPORTS)}"
        for name in sorted(set(names) - ALLOWED_IMPORTS)
    ]


def dynamic_errors(tree: ast.Module) -> list[str]:
    """Primitivas de importacao e execucao dinamica sao proibidas em qualquer forma que aparecam.

    Cobrir apenas `ast.Name` deixa passar acesso indireto, como
    `getattr(__builtins__, "__import__")("subprocess")` ou `pathlib.os.system(...)`. Por isso o nome
    proibido tambem e recusado como atributo acessado e como texto exato no codigo: sem primitiva
    alguma, o contrato nao adquire autoridade de execucao, mesmo que tente.
    """
    used: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_PRIMITIVES:
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            # Atributo reservado e a via de introspeccao: `__globals__` alcanca builtins e
            # `_getframe` alcanca o quadro de execucao, que tambem entrega as builtins.
            if node.attr in FORBIDDEN_PRIMITIVES or node.attr.startswith("_"):
                used.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in FORBIDDEN_PRIMITIVES:
            used.add(node.value)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_PRIMITIVES:
            used.add(node.func.id)
    return [
        f"o contrato de handoff usa `{name}`, que permite adquirir autoridade em execucao"
        for name in sorted(used)
    ]


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
    errors = confined_errors(root, path, POLICY_RELATIVE)
    if errors or not path.is_file():
        return errors or [f"a politica do handoff nao existe: {POLICY_RELATIVE}"]
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"nao foi possivel ler {POLICY_RELATIVE}: {error}"]
    if not isinstance(policy, dict):
        return [f"{POLICY_RELATIVE} nao contem um objeto JSON"]
    return errors + policy_errors(policy) + script_errors(root) + behaviour_errors(root)


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
