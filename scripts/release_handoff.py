#!/usr/bin/env python3
"""Contrato executavel de handoff de release, sem autoridade de merge.

Reune a evidencia exigida pela politica, verifica cada item e reprova quando falta evidencia obrigatoria,
quando um identificador e desconhecido, quando o commit nao e hexadecimal de 40 caracteres, quando
`develop` e `main` sao iguais ou quando a auditoria independente nao esta aprovada.

O script nao executa merge, nao cria tag e nao publica release: ele so verifica o que foi declarado, para
que a passagem `develop` -> `main` deixe de ser o unico trecho do processo sem contrato auditavel.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
POLICY_RELATIVE = "config/release-handoff.json"
IGNORED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Zs"})
REQUIRED_IDS = frozenset(
    {"issues-delivered", "develop-sha", "gates", "independent-audit", "divergence"}
)
SCHEMA_VERSION = 1


def significant(text: object) -> str:
    """Conteudo significativo: descarta espaco e caracteres de controle e de formato.

    `str.strip()` nao remove ZERO WIDTH SPACE nem outros controles de formato, que passariam como
    evidencia valida. Aqui, espaco (`Zs`/`Zl`/`Zp`) e controle/formato (`Cc`/`Cf`) deixam de contar.
    """
    if not isinstance(text, str):
        return ""
    kept = "".join(character for character in text if unicodedata.category(character) not in IGNORED_CATEGORIES)
    return kept.strip()


def exact_version(value: object, expected: int) -> bool:
    """A versão declarada precisa ser o inteiro exato: `True` e `1.0` não são a versão 1."""
    return isinstance(value, int) and not isinstance(value, bool) and value == expected


def symlinked_component(path: Path) -> Path | None:
    """Primeiro componente do caminho que e link simbolico, ou nada quando nenhum e.

    Verificar apenas o caminho final deixaria passar `config -> ../../fora/config`, em que o arquivo
    final e regular mas o diretorio que o contem nao pertence a arvore auditada.
    """
    for component in [*reversed(path.parents), path]:
        if component.is_symlink():
            return component
    return None


def confined_regular_file(root: Path, path: Path, label: str) -> None:
    """Recusa arquivo que nao seja regular, que tenha componente simbolico ou que saia da raiz."""
    linked = symlinked_component(path)
    if linked is not None:
        raise SystemExit(f"ERRO: {label} passa por link simbolico: {linked}")
    resolved = path.resolve()
    if not resolved.is_file():
        raise SystemExit(f"ERRO: {label} nao e um arquivo regular: {path}")
    if not resolved.is_relative_to(root.resolve()):
        raise SystemExit(f"ERRO: {label} resolve para fora da raiz auditada: {resolved}")


def load_json(path: Path) -> dict:
    """Le um JSON de objeto, falhando fechado quando o arquivo falta ou nao e um objeto."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERRO: nao foi possivel ler {path}: {error}") from error
    if not isinstance(document, dict):
        raise SystemExit(f"ERRO: {path} nao contem um objeto JSON")
    return document


