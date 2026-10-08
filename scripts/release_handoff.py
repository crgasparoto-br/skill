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
import stat
import sys
import unicodedata
from pathlib import Path

SHA_RE = re.compile(r"\A[0-9a-f]{40}\Z")
POLICY_RELATIVE = "config/release-handoff.json"
MEANINGFUL_CATEGORIES = frozenset({"L", "N"})
# Codigos que renderizam como nada apesar de a categoria ser letra ou numero: preenchedores de Hangul
# (`U+115F`, `U+1160`, `U+3164`, `U+FFA0`), preenchedores de hieroglifo egipcio (`U+13441`, `U+13442`),
# braille em branco (`U+2800`), sinal de multiplicacao invisivel (`U+2062` a `U+2064`), separador de
# palavra invisivel (`U+2060`), espaco estreito sem quebra (`U+202F`) e marca de ordem de byte (`U+FEFF`).
DECLARED_CATEGORIES = frozenset({"L", "N", "P"})
MINIMUM_TEXT = 2
MINIMUM_DISTINCT = 2
BLANK_CHARACTERS = frozenset(
    {
        "\u115f",
        "\u1160",
        "\U00013441",
        "\U00013442",
        "\u202f",
        "\u2060",
        "\u2061",
        "\u2062",
        "\u2063",
        "\u2064",
        "\u2800",
        "\u3164",
        "\ufeff",
        "\uffa0",
    }
)
EVIDENCE_KEYS = frozenset({"schema_version", "main", "items"})
ITEM_KEYS = frozenset({"value", "source"})
REQUIRED_IDS = frozenset(
    {"issues-delivered", "develop-sha", "gates", "independent-audit", "divergence"}
)
SCHEMA_VERSION = 1


def significant(text: object) -> str:
    """Conteudo significativo: so letra e numero contam como evidencia.

    Listar o que descartar sempre deixa uma categoria invisivel de fora: espaco e controle nao bastavam,
    porque marcas combinantes como `U+034F` tambem sao invisiveis. Por isso a regra e positiva: o texto
    significativo e aquele formado por letras e numeros, e nada mais conta como evidencia.
    """
    if not isinstance(text, str):
        return ""
    return "".join(
        character
        for character in text
        if unicodedata.category(character)[0] in MEANINGFUL_CATEGORIES
        and character not in BLANK_CHARACTERS
    ).strip()


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
    resolved = resolved_path(path, label)
    if not resolved.is_file():
        raise SystemExit(f"ERRO: {label} nao e um arquivo regular: {path}")
    if not resolved.is_relative_to(resolved_path(root, label)):
        raise SystemExit(f"ERRO: {label} resolve para fora da raiz auditada: {resolved}")


def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    """Converte pares em objeto e recusa chave repetida, que `json.loads` resolveria em silencio."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise SystemExit(f"ERRO: chave repetida no JSON: {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> dict:
    """Le um JSON de objeto, falhando fechado quando o arquivo falta ou nao e um objeto."""
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
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
    approved = (policy.get("verdicts") or {}).get("audit_approved") if isinstance(policy.get("verdicts"), dict) else None
    if isinstance(approved, list) and len(approved) != len(set(map(str, approved))):
        errors.append("a politica repete parecer em `verdicts.audit_approved`")
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
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or visible_problem(item["id"])
            ):
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
    for item in approved:
        if not isinstance(item, str) or visible_problem(item):
            errors.append("a politica declara parecer invalido em `verdicts.audit_approved`")
    return errors


def policy_items(policy: dict, key: str) -> list[dict]:
    """Itens declarados na politica sob `key`, na ordem em que aparecem."""
    items = policy.get(key)
    if not isinstance(items, list):
        raise SystemExit(f"ERRO: a politica nao declara a lista `{key}`")
    return [item for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)]


def encodable(text: str) -> bool:
    """Texto que nao pode ser codificado em UTF-8, como surrogate isolado, nao serve como evidencia."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def allowed_character(character: str) -> bool:
    """Caractere permitido em texto declarado: letra, numero, pontuacao ou espaco simples.

    `L`, `N` e `P` sao familias de categorias, enquanto o espaco simples e um caractere exato. Comparar so
    a familia descartaria o espaco legitimo, e aceitar toda a familia `Zs` aceitaria espaco nao quebravel e
    espaco ideografico, que passam por texto normal sem serem o separador comum.
    """
    category = unicodedata.category(character)
    return category[0] in DECLARED_CATEGORIES or character == " "


