#!/usr/bin/env python3
"""Gate deterministico de analise estatica do codigo Python do catalogo.

A politica em `config/lint-policy.json` e a unica fonte da selecao de regras: cada familia do
catalogo do Ruff aparece exatamente uma vez como aplicada, aplicada em parte com a parte desligada
declarada, ou dispensada com motivo escrito. O gate reprova quando a politica nao cobre o catalogo,
quando uma dispensa nao tem motivo suficiente, quando a ferramenta nao esta instalada, quando a
versao executada diverge da declarada, quando existe supressao em linha com codigo fora da lista
permitida ou sem justificativa propria, e quando qualquer regra aplicada e violada.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_dependency_locks import confined, relative

POLICY = Path("config") / "lint-policy.json"
REQUIRED_STATES = {"selected", "partial", "dismissed"}
MINIMUM_REASON_CHARS = 40
# O marcador e montado para que o proprio codigo do gate nao contenha a sequencia que ele procura.
SUPPRESSION_RE = re.compile(r"#" + r"\s*noqa(?::\s*(?P<codes>[A-Za-z0-9]+(?:[,\s]+[A-Za-z0-9]+)*))?")
JUSTIFICATION_SEPARATOR = " - "
MAXIMUM_REPORTED = 200
CATALOG_TIMEOUT_SECONDS = 120


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


def policy_errors(policy: dict, catalog: set[str]) -> list[str]:
    """Integridade da politica: catalogo coberto, motivos presentes, supressoes declaradas."""
    errors: list[str] = []
    if policy.get("schema_version") != 1:
        errors.append("politica: schema_version precisa ser 1")

    tool = policy.get("tool")
    if not isinstance(tool, dict) or tool.get("name") != "ruff":
        errors.append("politica: tool.name precisa ser 'ruff'")
    elif not re.fullmatch(r"\d+\.\d+\.\d+", str(tool.get("version", ""))):
        errors.append("politica: tool.version precisa ser versao fixada no formato X.Y.Z")

    if not re.fullmatch(r"py3\d{2}", str(policy.get("target_version", ""))):
        errors.append("politica: target_version precisa ser alvo explicito, como py312")

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
        if state not in REQUIRED_STATES:
            errors.append(f"politica: familia {prefix} com estado invalido: {state!r}")
            continue
        select = entry.get("select")
        ignore = entry.get("ignore")
        if not isinstance(select, list) or not isinstance(ignore, list):
            errors.append(f"politica: familia {prefix} precisa declarar select e ignore como listas")
            continue
        if state == "dismissed" and select:
            errors.append(f"politica: familia {prefix} dispensada nao pode selecionar regra")
        if state == "selected" and not select:
            errors.append(f"politica: familia {prefix} selecionada precisa de select nao vazio")
        reason = entry.get("reason")
        if state != "selected":
            if not isinstance(reason, str) or len(reason.strip()) < MINIMUM_REASON_CHARS:
                errors.append(
                    f"politica: familia {prefix} precisa de motivo escrito com pelo menos "
                    f"{MINIMUM_REASON_CHARS} caracteres"
                )
        elif reason not in (None, ""):
            errors.append(f"politica: familia {prefix} aplicada nao pode carregar motivo de dispensa")

    missing = sorted(catalog - seen)
    extra = sorted(seen - catalog)
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


def selection_of(policy: dict) -> tuple[list[str], list[str]]:
    select = sorted({code for entry in policy["families"] for code in entry.get("select", [])})
    ignore = sorted({code for entry in policy["families"] for code in entry.get("ignore", [])})
    return select, ignore


def catalog_of(errors: list[str]) -> set[str]:
    """Familias de regras que a ferramenta instalada declara conhecer."""
    try:
        completed = subprocess.run(
            ["ruff", "rule", "--all", "--output-format", "json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=CATALOG_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        errors.append("ruff: nao instalado; instalar pelo lockfile antes de validar")
        return set()
    except subprocess.TimeoutExpired:
        errors.append("ruff: tempo esgotado ao listar o catalogo de regras")
        return set()
    if completed.returncode != 0:
        errors.append(f"ruff: falha ao listar o catalogo: {completed.stderr.strip()[:200]}")
        return set()
    try:
        rules = json.loads(completed.stdout)
    except json.JSONDecodeError:
        errors.append("ruff: catalogo de regras em formato inesperado")
        return set()
    return {re.sub(r"[^A-Z]", "", str(rule.get("code", ""))) for rule in rules}


def installed_version(errors: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            ["ruff", "--version"], capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        errors.append("ruff: nao instalado; instalar pelo lockfile antes de validar")
        return None
    match = re.search(r"(\d+\.\d+\.\d+)", completed.stdout)
    if completed.returncode != 0 or not match:
        errors.append(f"ruff: versao ilegivel ({completed.stdout.strip()[:80]})")
        return None
    return match.group(1)


def python_files(root: Path) -> list[Path]:
    """Arquivos Python sob a raiz, excluindo o que nao e codigo versionado do catalogo."""
    excluded_parts = {".git", "__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache", "dist"}
    found = []
    for path in root.rglob("*.py"):
        if any(part in excluded_parts for part in path.parts):
            continue
        if not confined(path, root):
            continue
        found.append(path)
    return sorted(found)


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
    """Supressao precisa estar declarada na politica e justificada na propria linha."""
    allowed = {
        str(entry.get("code"))
        for entry in policy.get("allowed_suppressions", [])
        if isinstance(entry, dict)
    }
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append(f"{relative(path, root)}: ilegivel ou fora de UTF-8")
            continue
        for number, comment in comments_of(text):
            match = SUPPRESSION_RE.search(comment)
            if not match:
                continue
            where = f"{relative(path, root)}:{number}"
            codes = match.group("codes")
            if not codes:
                errors.append(f"{where}: supressao sem codigo de regra")
                continue
            for code in re.split(r"[,\s]+", codes.strip()):
                if code not in allowed:
                    errors.append(f"{where}: supressao de {code} fora da lista permitida na politica")
            if JUSTIFICATION_SEPARATOR not in comment[match.end():]:
                errors.append(f"{where}: supressao sem justificativa apos ' - '")


def run_tool(
    root: Path,
    target_version: str,
    line_length: int,
    select: list[str],
    ignore: list[str],
    files: list[Path],
    errors: list[str],
) -> list[dict]:
    """Executa a ferramenta sem cache, exatamente com a selecao declarada na politica."""
    if not files:
        return []
    command = [
        "ruff", "check",
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
            timeout=CATALOG_TIMEOUT_SECONDS * 5,
        )
    except FileNotFoundError:
        return []
    except subprocess.TimeoutExpired:
        errors.append("ruff: tempo esgotado ao analisar o codigo")
        return []
    if completed.returncode not in (0, 1):
        errors.append(f"ruff: execucao falhou: {completed.stderr.strip()[:200]}")
        return []
    try:
        return json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        errors.append("ruff: saida em formato inesperado")
        return []


def validate_lint(root: Path) -> list[str]:
    """Valida a politica e executa a analise com a selecao declarada."""
    root = root.resolve()
    errors: list[str] = []
    policy = load_policy(root, errors)
    if policy is None:
        return errors

    catalog = catalog_of(errors)
    errors.extend(policy_errors(policy, catalog))
    version = installed_version(errors)
    declared = str(policy.get("tool", {}).get("version", ""))
    if version and declared and version != declared:
        errors.append(f"ruff: versao instalada {version} diverge da declarada {declared}")

    select, ignore = selection_of(policy)
    files = python_files(root)
    suppression_errors(root, files, policy, errors)

    line_length = int((policy.get("line_length") or {}).get("value") or 0)
    if line_length <= 0:
        errors.append("politica: line_length.value precisa ser inteiro positivo")
    violations = run_tool(
        root, str(policy.get("target_version", "py312")), line_length, select, ignore, files, errors
    )
    for violation in violations:
        location = violation.get("location") or {}
        errors.append(
            f"{violation.get('filename')}:{location.get('row')}:{location.get('column')}: "
            f"{violation.get('code')} {violation.get('message')}"
        )
    if not errors:
        print(f"Lint OK: {len(files)} arquivo(s) Python sem violacao das regras aplicadas.")
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
