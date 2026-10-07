#!/usr/bin/env python3
"""Gate deterministico de analise estatica do codigo Python do catalogo.

A politica em `config/lint-policy.json` e a unica fonte da decisao sobre regras: cada familia do
catalogo da ferramenta aparece exatamente uma vez como aplicada, aplicada em parte com a parte
desligada declarada, ou dispensada com motivo escrito, e a cobertura e conferida no nivel da regra,
nao apenas no nivel do prefixo. O gate reprova quando a politica nao cobre o catalogo, quando uma
familia nao decide sobre todas as suas regras, quando uma dispensa nao tem motivo suficiente, quando
a ferramenta nao esta instalada, quando a versao executada diverge da declarada, quando existe
supressao em linha ou de arquivo com codigo fora da lista permitida ou sem justificativa propria,
quando um arquivo coberto esta fora da raiz ou em diretorio ilegivel, e quando qualquer regra
aplicada e violada.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_dependency_locks import confined, relative

POLICY = Path("config") / "lint-policy.json"
REQUIRED_STATES = {"selected", "partial", "dismissed"}
MINIMUM_REASON_CHARS = 40
MINIMUM_JUSTIFICATION_CHARS = 8
ENTRY_RE = re.compile(r"[A-Z]+\d*")
# Diretivas que a ferramenta reconhece: marcador em qualquer caixa e diretiva de arquivo com
# prefixo `ruff:` ou `flake8:`. A leitura e feita sobre comentarios reais, entao a ocorrencia
# dentro de string nao conta como supressao.
DIRECTIVE_RE = re.compile(r"#\s*(?:(?P<scope>ruff|flake8)\s*:\s*)?noqa(?P<rest>:\s*(?P<codes>[A-Za-z0-9]+(?:[,\s]+[A-Za-z0-9]+)*))?", re.IGNORECASE)
JUSTIFICATION_SEPARATOR = " - "
MAXIMUM_REPORTED = 200
MAXIMUM_LISTED_CODES = 8
TOOL_TIMEOUT_SECONDS = 120


def load_policy(root: Path, errors: list[str]) -> dict | None:
    path = root / POLICY
    if not path.is_file():
        errors.append(f"{POLICY.as_posix()}: ausente")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{POLICY.as_posix()}: ilegivel ({exc})")
        return None
    if not isinstance(data, dict):
        errors.append(f"{POLICY.as_posix()}: precisa ser objeto")
        return None
    return data


def shortlist(codes: set[str] | list[str]) -> str:
    ordered = sorted(codes)
    if len(ordered) <= MAXIMUM_LISTED_CODES:
        return ", ".join(ordered)
    return f"{', '.join(ordered[:MAXIMUM_LISTED_CODES])} e mais {len(ordered) - MAXIMUM_LISTED_CODES}"


def covered(codes: set[str], entries: list[str]) -> set[str]:
    """Regras do conjunto cobertas por entradas, que podem ser prefixo ou codigo completo."""
    return {code for code in codes if any(code.startswith(entry) for entry in entries)}


def scope_errors(policy: dict) -> list[str]:
    """O escopo do gate e declarado, nao presumido pelo codigo."""
    errors: list[str] = []
    scope = policy.get("scope")
    if not isinstance(scope, dict):
        return ["politica: scope precisa ser objeto com extensions, excluded_directories e reason"]
    extensions = scope.get("extensions")
    if not isinstance(extensions, list) or not extensions:
        errors.append("politica: scope.extensions precisa ser lista nao vazia")
    elif any(not isinstance(item, str) or not item.startswith(".") for item in extensions):
        errors.append("politica: scope.extensions aceita apenas sufixos iniciados por ponto")
    excluded = scope.get("excluded_directories")
    if not isinstance(excluded, list) or not excluded:
        errors.append("politica: scope.excluded_directories precisa ser lista nao vazia")
    elif any(not isinstance(item, str) or not item for item in excluded):
        errors.append("politica: scope.excluded_directories aceita apenas nomes de diretorio")
    reason = scope.get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < MINIMUM_REASON_CHARS:
        errors.append("politica: scope.reason precisa de motivo escrito suficiente")
    return errors


def family_errors(
    prefix: str, state: str, select: list, ignore: list, catalog: dict[str, str]
) -> list[str]:
    """A familia precisa decidir sobre todas as suas regras, no nivel da regra."""
    errors: list[str] = []
    family_codes = {code for code, family in catalog.items() if family == prefix}
    for label, raw_items in (("select", select), ("ignore", ignore)):
        for raw in raw_items:
            text = str(raw)
            if text != text.upper() or not ENTRY_RE.fullmatch(text):
                errors.append(f"politica: familia {prefix} declara {label} invalido: {raw!r}")
                continue
            if re.sub(r"[^A-Z]", "", text) != prefix:
                errors.append(
                    f"politica: familia {prefix} declara {label} {text}, que nao pertence a familia"
                )
    entries = [str(item).upper() for item in select]
    ignored_entries = [str(item).upper() for item in ignore]
    if not family_codes:
        return errors
    selected = covered(family_codes, entries)
    ignored = covered(family_codes, ignored_entries)
    if state == "selected":
        if ignored:
            errors.append(
                f"politica: familia {prefix} aplicada nao pode desligar regra: {shortlist(ignored)}"
            )
        pending = family_codes - selected
        if pending:
            errors.append(
                f"politica: familia {prefix} aplicada nao decide sobre toda a familia: {shortlist(pending)}"
            )
    elif state == "partial":
        # A ferramenta aplica `select` menos `ignore`, entao sobreposicao e a forma normal de
        # aplicar a familia inteira e desligar partes. O que nao pode acontecer e sobrar regra sem
        # decisao, nem a parte parcial desligar tudo e virar dispensa disfarcada.
        if not ignored:
            errors.append(
                f"politica: familia {prefix} parcial precisa declarar a parte desligada em ignore"
            )
        pending = family_codes - (selected | ignored)
        if pending:
            errors.append(
                f"politica: familia {prefix} parcial deixa regra sem decisao: {shortlist(pending)}"
            )
        applied = selected - ignored
        if not applied:
            errors.append(
                f"politica: familia {prefix} parcial desliga a familia inteira; use dismissed com motivo"
            )
    elif select or ignore:
        errors.append(f"politica: familia {prefix} dispensada nao pode selecionar nem desligar regra")
    return errors


def is_exact_integer(value: object) -> bool:
    """Inteiro de verdade: booleano e float nao contam, mesmo quando comparam igual a um inteiro."""
    return isinstance(value, int) and not isinstance(value, bool)


def policy_errors(policy: dict, catalog: dict[str, str]) -> list[str]:
    """Integridade da politica: catalogo coberto, regras decididas, motivos e supressoes."""
    errors: list[str] = []
    schema_version = policy.get("schema_version")
    if not is_exact_integer(schema_version) or schema_version != 1:
        # Em Python `True == 1` e `1.0 == 1`: sem exigir inteiro exato, `true` e `1.0` passariam
        # como versao de schema que ninguem declarou.
        errors.append("politica: schema_version precisa ser o inteiro 1")

    tool = policy.get("tool")
    if not isinstance(tool, dict) or tool.get("name") != "ruff":
        errors.append("politica: tool.name precisa ser 'ruff'")
    elif not re.fullmatch(r"\d+\.\d+\.\d+", str(tool.get("version", ""))):
        errors.append("politica: tool.version precisa ser versao fixada no formato X.Y.Z")

    if not re.fullmatch(r"py3\d{2}", str(policy.get("target_version", ""))):
        errors.append("politica: target_version precisa ser alvo explicito, como py312")

    line_length = policy.get("line_length")
    if not isinstance(line_length, dict):
        # Forma bruta invalida reprova aqui: consultar campo de um escalar trocaria a causa por um
        # traceback, que e exatamente o que a interrupcao da validacao existe para evitar.
        errors.append("politica: line_length precisa ser objeto")
    elif not is_exact_integer(line_length.get("value")) or line_length["value"] <= 0:
        errors.append("politica: line_length.value precisa ser inteiro positivo, nao booleano nem fracao")
    else:
        reason = line_length.get("reason")
        if not isinstance(reason, str) or len(reason.strip()) < MINIMUM_REASON_CHARS:
            errors.append("politica: line_length.reason precisa de motivo escrito suficiente")

    errors.extend(scope_errors(policy))

    families = policy.get("families")
    if not isinstance(families, list) or not families:
        errors.append("politica: families precisa ser lista nao vazia")
        return errors

    seen: set[str] = set()
    for entry in families:
        if not isinstance(entry, dict):
            errors.append("politica: entrada de familia precisa ser objeto")
            continue
        prefix = str(entry.get("prefix", ""))
        if not prefix:
            errors.append("politica: entrada de familia sem prefix")
            continue
        if prefix in seen:
            errors.append(f"politica: familia {prefix} declarada mais de uma vez")
        seen.add(prefix)
        state = entry.get("state")
        if not isinstance(state, str) or state not in REQUIRED_STATES:
            errors.append(f"politica: familia {prefix} com estado invalido: {state!r}")
            continue
        select = entry.get("select")
        ignore = entry.get("ignore")
        if not isinstance(select, list) or not isinstance(ignore, list):
            errors.append(f"politica: familia {prefix} precisa declarar select e ignore como listas")
            continue
        reason = entry.get("reason")
        if state != "selected":
            if not isinstance(reason, str) or len(reason.strip()) < MINIMUM_REASON_CHARS:
                errors.append(
                    f"politica: familia {prefix} precisa de motivo escrito com pelo menos "
                    f"{MINIMUM_REASON_CHARS} caracteres"
                )
        elif reason not in (None, ""):
            errors.append(f"politica: familia {prefix} aplicada nao pode carregar motivo de dispensa")
        errors.extend(family_errors(prefix, state, select, ignore, catalog))

    if not catalog:
        # Sem catalogo, a cobertura nao pode ser conferida e uma lista de familias faltantes seria
        # ruido em cima da causa real, que ja foi registrada ao listar o catalogo.
        errors.append("politica: catalogo de regras indisponivel; cobertura de familias nao pode ser conferida")
    else:
        missing = sorted(set(catalog.values()) - seen)
        extra = sorted(seen - set(catalog.values()))
        if missing:
            errors.append(f"politica: familias do catalogo sem decisao: {', '.join(missing)}")
        if extra:
            errors.append(f"politica: familias declaradas que nao existem no catalogo: {', '.join(extra)}")

    suppressions = policy.get("allowed_suppressions")
    if not isinstance(suppressions, list):
        errors.append("politica: allowed_suppressions precisa ser lista")
    else:
        for entry in suppressions:
            if not isinstance(entry, dict) or not re.fullmatch(r"[A-Z]+\d+", str(entry.get("code", ""))):
                errors.append("politica: supressao permitida precisa declarar code valido")
                continue
            reason = entry.get("reason")
            if not isinstance(reason, str) or len(reason.strip()) < MINIMUM_REASON_CHARS:
                errors.append(f"politica: supressao {entry.get('code')} precisa de motivo escrito")
    return errors


def declared_codes(policy: dict, key: str) -> list[str]:
    """Codigos declarados numa chave das familias, tolerando forma bruta invalida."""
    families = policy.get("families")
    if not isinstance(families, list):
        return []
    codes: set[str] = set()
    for entry in families:
        if not isinstance(entry, dict):
            continue
        declared = entry.get(key)
        if isinstance(declared, list):
            codes.update(str(code) for code in declared)
    return sorted(codes)


def selection_of(policy: dict) -> tuple[list[str], list[str]]:
    return declared_codes(policy, "select"), declared_codes(policy, "ignore")


def tool_path() -> str | None:
    """Executavel resolvido uma vez, para que a analise use o mesmo que foi verificado."""
    return shutil.which("ruff")


def catalog_of(executable: str | None, errors: list[str]) -> dict[str, str]:
    """Codigo de regra para familia, segundo o catalogo da ferramenta instalada."""
    if executable is None:
        return {}
    try:
        completed = subprocess.run(
            [executable, "rule", "--all", "--output-format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=TOOL_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        errors.append("ruff: nao instalado; instalar pelo lockfile antes de validar")
        return {}
    except subprocess.TimeoutExpired:
        errors.append("ruff: tempo esgotado ao listar o catalogo de regras")
        return {}
    if completed.returncode != 0:
        errors.append(f"ruff: falha ao listar o catalogo: {completed.stderr.strip()[:200]}")
        return {}
    try:
        rules = json.loads(completed.stdout)
    except json.JSONDecodeError:
        errors.append("ruff: catalogo de regras em formato inesperado")
        return {}
    if not isinstance(rules, list) or not rules:
        errors.append("ruff: catalogo de regras em formato inesperado")
        return {}
    catalog: dict[str, str] = {}
    for rule in rules:
        code = rule.get("code") if isinstance(rule, dict) else None
        if not isinstance(code, str) or not code:
            errors.append("ruff: entrada de catalogo sem codigo de regra")
            return {}
        normalized = code.upper()
        catalog[normalized] = re.sub(r"[^A-Z]", "", normalized)
    return catalog


def installed_version(executable: str | None, errors: list[str]) -> str | None:
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        errors.append("ruff: nao instalado; instalar pelo lockfile antes de validar")
        return None
    match = re.search(r"(\d+\.\d+\.\d+)", completed.stdout)
    if completed.returncode != 0 or not match:
        errors.append(f"ruff: versao ilegivel ({completed.stdout.strip()[:80]})")
        return None
    return match.group(1)


def python_files(root: Path, policy: dict, errors: list[str]) -> list[Path]:
    """Arquivos do escopo declarado, com falha explicita em vez de omissao silenciosa."""
    scope = policy.get("scope") or {}
    extensions = tuple(str(item) for item in scope.get("extensions") or ())
    excluded = {str(item) for item in scope.get("excluded_directories") or ()}
    if not extensions:
        errors.append("politica: scope.extensions precisa declarar os sufixos cobertos")
        return []

    def onerror(error: OSError) -> None:
        location = getattr(error, "filename", None) or "desconhecido"
        errors.append(f"{location}: diretorio ilegivel ({error.strerror or error.__class__.__name__})")

    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        kept: list[str] = []
        for name in sorted(dirnames):
            if name in excluded:
                continue
            directory = Path(dirpath) / name
            if directory.is_symlink():
                # A caminhada nao segue link de diretorio: o conteudo sairia da analise sem
                # aparecer, entao o caso e reprovado para que a resolucao seja explicita.
                if confined(directory, root):
                    errors.append(
                        f"{relative(directory, root)}: diretorio do escopo e link simbolico e nao e seguido"
                    )
                else:
                    errors.append(
                        f"{relative(directory, root)}: diretorio do escopo aponta para fora da raiz"
                    )
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if path.is_symlink():
                # Um link quebrado ou ciclico aparece como arquivo, nao como diretorio, e sumiria
                # do conjunto sem aparecer se o filtro de sufixo viesse primeiro.
                try:
                    path.resolve(strict=True)
                except (OSError, RuntimeError):
                    errors.append(
                        f"{relative(path, root)}: link simbolico quebrado ou ciclico no escopo"
                    )
                    continue
            if not name.endswith(extensions):
                continue
            if not confined(path, root):
                errors.append(
                    f"{relative(path, root)}: arquivo coberto aponta para fora da raiz do repositorio"
                )
                continue
            found.append(path)
    return found


def comments_of(text: str) -> list[tuple[int, str]]:
    """Comentarios reais do arquivo, com a linha: texto dentro de string nao e supressao."""
    found: list[tuple[int, str]] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                found.append((token.start[0], token.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return found
    return found


def suppression_errors(root: Path, files: list[Path], policy: dict, errors: list[str]) -> None:
    """Supressao precisa estar declarada na politica e justificada na propria diretiva.

    A leitura cobre as formas que a ferramenta reconhece: o marcador em qualquer caixa e a diretiva
    de arquivo com prefixo `ruff:` ou `flake8:`. Supressao de arquivo sem codigo e recusada porque
    desliga a analise inteira sem deixar o alvo declarado.
    """
    declared = policy.get("allowed_suppressions")
    allowed = {
        str(entry.get("code")).upper()
        for entry in (declared if isinstance(declared, list) else [])
        if isinstance(entry, dict)
    }
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append(f"{relative(path, root)}: ilegivel ou fora de UTF-8")
            continue
        for number, comment in comments_of(text):
            match = DIRECTIVE_RE.search(comment)
            if not match:
                continue
            where = f"{relative(path, root)}:{number}"
            codes = match.group("codes")
            if not codes:
                kind = "de arquivo" if match.group("scope") else "sem codigo de regra"
                errors.append(f"{where}: supressao {kind} sem codigo declarado")
                continue
            for code in re.split(r"[,\s]+", codes.strip()):
                if code.upper() not in allowed:
                    errors.append(f"{where}: supressao de {code} fora da lista permitida na politica")
            tail = comment[match.end():]
            separator = tail.find(JUSTIFICATION_SEPARATOR)
            justification = (
                tail[separator + len(JUSTIFICATION_SEPARATOR):].strip() if separator >= 0 else ""
            )
            if len(justification) < MINIMUM_JUSTIFICATION_CHARS:
                errors.append(
                    f"{where}: supressao sem justificativa propria de pelo menos "
                    f"{MINIMUM_JUSTIFICATION_CHARS} caracteres apos ' - '"
                )


def run_tool(
    root: Path,
    executable: str | None,
    target_version: str,
    line_length: int,
    select: list[str],
    ignore: list[str],
    files: list[Path],
    errors: list[str],
) -> list[dict]:
    """Executa a ferramenta sem cache, exatamente com a decisao declarada na politica."""
    if not files or executable is None:
        return []
    command = [
        executable, "check",
        "--no-cache",
        "--quiet",
        "--target-version", target_version,
        "--line-length", str(line_length),
        "--select", ",".join(select),
        "--extend-ignore", ",".join(ignore),
        "--output-format", "json",
        *[relative(path, root) for path in files],
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            cwd=str(root),
            timeout=TOOL_TIMEOUT_SECONDS * 5,
        )
    except FileNotFoundError:
        errors.append("ruff: executavel indisponivel no momento da analise; reinstalar pelo lockfile")
        return []
    except subprocess.TimeoutExpired:
        errors.append("ruff: tempo esgotado ao analisar o codigo")
        return []
    if completed.returncode not in (0, 1):
        errors.append(f"ruff: execucao falhou: {completed.stderr.strip()[:200]}")
        return []
    if not completed.stdout.strip():
        errors.append("ruff: saida da analise vazia")
        return []
    try:
        violations = json.loads(completed.stdout)
    except json.JSONDecodeError:
        errors.append("ruff: saida da analise em formato inesperado")
        return []
    if not isinstance(violations, list):
        errors.append("ruff: saida da analise em formato inesperado")
        return []
    for violation in violations:
        if not isinstance(violation, dict):
            errors.append("ruff: diagnostico em formato inesperado")
            return []
        if not isinstance(violation.get("code"), str) or not isinstance(violation.get("filename"), str):
            errors.append("ruff: diagnostico sem codigo de regra ou arquivo")
            return []
        if violation.get("location") is not None and not isinstance(violation.get("location"), dict):
            errors.append("ruff: diagnostico com localizacao em formato inesperado")
            return []
    return violations


def validate_lint(root: Path) -> list[str]:
    """Valida a politica e executa a analise com a decisao declarada."""
    root = root.resolve()
    errors: list[str] = []
    policy = load_policy(root, errors)
    if policy is None:
        return errors

    executable = tool_path()
    if executable is None:
        errors.append("ruff: nao instalado; instalar pelo lockfile antes de validar")
    catalog = catalog_of(executable, errors)
    policy_problems = policy_errors(policy, catalog)
    errors.extend(policy_problems)
    if policy_problems:
        # Politica invalida interrompe aqui: selecao, arquivos, supressoes e analise dependem de uma
        # politica integra, e seguir em frente trocaria a causa pelo sintoma ou estouraria traceback.
        return errors
    version = installed_version(executable, errors)
    declared = str(policy.get("tool", {}).get("version", ""))
    if version and declared and version != declared:
        errors.append(f"ruff: versao instalada {version} diverge da declarada {declared}")

    select, ignore = selection_of(policy)
    files = python_files(root, policy, errors)
    if not files:
        errors.append("escopo: nenhum arquivo coberto encontrado; conjunto vazio nao pode ser aprovacao")
    suppression_errors(root, files, policy, errors)

    violations = run_tool(
        root,
        executable,
        str(policy.get("target_version", "py312")),
        int((policy.get("line_length") or {}).get("value") or 0),
        select,
        ignore,
        files,
        errors,
    )
    for violation in violations:
        location = violation.get("location") or {}
        errors.append(
            f"{violation.get('filename')}:{location.get('row')}:{location.get('column')}: "
            f"{violation.get('code')} {violation.get('message')}"
        )
    if not errors:
        print(f"Lint OK: {len(files)} arquivo(s) coberto(s) sem violacao das regras aplicadas.")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validar politica de lint e executar a analise.")
    parser.add_argument("--root", default=".", help="raiz do repositorio")
    parser.add_argument("--quiet", action="store_true", help="imprimir apenas o resumo dos erros")
    args = parser.parse_args(argv)

    errors = validate_lint(Path(args.root))
    if errors:
        limit = 5 if args.quiet else MAXIMUM_REPORTED
        for error in errors[:limit]:
            print(f"ERRO: {error}", file=sys.stderr)
        if len(errors) > limit:
            print(f"... e {len(errors) - limit} outro(s)", file=sys.stderr)
        print(f"validacao falhou: {len(errors)} erro(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