def visible_problem(text: str) -> str:
    """Descreve por que o texto nao serve como evidencia, ou devolve vazio quando serve.

    A regra positiva de `significant()` nao basta aqui: ela **remove** o caractere estranho e aceitaria
    `"lo\u200blocal"` como `"local"`. Para valor e origem declarados a exigencia e outra: nada invisivel,
    espaco normal permitido no meio, ao menos uma letra ou digito e tamanho minimo de dois caracteres.
    """
    if text != text.strip():
        return "tem espaco nas pontas"

    if not text:
        return "esta vazio"
    if not encodable(text):
        return "tem caractere nao codificavel em UTF-8"
    if any(character in BLANK_CHARACTERS for character in text):
        return "contem preenchedor"
    if any(not allowed_character(character) for character in text):
        return "contem caractere fora de letra, numero, pontuacao e espaco"
    if not any(unicodedata.category(character)[0] in MEANINGFUL_CATEGORIES for character in text):
        return "nao contem letra nem digito"
    if len(text) < MINIMUM_TEXT:
        return f"tem menos de {MINIMUM_TEXT} caracteres"
    if len(set(text)) < MINIMUM_DISTINCT:
        return "nao tem caracteres distintos"
    return ""


def declared_text(evidence: dict, item_id: str) -> str:
    """Valor declarado sem normalizacao de conteudo: espaco interno precisa chegar a validacao.

    Aplicar a regra de conteudo significativo aqui apagaria o espaco interno de um commit informado, e
    um valor de 41 caracteres passaria a parecer hexadecimal de 40.
    """
    entry = evidence.get("items")
    entry = entry.get(item_id) if isinstance(entry, dict) else None
    value = entry.get("value") if isinstance(entry, dict) else None
    return value if isinstance(value, str) else ""


def evidence_value(evidence: dict, item_id: str) -> tuple[str, str]:
    """Valor e origem declarados para um item, ou vazio quando nao ha evidencia."""
    items = evidence.get("items")
    entry = items.get(item_id) if isinstance(items, dict) else None
    if not isinstance(entry, dict):
        return "", ""
    extra = sorted(set(entry) - ITEM_KEYS)
    if extra:
        raise SystemExit(f"ERRO: o item `{item_id}` traz campo desconhecido: {', '.join(extra)}")
    source = entry.get("source")
    # Valor e origem chegam intactos a validacao: normalizar apagaria separador interno de um commit ou
    # o caractere invisivel embutido numa origem, e os dois passariam como se fossem validos.
    return declared_text(evidence, item_id), (source if isinstance(source, str) else "")


def check_required(policy: dict, evidence: dict, shas: dict[str, str]) -> list[dict]:
    """Verifica cada item obrigatorio e devolve as linhas do relatorio."""
    rows = []
    for item in policy_items(policy, "required"):
        item_id = item["id"]
        value, source = evidence_value(evidence, item_id)
        problems = []
        reason = visible_problem(source)
        if reason:
            problems.append(f"origem declarada {reason}")
        if not value:
            problems.append("sem evidencia declarada")
        else:
            if item_id != "develop-sha":
                reason = visible_problem(value)
                if reason:
                    problems.append(f"evidencia declarada {reason}")
            if item_id == "divergence":
                problems.extend(divergence_problems(shas))
            elif item_id == "independent-audit":
                problems.extend(audit_problems(policy, value))
            elif item_id == "develop-sha" and not SHA_RE.match(value):
                problems.append("commit nao e hexadecimal de 40 caracteres")
        rows.append({"id": item_id, "value": value, "source": source, "problems": problems})
    return rows