def policy_shape_errors(policy: dict) -> list[str]:
    """A politica precisa declarar versao exata, ausencia de autoridade e identificadores unicos.

    Sem isto, rodar o contrato sozinho aceitaria politica com versao de tipo errado, autoridade de merge
    declarada ou identificador repetido, e o veredito dependeria de qual porta de entrada foi usada.
    """
    errors = []
    if not exact_version(policy.get("policy_version"), SCHEMA_VERSION):
        errors.append("a politica nao declara `policy_version` como o inteiro 1")
    authority = policy.get("authority")
    if not isinstance(authority, dict):
        errors.append("a politica nao declara o bloco `authority`")
    else:
        errors.extend(
            f"a politica precisa declarar `authority.{key}` como falso"
            for key in ("merges", "tags", "publishes")
            if authority.get(key) is not False
        )
    if not isinstance(policy.get("required"), list) or not isinstance(policy.get("optional"), list):
        errors.append("a politica precisa declarar `required` e `optional` como listas")
        return errors
    identifiers = []
    for key in ("required", "optional"):
        for item in policy[key]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
                errors.append(f"a politica declara item sem identificador textual em `{key}`")
                continue
            for field in ("description", "reason"):
                declared = significant(item.get(field))
                if not declared:
                    errors.append(f"a politica declara item `{item['id']}` sem `{field}`")
            identifiers.append(item["id"])
    if len(identifiers) != len(set(identifiers)):
        errors.append("a politica repete identificador entre itens obrigatorios e opcionais")
    declared_required = {
        item["id"]
        for item in policy["required"]
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    errors.extend(
        f"a politica nao declara o item obrigatorio `{item}`"
        for item in sorted(REQUIRED_IDS - declared_required)
    )
    verdicts = policy.get("verdicts")
    approved = verdicts.get("audit_approved") if isinstance(verdicts, dict) else None
    if not isinstance(approved, list) or not approved:
        errors.append("a politica nao declara `verdicts.audit_approved`")
    return errors


def policy_items(policy: dict, key: str) -> list[dict]:
    """Itens declarados na politica sob `key`, na ordem em que aparecem."""
    items = policy.get(key)
    if not isinstance(items, list):
        raise SystemExit(f"ERRO: a politica nao declara a lista `{key}`")
    return [item for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]


def evidence_value(evidence: dict, item_id: str) -> tuple[str, str]:
    """Valor e origem declarados para um item, ou vazio quando nao ha evidencia."""
    items = evidence.get("items")
    entry = items.get(item_id) if isinstance(items, dict) else None
    if not isinstance(entry, dict):
        return "", ""
    value = entry.get("value")
    source = entry.get("source")
    # Espaco e caractere de controle nao sao evidencia: o valor e a origem precisam ter conteudo.
    return significant(value), significant(source)


def check_required(policy: dict, evidence: dict, shas: dict[str, str]) -> list[dict]:
    """Verifica cada item obrigatorio e devolve as linhas do relatorio."""
    rows = []
    for item in policy_items(policy, "required"):
        item_id = item["id"]
        value, source = evidence_value(evidence, item_id)
        problems = []
        if not source:
            problems.append("sem origem declarada para a evidencia")
        if not value:
            problems.append("sem evidencia declarada")
        elif item_id == "divergence":
            problems.extend(divergence_problems(shas))
        elif item_id == "independent-audit":
            problems.extend(audit_problems(policy, value))
        elif item_id in {"develop-sha"} and not SHA_RE.match(value):
            problems.append("commit nao e hexadecimal de 40 caracteres")
        rows.append({"id": item_id, "value": value, "source": source, "problems": problems})
    return rows


def divergence_problems(shas: dict[str, str]) -> list[str]:
    """O handoff exige que `develop` e `main` divirjam."""
    develop = shas.get("develop", "")
    main = shas.get("main", "")
    problems = []
    if not SHA_RE.match(develop):
        problems.append("commit de `develop` invalido")
    if not SHA_RE.match(main):
        problems.append("commit de `main` invalido")
    if develop and develop == main:
        problems.append("`develop` e `main` no mesmo commit: nao ha release a promover")
    return problems


def audit_problems(policy: dict, verdict: str) -> list[str]:
    """A auditoria independente precisa constar como aprovada na politica."""
    verdicts = policy.get("verdicts")
    approved = verdicts.get("audit_approved") if isinstance(verdicts, dict) else None
    if not isinstance(approved, list):
        return ["a politica nao declara os pareceres de auditoria aceitos"]
    if verdict not in approved:
        return [f"parecer de auditoria `{verdict}` nao esta aprovado"]
    return []


def evidence_problems(policy: dict, evidence: dict, shas: dict[str, str]) -> list[str]:
    """Problemas da evidencia como um todo, antes da verificacao item a item."""
    problems = []
    if not exact_version(evidence.get("schema_version"), SCHEMA_VERSION):
        problems.append("a evidencia nao declara `schema_version` 1")
    declared = {item["id"] for item in policy_items(policy, "required")}
    declared |= {item["id"] for item in policy_items(policy, "optional")}
    items = evidence.get("items")
    known = set(items) if isinstance(items, dict) else set()
    for unknown in sorted(known - declared):
        problems.append(f"identificador de evidencia desconhecido: `{unknown}`")
    declared_develop, _ = evidence_value(evidence, "develop-sha")
    if shas.get("develop") and declared_develop and shas["develop"] != declared_develop:
        problems.append("a evidencia aponta commit de `develop` diferente do informado")
    return problems


def build_report(policy: dict, evidence: dict, shas: dict[str, str]) -> dict:
    """Relatorio do handoff, com o veredito e uma linha por item."""
    rows = check_required(policy, evidence, shas)
    problems = evidence_problems(policy, evidence, shas)
    for row in rows:
        problems.extend(f"`{row['id']}`: {problem}" for problem in row["problems"])
    return {
        "schema_version": 1,
        "develop": shas.get("develop", ""),
        "main": shas.get("main", ""),
        "ready": not problems,
        "items": rows,
        "problems": problems,
    }


def markdown_report(report: dict) -> str:
    """Relatorio legivel, com marcacao por item."""
    lines = ["# Handoff de release", ""]
    lines.append(f"- `develop`: `{report['develop'] or 'nao informado'}`")
    lines.append(f"- `main`: `{report['main'] or 'nao informado'}`")
    lines.append(f"- veredito: **{'pronto' if report['ready'] else 'nao pronto'}**")
    lines.append("")
    lines.append("| Item | Evidencia | Origem | Estado |")
    lines.append("| --- | --- | --- | --- |")
    for row in report["items"]:
        state = "ok" if not row["problems"] else "; ".join(row["problems"])
        lines.append(f"| `{row['id']}` | {row['value'] or '-'} | {row['source'] or '-'} | {state} |")
    if report["problems"]:
        lines.append("")
        lines.append("## Pendencias")
        lines.extend(f"- {problem}" for problem in report["problems"])
    return "\n".join(lines) + "\n"


def refuse_symlink(path: Path, label: str) -> None:
    """Recusa escrever quando o destino ou qualquer diretorio que o contem e link simbolico."""
    linked = symlinked_component(path)
    if linked is not None:
        raise SystemExit(f"ERRO: {label} passa por link simbolico: {linked}")


def read_shas(arguments: argparse.Namespace, evidence: dict) -> dict[str, str]:
    """Commits de `develop` e `main`: argumento tem precedencia sobre a evidencia."""
    develop = significant(arguments.develop) or evidence_value(evidence, "develop-sha")[0]
    declared_main = significant(evidence.get("main"))
    main = significant(arguments.main) or declared_main
    return {"develop": develop or "", "main": main or ""}


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Argumentos do contrato de handoff."""
    parser = argparse.ArgumentParser(description="Verifica a evidencia do handoff de release.")
    parser.add_argument("--root", type=Path, default=Path(), help="Raiz do repositorio.")
    parser.add_argument("--evidence", type=Path, required=True, help="Arquivo de evidencia declarada.")
    parser.add_argument("--develop", default="", help="Commit de `develop` a promover.")
    parser.add_argument("--main", default="", help="Commit atual de `main`.")
    parser.add_argument("--report", type=Path, help="Caminho do relatorio Markdown.")
    parser.add_argument("--json-report", type=Path, help="Caminho do relatorio JSON.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Verifica o handoff e devolve 0 quando pronto, 1 quando falta evidencia."""
    arguments = parse_arguments(argv)
    policy_path = arguments.root / POLICY_RELATIVE
    confined_regular_file(arguments.root, policy_path, "a politica do handoff")
    policy = load_json(policy_path)
    shape_errors = policy_shape_errors(policy)
    if shape_errors:
        for error in shape_errors:
            print(f"ERRO: {error}")
        print("Handoff reprovado: a politica do handoff e invalida.")
        return 1
    evidence = load_json(arguments.evidence)
    shas = read_shas(arguments, evidence)
    report = build_report(policy, evidence, shas)
    markdown = markdown_report(report)
    if arguments.report:
        refuse_symlink(arguments.report, "o relatorio Markdown")
        arguments.report.write_text(markdown, encoding="utf-8")
    else:
        sys.stdout.write(markdown)
    if arguments.json_report:
        refuse_symlink(arguments.json_report, "o relatorio JSON")
        arguments.json_report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if report["ready"]:
        print("Handoff OK: evidencia obrigatoria completa e verificada.")
        return 0
    print(f"Handoff reprovado: {len(report['problems'])} pendencia(s).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
