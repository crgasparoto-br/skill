#!/usr/bin/env python3
"""Varredura global de higiene: duplicação, código morto, dependência sem uso e complexidade.

A varredura é determinística e offline: a mesma árvore com a mesma política produz o mesmo
relatório, byte a byte, sem consultar a rede e sem depender da ordem do sistema de arquivos. Nada
aqui escreve no produto varrido: a saída é o relatório e, no script companheiro, os work items.

Cada classe declara o que **não** vê, porque uma classe que reivindica completude produz confiança
falsa. Os limites declarados são parte do contrato e vivem na política, não no código:

- `duplication`: compara corpos de função normalizados por AST, ignorando nome, literal de
  documentação e identificadores. Não vê duplicação entre linguagens, duplicação de bloco dentro de
  uma função, nem equivalência semântica entre corpos diferentes. Cópia declarada em
  `config/shared-files.json` é exclusão legítima, e não achado.
- `dead-module`: considera morto o módulo que nenhum outro módulo importa e que nenhuma invocação
  declarada alcança. Não vê referência montada em tempo de execução por nome de string fora de
  arquivo texto, nem plugin carregado por convenção de diretório.
- `dead-symbol`: considera morto o símbolo de nível de módulo cujo nome não aparece em nenhum lugar
  da árvore além da própria definição. Não vê uso por `getattr`, por nome montado ou por registro
  dinâmico, e por isso qualquer ocorrência do nome já conta como referência.
- `unused-dependency`: cruza os manifests declarados com os imports efetivos. Não vê import feito
  dentro de `try` de dependência opcional por caminho indireto, e trata a dependência declarada
  como ferramenta executada pela lista declarada na política.
- `complexity`: mede complexidade ciclomática por função. Não mede complexidade cognitiva, tamanho
  de arquivo nem acoplamento.

Arquivo ilegível, fora da raiz ou com erro de sintaxe entra em `not_analyzed`, nunca em silêncio: o
conjunto analisado não pode encolher sem aparecer no relatório.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

DEFAULT_POLICY = Path("config") / "hygiene-policy.json"
SHARED_FILES = Path("config") / "shared-files.json"
TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".sh", ".txt", ".toml", ".cfg", ".ini"}
NAME_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|md|json|ya?ml|sh|txt|toml|cfg|ini)\b")
CLASSES = ("duplication", "dead-module", "dead-symbol", "unused-dependency", "complexity")


class HygieneError(Exception):
    """Falha de leitura ou de política que impede a varredura de ser honesta."""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise HygieneError(f"arquivo ausente: {path}") from error
    except UnicodeDecodeError as error:
        raise HygieneError(f"arquivo nao esta em UTF-8: {path}") from error
    except OSError as error:
        raise HygieneError(f"arquivo ilegivel: {path} ({error.strerror or error.__class__.__name__})") from error


def load_policy(root: Path, policy_path: Path | None = None) -> dict:
    """Política de higiene; a ausência é erro, porque o padrão precisa ser declarado."""
    path = policy_path if policy_path is not None else root / DEFAULT_POLICY
    if not path.is_file():
        raise HygieneError(f"politica de higiene ausente: {path.name}")
    try:
        policy = json.loads(read_text(path))
    except json.JSONDecodeError as error:
        raise HygieneError(f"politica de higiene invalida: {error.msg}") from error
    if not isinstance(policy, dict):
        raise HygieneError("politica de higiene precisa ser objeto")
    return policy


def shared_declared_paths(root: Path) -> set[str]:
    """Caminhos declarados como cópia compartilhada ou fonte canônica em shared-files.json."""
    path = root / SHARED_FILES
    if not path.is_file():
        return set()
    try:
        document = json.loads(read_text(path))
    except json.JSONDecodeError:
        return set()
    declared: set[str] = set()
    for group in document.get("groups", []) if isinstance(document, dict) else []:
        if not isinstance(group, dict):
            continue
        canonical = group.get("canonical")
        if isinstance(canonical, str):
            declared.add(canonical)
        for copy in group.get("copies", []) if isinstance(group.get("copies"), list) else []:
            if isinstance(copy, str):
                declared.add(copy)
    return declared


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def scope_files(root: Path, policy: dict, paths: list[str] | None = None) -> tuple[list[Path], list[dict]]:
    """Arquivos no escopo declarado e arquivos recusados, que precisam aparecer no relatório."""
    scope = policy.get("scope") if isinstance(policy.get("scope"), dict) else {}
    suffixes = set(scope.get("include_suffixes") or [".py"])
    exclude_dirs = set(scope.get("exclude_dirs") or [])
    exclude_paths = set(scope.get("exclude_paths") or [])
    candidates: list[Path] = []
    if paths:
        for raw in paths:
            candidate = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
            if root.resolve() not in candidate.parents and candidate != root.resolve():
                raise HygieneError(f"caminho fora da raiz: {raw}")
            if candidate.is_dir():
                candidates.extend(candidate.rglob("*"))
            elif candidate.is_file():
                candidates.append(candidate)
    else:
        candidates.extend(root.rglob("*"))
    files: list[Path] = []
    refused: list[dict] = []
    for candidate in candidates:
        if not candidate.is_file() or candidate.suffix not in suffixes:
            continue
        rel = relative(candidate, root)
        parts = set(Path(rel).parts)
        if parts & exclude_dirs or rel in exclude_paths:
            continue
        files.append(candidate)
    return sorted(files, key=lambda item: relative(item, root)), refused


def parse_module(path: Path, root: Path) -> tuple[ast.Module | None, list[dict]]:
    rel = relative(path, root)
    try:
        text = read_text(path)
    except HygieneError as error:
        return None, [{"path": rel, "reason": str(error)}]
    try:
        return ast.parse(text), []
    except SyntaxError as error:
        return None, [{"path": rel, "reason": f"erro de sintaxe na linha {error.lineno}"}]


def qualname(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    """Nome qualificado do símbolo, subindo pelos escopos de função e de classe."""
    parts = [getattr(node, "name", "?")]
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parts.append(current.name)
        current = parents.get(current)
    return ".".join(reversed(parts))


def parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def cyclomatic_complexity(node: ast.AST) -> int:
    """Complexidade ciclomática: caminhos independentes contados a partir do corpo da função."""
    score = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.AsyncWith)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, ast.IfExp):
            score += 1
        elif isinstance(child, ast.comprehension):
            score += 1 + len(child.ifs)
        elif isinstance(child, ast.Match):
            score += len(child.cases)
    return score


def normalized_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Forma do corpo sem nome, sem literal de documentação e sem identificador."""
    body = [
        statement
        for statement in node.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if not body:
        return None
    dump = ast.dump(ast.Module(body=body, type_ignores=[]), annotate_fields=False)
    return re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*\b", "ID", dump)


def finding_identity(class_name: str, parts: list[str]) -> str:
    """Identidade estável do achado: derivada do conteúdo, sem número de linha."""
    digest = hashlib.sha256("\u0000".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{class_name}:{digest}"


def corpus_texts(root: Path, policy: dict) -> dict[str, str]:
    """Texto de todos os arquivos analisáveis da árvore, para as regras de referência."""
    scope = policy.get("scope") if isinstance(policy.get("scope"), dict) else {}
    exclude_dirs = set(scope.get("exclude_dirs") or [])
    texts: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        rel = relative(path, root)
        if set(Path(rel).parts) & exclude_dirs:
            continue
        try:
            texts[rel] = read_text(path)
        except HygieneError:
            continue
    return texts


def named_paths(texts: dict[str, str], root: Path) -> set[str]:
    """Caminhos citados por algum arquivo, resolvidos na raiz e no diretório de quem cita.

    A citação pode vir como caminho a partir da raiz (`scripts/x.py`), como caminho a partir do
    diretório do arquivo que cita (`scripts/x.py` dentro de uma skill) ou como nome solto. As três
    formas contam, porque todas são invocação declarada para quem lê a instrução.
    """
    named: set[str] = set()
    known = sorted(
        relative(path, root) for path in root.rglob("*") if path.is_file()
    )
    by_name: dict[str, list[str]] = defaultdict(list)
    for rel in known:
        by_name[Path(rel).name].append(rel)
    for rel, text in texts.items():
        directory = Path(rel).parent.as_posix()
        for token in NAME_RE.findall(text):
            cleaned = token.strip("./")
            if not cleaned:
                continue
            candidates = {cleaned, f"{directory}/{cleaned}" if directory != "." else cleaned}
            for candidate in candidates:
                if candidate in known:
                    named.add(candidate)
            named.update(by_name.get(Path(cleaned).name, []))
    return named


def detect_duplication(
    root: Path, policy: dict, modules: dict[str, ast.Module], texts: dict[str, str]
) -> list[dict]:
    config = policy["classes"]["duplication"]
    minimum = int(config.get("min_body_lines", 12))
    exclude_copies = bool(config.get("exclude_declared_copies", True))
    exclude_tests = bool(config.get("exclude_tests", True))
    declared = shared_declared_paths(root) if exclude_copies else set()
    groups: dict[str, list[str]] = defaultdict(list)
    for rel in sorted(modules):
        if rel in declared:
            continue
        path = Path(rel)
        if exclude_tests and (path.name.startswith("test_") or "tests" in path.parts):
            continue
        tree = modules[rel]
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            lines = (node.end_lineno or node.lineno) - node.lineno + 1
            if lines < minimum:
                continue
            form = normalized_body(node)
            if form:
                groups[form].append(f"{rel}::{node.name}")
    findings: list[dict] = []
    for form, members in groups.items():
        if len(members) < 2:
            continue
        for member in sorted(members):
            path, symbol = member.split("::", 1)
            peers = [other for other in sorted(members) if other != member]
            findings.append(
                {
                    "id": finding_identity("duplication", [path, symbol, form]),
                    "class": "duplication",
                    "location": member,
                    "path": path,
                    "symbol": symbol,
                    "detail": f"corpo normalizado identico em {len(members)} funcoes: {', '.join(peers)}",
                }
            )
    return findings


def detect_dead_modules(
    root: Path, policy: dict, modules: dict[str, ast.Module], texts: dict[str, str]
) -> list[dict]:
    config = policy["classes"]["dead-module"]
    declared_entries = {entry for entry in config.get("entry_points", []) if isinstance(entry, str)}
    named = named_paths(texts, root)
    imported: set[str] = set()
    for tree in modules.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    findings: list[dict] = []
    for rel in sorted(modules):
        path = Path(rel)
        if path.name == "__init__.py" or path.name.startswith("test_") or "tests" in path.parts:
            continue
        if rel in declared_entries or rel in named or path.name in named:
            continue
        module_name = rel[:-3].replace("/", ".")
        stem = path.stem
        if any(
            entry in (module_name, stem)
            or entry.endswith(("." + stem, "." + module_name))
            for entry in imported
        ):
            continue
        findings.append(
            {
                "id": finding_identity("dead-module", [rel]),
                "class": "dead-module",
                "location": rel,
                "path": rel,
                "detail": "nenhum modulo importa este arquivo e nenhuma invocacao declarada o alcanca",
            }
        )
    return findings


def detect_dead_symbols(
    root: Path, policy: dict, modules: dict[str, ast.Module], texts: dict[str, str]
) -> list[dict]:
    config = policy["classes"]["dead-symbol"]
    exclude_tests = bool(config.get("exclude_tests", True))
    ignore = {name for name in config.get("ignore_names", []) if isinstance(name, str)}
    corpus = "\n".join(texts.values())
    definitions: dict[str, list[str]] = defaultdict(list)
    for rel in sorted(modules):
        path = Path(rel)
        if exclude_tests and (path.name.startswith("test_") or "tests" in path.parts):
            continue
        tree = modules[rel]
        parents = parent_map(tree)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                definitions[node.name].append(f"{rel}::{qualname(node, parents)}")
    findings: list[dict] = []
    for name, places in sorted(definitions.items()):
        if name in ignore or name.startswith("__"):
            continue
        occurrences = len(re.findall(rf"\b{re.escape(name)}\b", corpus))
        if occurrences > len(places):
            continue
        for place in places:
            rel, symbol = place.split("::", 1)
            findings.append(
                {
                    "id": finding_identity("dead-symbol", [rel, symbol]),
                    "class": "dead-symbol",
                    "location": place,
                    "path": rel,
                    "symbol": symbol,
                    "detail": f"o nome {name!r} aparece apenas na definicao em toda a arvore",
                }
            )
    return findings


def detect_unused_dependencies(root: Path, policy: dict, texts: dict[str, str]) -> list[dict]:
    config = policy["classes"]["unused-dependency"]
    mapping = {
        str(key).lower(): str(value)
        for key, value in (config.get("import_name_map") or {}).items()
    }
    tools = {str(name).lower() for name in config.get("tool_dependencies", [])}
    manifests = sorted(
        path
        for path in root.rglob("requirements*.txt")
        if not path.name.endswith(".lock.txt")
    )
    findings: list[dict] = []
    for manifest in manifests:
        manifest_rel = relative(manifest, root)
        directory = manifest.parent
        prefix = "" if directory == root else directory.relative_to(root).as_posix() + "/"
        imported: set[str] = set()
        for rel in sorted(texts):
            if not rel.startswith(prefix) or not rel.endswith(".py"):
                continue
            try:
                tree = ast.parse(texts[rel])
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    imported.add(node.module.split(".")[0])
        try:
            lines = read_text(manifest).splitlines()
        except HygieneError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith(("#", "-")):
                continue
            name = re.split(r"[<>=!~\[;]", line, maxsplit=1)[0].strip()
            if not name:
                continue
            lowered = name.lower()
            if lowered in tools:
                continue
            import_name = mapping.get(lowered, lowered)
            if import_name.replace("-", "_") in imported or import_name in imported:
                continue
            findings.append(
                {
                    "id": finding_identity("unused-dependency", [manifest_rel, lowered]),
                    "class": "unused-dependency",
                    "location": f"{manifest_rel}::{lowered}",
                    "path": manifest_rel,
                    "symbol": lowered,
                    "detail": (
                        f"declarada em {manifest_rel} e nunca importada sob o nome {import_name!r} "
                        f"na arvore de {prefix or 'raiz'}"
                    ),
                }
            )
    return findings


def detect_complexity(policy: dict, modules: dict[str, ast.Module]) -> list[dict]:
    config = policy["classes"]["complexity"]
    limit = int(config.get("max_complexity", 30))
    findings: list[dict] = []
    for rel in sorted(modules):
        tree = modules[rel]
        parents = parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            score = cyclomatic_complexity(node)
            if score <= limit:
                continue
            symbol = qualname(node, parents)
            findings.append(
                {
                    "id": finding_identity("complexity", [rel, symbol]),
                    "class": "complexity",
                    "location": f"{rel}::{symbol}",
                    "path": rel,
                    "symbol": symbol,
                    "value": score,
                    "detail": f"complexidade ciclomatica {score} acima do teto declarado {limit}",
                }
            )
    return findings


def apply_policy_states(policy: dict, findings: list[dict]) -> tuple[list[dict], list[str]]:
    """Aplica exceções declaradas e calcula o estado de cada achado; devolve problemas da política."""
    accepted = {}
    for entry in policy.get("accepted", []) if isinstance(policy.get("accepted"), list) else []:
        if not isinstance(entry, dict):
            continue
        identity = entry.get("id")
        reason = entry.get("reason")
        if isinstance(identity, str):
            accepted[identity] = str(reason or "")
    problems: list[str] = []
    seen: set[str] = set()
    for finding in findings:
        identity = finding["id"]
        if identity in seen:
            problems.append(f"achado com identidade repetida: {identity}")
        seen.add(identity)
        reason = accepted.get(identity)
        if reason is None:
            finding["state"] = "open"
            finding.pop("justification", None)
        else:
            finding["state"] = "accepted"
            finding["justification"] = reason
    for identity, reason in sorted(accepted.items()):
        if identity in seen:
            continue
        problems.append(f"excecao declarada sem achado correspondente: {identity} ({reason[:60]})")
    return findings, problems


def build_report(root: Path, policy: dict, paths: list[str] | None = None) -> tuple[dict, list[str]]:
    """Relatório completo da varredura e problemas estruturais encontrados no caminho."""
    files, refused = scope_files(root, policy, paths)
    modules: dict[str, ast.Module] = {}
    not_analyzed: list[dict] = list(refused)
    for path in files:
        tree, problems = parse_module(path, root)
        if tree is None:
            not_analyzed.extend(problems)
            continue
        modules[relative(path, root)] = tree
    texts = corpus_texts(root, policy)
    findings: list[dict] = []
    findings.extend(detect_duplication(root, policy, modules, texts))
    findings.extend(detect_dead_modules(root, policy, modules, texts))
    findings.extend(detect_dead_symbols(root, policy, modules, texts))
    findings.extend(detect_unused_dependencies(root, policy, texts))
    findings.extend(detect_complexity(policy, modules))
    findings, problems = apply_policy_states(policy, findings)
    findings.sort(key=lambda item: (item["class"], item["location"]))
    not_analyzed.sort(key=lambda item: item["path"])
    classes = []
    for name in CLASSES:
        config = policy["classes"][name]
        members = [finding for finding in findings if finding["class"] == name]
        classes.append(
            {
                "name": name,
                "state": config.get("state", "gated"),
                "threshold": {
                    key: value
                    for key, value in config.items()
                    if key not in {"state", "limits", "reason"}
                },
                "open": sum(1 for finding in members if finding["state"] == "open"),
                "accepted": sum(1 for finding in members if finding["state"] == "accepted"),
                "findings": members,
            }
        )
    report = {
        "schema_version": 1,
        "system": "hygiene-report",
        "policy_system": policy.get("system"),
        "policy_schema_version": policy.get("schema_version"),
        "mode": "targeted" if paths else "sweep",
        "analyzed": len(modules),
        "not_analyzed": not_analyzed,
        "classes": classes,
        "summary": {
            "open": sum(1 for finding in findings if finding["state"] == "open"),
            "accepted": sum(1 for finding in findings if finding["state"] == "accepted"),
            "not_analyzed": len(not_analyzed),
        },
    }
    return report, problems


def render_markdown(report: dict) -> str:
    """Relatório em Markdown, para leitura humana."""
    lines = [
        "# Relatório de higiene global",
        "",
        f"- Modo: `{report['mode']}`",
        f"- Arquivos analisados: {report['analyzed']}",
        f"- Achados abertos: {report['summary']['open']}",
        f"- Achados aceitos por exceção declarada: {report['summary']['accepted']}",
        f"- Arquivos não analisados: {report['summary']['not_analyzed']}",
        "",
        "## Achados por classe",
        "",
        "| Classe | Estado | Abertos | Aceitos |",
        "| --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| `{entry['name']}` | `{entry['state']}` | {entry['open']} | {entry['accepted']} |"
        for entry in report["classes"]
    )
    for entry in report["classes"]:
        if not entry["findings"]:
            continue
        lines.extend(["", f"### `{entry['name']}`", ""])
        for finding in entry["findings"]:
            suffix = ""
            if finding["state"] == "accepted":
                suffix = f" — aceito: {finding.get('justification', '')}"
            lines.append(f"- `{finding['location']}` — {finding['detail']}{suffix}")
    if report["not_analyzed"]:
        lines.extend(["", "## Não analisados", ""])
        lines.extend(
            f"- `{entry['path']}` — {entry['reason']}" for entry in report["not_analyzed"]
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Varredura global de higiene do repositorio")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None, help="caminho do relatorio JSON")
    parser.add_argument("--markdown", type=Path, default=None, help="caminho do relatorio Markdown")
    parser.add_argument("--paths", nargs="*", default=None, help="modo direcionado a caminhos")
    args = parser.parse_args(argv)
    root = (args.root or Path()).resolve()
    try:
        policy = load_policy(root, args.policy)
        report, problems = build_report(root, policy, args.paths)
    except HygieneError as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 2
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.report:
        args.report.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    if args.markdown:
        args.markdown.write_text(render_markdown(report), encoding="utf-8")
    if problems:
        print("Problemas na politica:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