def check_optional(policy: dict, evidence: dict) -> list[str]:
    """Item opcional presente precisa declarar valor e origem utilizaveis, mesmo sem bloquear o handoff."""
    problems = []
    for item in policy_items(policy, "optional"):
        item_id = item["id"]
        entries = evidence.get("items")
        if not isinstance(entries, dict) or item_id not in entries:
            continue
        entry = entries[item_id]
        if not isinstance(entry, dict):
            problems.append(f"o item opcional `{item_id}` precisa ser objeto com valor e origem")
            continue
        value, source = evidence_value(evidence, item_id)
        for field, text in (("valor", value), ("origem", source)):
            reason = visible_problem(text)
            if reason:
                problems.append(f"o {field} do item opcional `{item_id}` {reason}")
    return problems


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
    declared_main = evidence.get("main")
    if not isinstance(declared_main, str) or not SHA_RE.match(declared_main):
        problems.append("a evidencia precisa declarar `main` como hexadecimal de 40 caracteres")
    if not exact_version(evidence.get("schema_version"), SCHEMA_VERSION):
        problems.append("a evidencia nao declara `schema_version` 1")
    declared = {item["id"] for item in policy_items(policy, "required")}
    declared |= {item["id"] for item in policy_items(policy, "optional")}
    for key in sorted(set(evidence) - EVIDENCE_KEYS):
        problems.append(f"a evidencia traz campo desconhecido `{key}`")
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
    problems.extend(check_optional(policy, evidence))
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




def resolved_path(path: Path, label: str) -> Path:
    """Resolve o caminho, recusando link ciclico de forma controlada."""
    try:
        return path.resolve()
    except (OSError, RuntimeError, UnicodeEncodeError, ValueError) as error:
        raise SystemExit(f"ERRO: {label} nao pode ser resolvido: {error}") from error


def refuse_protected(root: Path, path: Path, evidence: Path, label: str) -> None:
    """Recusa destino que sobrescreveria o contrato, a politica ou a propria evidencia."""
    resolved = resolved_path(path, label)
    protected = [
        resolved_path(root, label) / POLICY_RELATIVE,
        resolved_path(Path(__file__), label),
        resolved_path(evidence, label),
    ]
    if resolved in protected:
        raise SystemExit(f"ERRO: {label} sobrescreveria um artefato do handoff: {resolved}")


def write_report(root: Path, path: Path, evidence: Path, text: str, label: str) -> None:
    """Escreve o relatorio de forma que o destino pedido seja o unico arquivo alterado.

    Duas brechas ficam fechadas: um destino que seja hard link de outro arquivo (`st_nlink` maior que um)
    levaria a escrita para o alvo compartilhado, e conferir o caminho e depois escrever deixaria a janela
    em que um link e criado entre a conferencia e a abertura. Por isso a conferencia vem antes e a escrita
    passa por arquivo temporario seguido de substituicao atomica, que troca o proprio link pelo arquivo.
    """
    refuse_protected(root, path, evidence, label)
    if not path.is_absolute():
        raise SystemExit(f"ERRO: {label} precisa de caminho absoluto: {path}")
    if not resolved_path(path, label).is_relative_to(resolved_path(root, label)):
        raise SystemExit(f"ERRO: {label} precisa ficar dentro da raiz auditada: {path}")
    refuse_symlink(path, label)
    if not path.parent.is_dir():
        raise SystemExit(f"ERRO: {label} nao tem diretorio de destino: {path.parent}")
    if path.exists():
        status = path.stat()
        if not stat.S_ISREG(status.st_mode) or status.st_nlink > 1:
            raise SystemExit(f"ERRO: {label} nao e um arquivo regular exclusivo: {path}")
    temporary = path.with_name(f"{path.name}.parcial")
    if temporary.exists() or temporary.is_symlink():
        raise SystemExit(f"ERRO: {label} usa um caminho temporario ja ocupado: {temporary}")
    try:
        temporary.write_text(text.encode("utf-8", "backslashreplace").decode("utf-8"), encoding="utf-8")
        temporary.replace(path)
    except (OSError, UnicodeEncodeError) as error:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"ERRO: nao foi possivel escrever {label}: {error}") from error


def read_shas(arguments: argparse.Namespace, evidence: dict) -> dict[str, str]:
    """Commits de `develop` e `main`: argumento tem precedencia sobre a evidencia."""
    informed_develop = arguments.develop if arguments.develop else ""
    if arguments.develop is not None and not informed_develop:
        raise SystemExit("ERRO: `--develop` foi informado vazio")
    if arguments.main is not None and not arguments.main:
        raise SystemExit("ERRO: `--main` foi informado vazio")
    develop = informed_develop or declared_text(evidence, "develop-sha")
    declared_main = evidence.get("main")
    declared_main = declared_main if isinstance(declared_main, str) else ""
    informed_main = arguments.main if arguments.main else ""
    declared_develop = evidence_value(evidence, "develop-sha")[0]
    if declared_develop and not SHA_RE.match(declared_develop):
        raise SystemExit("ERRO: `develop-sha` da evidencia precisa ser hexadecimal de 40 caracteres")
    for flag, informed in (("--develop", informed_develop), ("--main", informed_main)):
        if informed and not SHA_RE.match(informed):
            raise SystemExit(f"ERRO: {flag} precisa ser hexadecimal de 40 caracteres")
    if declared_main and not SHA_RE.match(declared_main):
        raise SystemExit(f"ERRO: `main` da evidencia nao e hexadecimal de 40: {declared_main}")
    if informed_main and declared_main and informed_main != declared_main:
        raise SystemExit(
            f"ERRO: `--main` diverge da evidencia: {informed_main} contra {declared_main}"
        )
    main = informed_main or declared_main
    return {"develop": develop or "", "main": main or ""}


def root_path(value: str) -> Path:
    """Raiz do repositorio: valor vazio nao pode virar o diretorio atual em silencio."""
    if not value:
        raise argparse.ArgumentTypeError("a raiz nao pode ser vazia")
    return Path(value)


def reject_repeated_options(argv: list[str]) -> None:
    """Recusa opcao repetida: sem isto a ultima ocorrencia venceria em silencio."""
    seen = set()
    for token in argv:
        name = token.split("=", 1)[0]
        if not name.startswith("--"):
            continue
        if name in seen:
            raise SystemExit(f"ERRO: a opcao {name} foi informada mais de uma vez")
        seen.add(name)


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """Argumentos do contrato de handoff, sem abreviacao e sem opcao repetida."""
    parser = argparse.ArgumentParser(
        description="Verifica a evidencia do handoff de release.", allow_abbrev=False
    )
    parser.add_argument("--root", type=root_path, default=Path(), help="Raiz do repositorio.")
    parser.add_argument("--evidence", type=Path, required=True, help="Arquivo de evidencia declarada.")
    parser.add_argument("--develop", default=None, help="Commit de `develop` a promover.")
    parser.add_argument("--main", default=None, help="Commit atual de `main`.")
    parser.add_argument("--report", type=Path, help="Caminho do relatorio Markdown.")
    parser.add_argument("--json-report", type=Path, help="Caminho do relatorio JSON.")
    arguments = list(sys.argv[1:] if argv is None else argv)
    reject_repeated_options(arguments)
    return parser.parse_args(arguments)


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
    if (
        arguments.report
        and arguments.json_report
        and resolved_path(Path(arguments.report), "o relatorio") == resolved_path(Path(arguments.json_report), "o relatorio")
    ):
        raise SystemExit("ERRO: `--report` e `--json-report` nao podem apontar para o mesmo destino")
    if arguments.report:
        write_report(arguments.root, arguments.report, arguments.evidence, markdown, "o relatorio Markdown")
    else:
        sys.stdout.write(markdown.encode("utf-8", "backslashreplace").decode("utf-8"))
    if arguments.json_report:
        write_report(
            arguments.root, arguments.json_report, arguments.evidence,
            json.dumps(report, ensure_ascii=True, indent=2) + "\n", "o relatorio JSON",
        )
    if report["ready"]:
        print("Handoff OK: evidencia obrigatoria completa e verificada.")
        return 0
    print(f"Handoff reprovado: {len(report['problems'])} pendencia(s).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
