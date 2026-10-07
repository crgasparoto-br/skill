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
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

DEFAULT_POLICY = Path("config") / "hygiene-policy.json"
SHARED_FILES = Path("config") / "shared-files.json"
IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
COMMENT_START_RE = re.compile(r"\s+#")
CLASSES = ("duplication", "dead-module", "dead-symbol", "unused-dependency", "complexity")


class HygieneError(Exception):
    """Falha de leitura ou de política que impede a varredura de ser honesta."""


def in_excluded_dir(rel: str, exclude_dirs: set[str]) -> bool:
    """Diretório excluído cobre a subárvore inteira, e a entrada declarada pode ser caminho composto.

    Comparar componente solto só funciona para nome simples: `evals/fixtures` na política não casaria
    com nenhum componente do caminho, e a subárvore declarada fora do escopo continuaria sendo lida.
    """
    parts = Path(rel).parts
    return any(
        declared and parts[: len(Path(declared).parts)] == Path(declared).parts
        for declared in exclude_dirs
    )


def scope_of(policy: dict) -> dict:
    """Seção de escopo da política, sempre um mapa."""
    scope = policy.get("scope")
    return scope if isinstance(scope, dict) else {}


def corpus_suffixes(policy: dict) -> set[str]:
    """Sufixos de arquivo texto conferidos na busca por citação, declarados na política.

    A busca por citação não vê formato fora desta lista. O limite precisa estar declarado: sufixo
    escondido no código produz falso positivo em classe `gated`, e a política é a única fonte disso.
    """
    declared = scope_of(policy).get("corpus_suffixes")
    if not isinstance(declared, list) or not declared:
        raise HygieneError("politica: scope.corpus_suffixes precisa declarar os sufixos de texto")
    return {str(suffix) for suffix in declared}


# Marcador de lugar fechado imediatamente antes do caminho, como `<skill>/scripts/x.py`. Um `>` solto,
# como em `echo >/orphan.py`, nao e ancora: tratar qualquer `>` como ancora deixaria caminho absoluto
# manter modulo vivo.
PLACEHOLDER_ANCHOR_RE = re.compile(r"<[^<>]*>$")


def citation_pattern(policy: dict) -> re.Pattern[str]:
    """Expressão que reconhece citação de caminho, montada dos sufixos declarados."""
    suffixes = {*corpus_suffixes(policy), *(scope_of(policy).get("include_suffixes") or [])}
    names = sorted(
        {re.escape(str(suffix).lstrip(".")) for suffix in suffixes if str(suffix).startswith(".")}
    )
    return re.compile(rf"[A-Za-z0-9_./-]+\.(?:{'|'.join(names)})\b")


def identifier_counts(texts: dict[str, str]) -> Counter[str]:
    """Contagem de cada identificador do corpus, em uma passada só.

    Contar por definição recompilando expressão sobre o corpus inteiro custa definições vezes corpus e
    torna o gate lento em árvore grande; uma passada mantém o custo proporcional ao corpus.
    """
    counts: Counter[str] = Counter()
    for text in texts.values():
        counts.update(IDENTIFIER_TOKEN_RE.findall(text))
    return counts


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise HygieneError(f"arquivo ausente: {path}") from error
    except UnicodeDecodeError as error:
        raise HygieneError(f"arquivo nao esta em UTF-8: {path}") from error
    except OSError as error:
        raise HygieneError(f"arquivo ilegivel: {path} ({error.strerror or error.__class__.__name__})") from error


# Chave de decisão obrigatória por classe: o validador e a varredura leem a mesma tabela, para que a
# varredura isolada não caia em default silencioso que o gate rejeitaria.
REQUIRED_CLASS_KEYS = {
    "duplication": ("min_body_lines", "exclude_declared_copies", "exclude_tests"),
    "dead-module": ("entry_points", "exclude_tests", "package_init_is_entry"),
    "dead-symbol": ("exclude_tests", "ignore_names"),
    "unused-dependency": ("import_name_map", "tool_dependencies"),
    "complexity": ("max_complexity",),
}


def missing_class_keys(policy: dict) -> list[str]:
    """Chaves de decisão ausentes, por classe, na ordem em que precisam ser declaradas."""
    classes = policy.get("classes") if isinstance(policy.get("classes"), dict) else {}
    missing: list[str] = []
    for name, required in sorted(REQUIRED_CLASS_KEYS.items()):
        config = classes.get(name) if isinstance(classes.get(name), dict) else {}
        missing.extend(
            f"classes.{name}.{key}" for key in required if key not in config
        )
    return missing


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
    missing = missing_class_keys(policy)
    if missing:
        # A varredura isolada precisa reprovar a política incompleta: aceitar aqui mediria a árvore com
        # semântica que a própria política não declarou.
        raise HygieneError(
            "politica: classes sem chave de decisao declarada: " + ", ".join(sorted(missing))
        )
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


def safe_relative(path: Path, root: Path) -> str:
    """Caminho relativo à raiz quando possível; fora dela, o caminho absoluto como está."""
    try:
        return relative(path, root)
    except ValueError:
        return path.as_posix()


def declared_exclusions(policy: dict) -> dict[str, str]:
    """Exclusão declarada de caminho: motivo escrito na política, nunca otimização silenciosa."""
    scope = policy.get("scope") if isinstance(policy.get("scope"), dict) else {}
    declared: dict[str, str] = {}
    for entry in scope.get("exclude_paths") or []:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            declared[entry["path"]] = str(entry.get("reason") or "")
    return declared


def scope_files(
    root: Path, policy: dict, paths: list[str] | None = None
) -> tuple[list[Path], list[dict], list[dict]]:
    """Arquivos no escopo, arquivos recusados e exclusões declaradas.

    Arquivo coberto que não pode ser lido entra em recusados com a causa, em vez de desaparecer do
    conjunto analisado: cobertura que encolhe em silêncio é indistinguível de aprovação.
    """
    root = root.resolve()
    scope = policy.get("scope") if isinstance(policy.get("scope"), dict) else {}
    suffixes = set(scope.get("include_suffixes") or [".py"])
    exclude_dirs = set(scope.get("exclude_dirs") or [])
    excluded = declared_exclusions(policy)
    candidates: list[Path] = []
    missing: list[dict] = []
    if paths:
        for raw in paths:
            candidate = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
            if not candidate.is_relative_to(root):
                raise HygieneError(f"caminho fora da raiz: {raw}")
            if candidate.is_dir():
                candidates.extend(candidate.rglob("*"))
            elif candidate.is_file():
                candidates.append(candidate)
            else:
                # Alvo que não existe não é escopo vazio: sem a recusa, um erro de digitação produziria
                # relatório limpo com modo direcionado, que é indistinguível de uma árvore sem achado.
                missing.append({"path": raw, "reason": "alvo direcionado que nao existe"})
    else:
        candidates.extend(root.rglob("*"))
    files: list[Path] = []
    refused: list[dict] = list(missing)
    for candidate in candidates:
        rel = safe_relative(candidate, root)
        if in_excluded_dir(rel, exclude_dirs) or rel in excluded:
            continue
        if candidate.is_dir():
            # Diretorio, ou link para diretorio, com sufixo coberto: nao e arquivo analisavel, e sair
            # do conjunto sem aparecer no relatorio seria cobertura encolhida em silencio.
            if candidate.suffix in suffixes:
                refused.append(
                    {
                        "path": rel,
                        "reason": (
                            "link simbolico para diretorio, e nao arquivo regular"
                            if candidate.is_symlink()
                            else "caminho coberto que e diretorio, e nao arquivo regular"
                        ),
                    }
                )
            continue
        if candidate.suffix not in suffixes:
            continue
        if candidate.is_symlink() and not candidate.exists():
            refused.append({"path": rel, "reason": "link simbolico quebrado: o alvo nao existe"})
            continue
        if not candidate.is_file():
            refused.append({"path": rel, "reason": "caminho coberto que nao e arquivo regular"})
            continue
        if not candidate.resolve().is_relative_to(root):
            refused.append({"path": rel, "reason": "o caminho resolve para fora da raiz do repositorio"})
            continue
        files.append(candidate)
    return sorted(files, key=lambda item: relative(item, root)), refused, [
        {"path": path, "reason": reason} for path, reason in sorted(excluded.items())
    ]


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


def own_scope_nodes(node: ast.AST) -> list[ast.AST]:
    """Nós do próprio escopo: função aninhada, lambda e classe aninhada são unidades separadas."""
    collected: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        collected.append(current)
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(current))
    return collected


def own_body_nodes(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Nós do corpo da própria função: sem decorator, sem default de parâmetro, sem corpo aninhado."""
    collected: list[ast.AST] = []
    stack = list(node.body)
    while stack:
        current = stack.pop()
        collected.append(current)
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        stack.extend(ast.iter_child_nodes(current))
    return collected


def cyclomatic_complexity(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Complexidade ciclomática da própria função.

    Conta só os ramos do próprio corpo: função aninhada é medida por si, e somá-la aqui inflaria a
    função externa. `with` não entra, porque não cria caminho independente — tratá-lo como ramo
    transformaria gestão de recurso em dívida inexistente. Default de parâmetro e decorator também não
    entram: eles são avaliados fora da função, e contá-los acusaria ramo que a função não tem.
    """
    score = 1
    for child in own_body_nodes(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler)):
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


class IdentifierNeutralizer(ast.NodeTransformer):
    """Troca identificador por marcador neutro, sem tocar em literal, operador nem nome de atributo.

    Substituir por expressão sobre o texto do dump alcançaria também o conteúdo de string literal, e
    dois corpos com constantes diferentes passariam por cópia. Trocar o campo no nó é preciso: só o
    identificador muda.
    """

    def visit_Name(self, node: ast.Name) -> ast.AST:
        node.id = "ID"
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.arg = "ID"
        return node

    def visit_keyword(self, node: ast.keyword) -> ast.AST:
        # `make(left=x)` e `make(right=x)` são chamadas diferentes: nome de argumento faz parte da
        # interface da chamada e seleciona parâmetro distinto, e não é nome local que se possa apagar.
        self.generic_visit(node)
        return node
    def visit_MatchAs(self, node: ast.MatchAs) -> ast.AST:
        if node.name:
            node.name = "ID"
        self.generic_visit(node)
        return node
    def visit_MatchStar(self, node: ast.MatchStar) -> ast.AST:
        if node.name:
            node.name = "ID"
        self.generic_visit(node)
        return node
    def visit_MatchMapping(self, node: ast.MatchMapping) -> ast.AST:
        if node.rest:
            node.rest = "ID"
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.name = "ID"
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.name = "ID"
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        node.name = "ID"
        self.generic_visit(node)
        return node


def body_statements(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.stmt]:
    """Instruções do corpo, sem o literal de documentação.

    Só a primeira instrução pode ser docstring: tratar qualquer `Expr(Constant(str))` como documentação
    apagaria literal de expressão e faria dois corpos com constantes diferentes passarem por cópia.
    """
    body = list(node.body)
    if body and is_docstring(body[0]):
        body = body[1:]
    return body


def body_code_lines(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Linhas de código do corpo, contadas por instrução.

    Instrução de várias linhas conta uma, e linha vazia ou comentário não conta: o limiar mede código, e
    não a distância física entre a primeira e a última instrução, que linha em branco nenhuma infla.
    """
    return len(body_statements(node))


def normalized_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    """Forma do corpo sem nome de variável, parâmetro, função chamada e literal de documentação.

    Só identificador é apagado: nome de variável, de parâmetro, de função chamada e de definição
    aninhada. Operador, constante e nome de atributo permanecem: somar e subtrair o mesmo valor não
    são a mesma função, e chamar `upper` não é chamar `lower`. Apagar tudo isso produziria cópia onde
    não existe cópia, que é o erro mais caro desta classe; apagar menos faria a renomeação de uma
    variável esconder a cópia, que é o segundo erro mais caro.
    """
    body = body_statements(node)
    if not body:
        return None
    neutral = deepcopy(ast.Module(body=body, type_ignores=[]))
    IdentifierNeutralizer().visit(neutral)
    return ast.dump(neutral)


def is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def disambiguate(places: list[tuple[str, str]]) -> list[str]:
    """Rótulo estável por definição: nome repetido no mesmo arquivo ganha ordem, sem número de linha.

    Redefinir o mesmo nome é Python legal, e duas definições com o mesmo rótulo produziriam achados com
    identidade repetida: o relatório não distinguiria as duas e o gate reprovaria a árvore por uma
    ambiguidade do rótulo, não do código.
    """
    seen: dict[tuple[str, str], int] = defaultdict(int)
    labels: list[str] = []
    for rel, symbol in places:
        seen[(rel, symbol)] += 1
        order = seen[(rel, symbol)]
        labels.append(f"{rel}::{symbol}" if order == 1 else f"{rel}::{symbol}#{order}")
    return labels


def finding_identity(class_name: str, parts: list[str]) -> str:
    """Identidade estável do achado: derivada do conteúdo, sem número de linha."""
    digest = hashlib.sha256("\u0000".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{class_name}:{digest}"


def corpus_texts(root: Path, policy: dict) -> tuple[dict[str, str], list[dict]]:
    """Texto dos arquivos analisáveis da árvore, para as regras de referência, e o que ficou fora.

    Link que resolve para fora da raiz e arquivo ilegível são cobertura que não foi lida: entram no
    relatório em vez de sumir, porque cobertura que encolhe em silêncio é indistinguível de aprovação,
    e link externo é justamente por onde um texto de fora poderia apagar achado da árvore.
    """
    exclude_dirs = set(scope_of(policy).get("exclude_dirs") or [])
    excluded_paths = set(declared_exclusions(policy))
    suffixes = corpus_suffixes(policy)
    resolved_root = root.resolve()
    texts: dict[str, str] = {}
    refused: list[dict] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        rel = relative(path, root)
        if in_excluded_dir(rel, exclude_dirs) or rel in excluded_paths:
            continue
        if path.suffix not in suffixes:
            continue
        if path.is_symlink() and not path.is_file():
            # Link quebrado, ou link para caminho que não é arquivo regular, é cobertura de texto que
            # não foi lida: some do conjunto e o relatório declararia árvore limpa sem ter lido tudo.
            refused.append({"path": rel, "reason": "link simbolico quebrado no corpus de citacao"})
            continue
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(resolved_root):
            refused.append({"path": rel, "reason": "caminho de corpus que resolve para fora da raiz"})
            continue
        try:
            texts[rel] = read_text(path)
        except HygieneError:
            refused.append({"path": rel, "reason": "arquivo de corpus ilegivel"})
    return texts, refused


def named_paths(texts: dict[str, str], root: Path, pattern: re.Pattern[str]) -> set[str]:
    """Caminhos citados por algum arquivo, resolvidos na raiz e no diretório de quem cita.

    A citação pode vir como caminho a partir da raiz (`scripts/x.py`), como caminho a partir do
    diretório do arquivo que cita (`scripts/x.py` dentro de uma skill) ou como nome solto. As três
    formas contam, porque todas são invocação declarada para quem lê a instrução.
    """
    named: set[str] = set()
    known = {relative(path, root) for path in root.rglob("*") if path.is_file()}
    by_name: dict[str, list[str]] = defaultdict(list)
    for rel in sorted(known):
        by_name[Path(rel).name].append(rel)
    for rel, text in texts.items():
        directory = Path(rel).parent.as_posix()
        skill_root = Path(rel).parts[0] if len(Path(rel).parts) > 1 else ""
        for match in pattern.finditer(text):
            cleaned = match.group(0).removeprefix("./")
            if cleaned.startswith("/"):
                # A barra inicial só é âncora quando o caminho vem logo depois de um marcador de lugar,
                # como em `<skill>/scripts/x.py`: fora disso é caminho absoluto, que não é citação de
                # arquivo da árvore e não pode manter módulo vivo.
                if not PLACEHOLDER_ANCHOR_RE.search(text[: match.start()]):
                    continue
                cleaned = cleaned.lstrip("/")
            parts = Path(cleaned).parts
            # Citação que sai da raiz não é invocação declarada de arquivo da árvore.
            if not cleaned or ".." in parts:
                continue
            candidates = {cleaned}
            if directory != ".":
                candidates.add(f"{directory}/{cleaned}")
            if skill_root:
                candidates.add(f"{skill_root}/{cleaned}")
            matched = {candidate for candidate in candidates if candidate in known}
            if not matched and len(parts) == 1:
                # Nome solto alcança o arquivo de mesmo nome só quando ele é único na árvore: havendo
                # homônimos, o nome solto é ambíguo e não identifica invocação de nenhum deles.
                homonyms = by_name.get(cleaned, [])
                if len(homonyms) == 1:
                    matched = {homonyms[0]}
            named.update(matched)
    return named


def detect_duplication(
    root: Path, policy: dict, modules: dict[str, ast.Module], texts: dict[str, str]
) -> list[dict]:
    config = policy["classes"]["duplication"]
    if "min_body_lines" not in config:
        raise HygieneError("politica: classes.duplication.min_body_lines precisa ser declarado")
    minimum = int(config["min_body_lines"])
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
        every: list[tuple[int, int, str]] = []
        measured: list[tuple[int, int, str, str]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            every.append((node.lineno, node.col_offset, node.name))
            if body_code_lines(node) < minimum:
                continue
            form = normalized_body(node)
            if form:
                measured.append((node.lineno, node.col_offset, node.name, form))
        # Ordem de aparição é a do texto: a travessia da árvore não garante essa ordem, e o rótulo sem
        # sufixo pertence à primeira definição do arquivo, mesmo que ela fique abaixo do limiar: numerar
        # só o que passou pelo limiar daria a mesma localização a duas definições diferentes.
        every.sort()
        measured.sort()
        labels = dict(
            zip(
                [(line, column, name) for line, column, name in every],
                disambiguate([(rel, name) for _, _, name in every]),
                strict=True,
            )
        )
        for line, column, name, form in measured:
            groups[form].append(labels[(line, column, name)])
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


def resolve_import(imported: set[str], package: list[str], parts: list[str]) -> None:
    """Acrescenta as formas resolvidas de um nome importado ao conjunto de módulos alcançados."""
    if not parts:
        return
    imported.add(".".join(parts))
    if package:
        imported.add(".".join([*package, *parts]))


def imported_modules(modules: dict[str, ast.Module]) -> set[str]:
    """Módulos importados, resolvidos contra a raiz e contra o diretório de quem importa.

    Três formas precisam ser resolvidas para não acusar falso positivo nem falso negativo:

    - absoluta a partir da raiz (`import scripts.catalog`), resolvida pela raiz;
    - absoluta entre irmãos de diretório (`from handoff_origin import x`), porque script de skill roda
      com o próprio diretório no caminho de importação, resolvida contra o diretório de quem importa;
    - relativa (`from . import orphan`), resolvida contra o pacote de quem importa, que é o que impede
      a colisão de nome: o relativo alcança `pkg/orphan.py`, e não um `orphan.py` solto na raiz.
    """
    # `from .. import x` sobe para fora do pacote de quem importa; alcançar a raiz só é válido se a
    # própria raiz for pacote declarado, e sem isso o import não alcança módulo nenhum.
    root_is_package = "__init__.py" in modules
    imported: set[str] = set()
    for rel, tree in modules.items():
        package = list(Path(rel).parent.parts)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolve_import(imported, package, alias.name.split("."))
            elif isinstance(node, ast.ImportFrom):
                depth = node.level - 1
                # Import relativo além do pacote é inválido e não alcança módulo nenhum; resolver por
                # aproximação manteria vivo um módulo que ninguém importa.
                if depth > len(package) or (node.level == 1 and not package):
                    continue
                if depth == len(package) and not root_is_package:
                    continue
                base = [*package[: len(package) - depth], *(node.module.split(".") if node.module else [])]
                resolve_import(imported, package, base)
                for alias in node.names:
                    resolve_import(imported, package, [*base, alias.name])
    return imported


def detect_dead_modules(
    root: Path, policy: dict, modules: dict[str, ast.Module], texts: dict[str, str]
) -> list[dict]:
    config = policy["classes"]["dead-module"]
    exclude_tests = bool(config.get("exclude_tests", False))
    package_init_is_entry = bool(config.get("package_init_is_entry", False))
    declared_entries = {entry for entry in config.get("entry_points", []) if isinstance(entry, str)}
    named = named_paths(texts, root, citation_pattern(policy))
    imported = imported_modules(modules)
    findings: list[dict] = []
    for rel in sorted(modules):
        path = Path(rel)
        if package_init_is_entry and path.name == "__init__.py":
            continue
        if exclude_tests and (path.name.startswith("test_") or "tests" in path.parts):
            continue
        if rel in declared_entries or rel in named:
            continue
        if rel[:-3].replace("/", ".") in imported:
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


def assigned_names(node: ast.stmt) -> list[str]:
    """Nomes simples atribuídos no nível do módulo; desempacotamento e alvo não textual ficam fora."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [target.id for target in targets if isinstance(target, ast.Name) and target.id.isidentifier()]


def detect_dead_symbols(
    root: Path, policy: dict, modules: dict[str, ast.Module], texts: dict[str, str]
) -> list[dict]:
    config = policy["classes"]["dead-symbol"]
    exclude_tests = bool(config.get("exclude_tests", True))
    ignore = {name for name in config.get("ignore_names", []) if isinstance(name, str)}
    counts = identifier_counts(texts)
    definitions: dict[str, list[str]] = defaultdict(list)
    for rel in sorted(modules):
        path = Path(rel)
        if exclude_tests and (path.name.startswith("test_") or "tests" in path.parts):
            continue
        tree = modules[rel]
        parents = parent_map(tree)
        # Escopo do modulo inclui o que roda dentro de controle de fluxo: `if`, `try` e `with` no nivel
        # do modulo ligam nome no namespace do modulo, e ignorar isso deixaria simbolo morto invisivel.
        entries: list[tuple[int, int, str, str, str]] = []
        for node in own_scope_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                entries.append((node.lineno, node.col_offset, node.name, rel, qualname(node, parents)))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                entries.extend(
                    (node.lineno, node.col_offset, assigned, rel, assigned)
                    for assigned in assigned_names(node)
                )
        entries.sort()
        labels = disambiguate([(entry_rel, place) for _, _, _, entry_rel, place in entries])
        for (_, _, key, _, _), label in zip(entries, labels, strict=True):
            definitions[key].append(label)
    findings: list[dict] = []
    for name, places in sorted(definitions.items()):
        if name in ignore:
            continue
        if counts.get(name, 0) > len(places):
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


def normalize_target(raw: str) -> str:
    """Alvo do modo direcionado em forma canônica: sem prefixo `./` e sem barra final.

    `sub`, `./sub` e `sub/` são o mesmo diretório, e comparar a string bruta faria o manifest da
    subárvore desaparecer em duas das três formas.
    """
    return raw.strip().removeprefix("./").rstrip("/")


def in_targets(rel: str, targets: set[str]) -> bool:
    """Alvo do modo direcionado cobre o caminho e a subárvore, como no conjunto analisado."""
    return not targets or any(rel == target or rel.startswith(target + "/") for target in targets)


def scoped_manifests(
    root: Path, policy: dict, paths: list[str] | None
) -> tuple[list[Path], list[dict]]:
    """Manifests no escopo declarado, e o que ficou fora por resolver para fora da raiz.

    Manifest é lido do disco: link que resolve para fora da árvore entraria como declaração de fora e
    faria o resultado depender de arquivo que a varredura não mede.
    """
    exclude_dirs = set(scope_of(policy).get("exclude_dirs") or [])
    excluded_paths = set(declared_exclusions(policy))
    targets = {normalize_target(raw) for raw in (paths or []) if normalize_target(raw)}
    resolved_root = root.resolve()
    manifests: list[Path] = []
    refused: list[dict] = []
    for path in sorted(root.rglob("requirements*.txt")):
        if path.name.endswith(".lock.txt"):
            continue
        rel = relative(path, root)
        if in_excluded_dir(rel, exclude_dirs) or rel in excluded_paths or not in_targets(rel, targets):
            continue
        if not path.resolve().is_relative_to(resolved_root):
            refused.append({"path": rel, "reason": "manifest que resolve para fora da raiz"})
            continue
        manifests.append(path)
    return manifests, refused


def detect_unused_dependencies(
    root: Path, policy: dict, modules: dict[str, ast.Module], paths: list[str] | None = None
) -> tuple[list[dict], list[dict]]:
    """Requisito declarado e nunca importado no escopo do manifest.

    Manifest fora do escopo — em diretório excluído, em caminho excluído ou fora do modo direcionado —
    não é analisado: a política de escopo vale para todas as classes, e ler manifest excluído produziria
    achado de uma árvore que a varredura declara não estar medindo.
    """
    config = policy["classes"]["unused-dependency"]
    mapping = {
        str(key).lower(): str(value)
        for key, value in (config.get("import_name_map") or {}).items()
    }
    tools = {str(name).lower() for name in config.get("tool_dependencies", [])}
    manifests, refused = scoped_manifests(root, policy, paths)
    findings: list[dict] = []
    for manifest in manifests:
        manifest_rel = relative(manifest, root)
        directory = manifest.parent
        prefix = "" if directory == root else directory.relative_to(root).as_posix() + "/"
        imported: set[str] = set()
        for rel, tree in sorted(modules.items()):
            if not rel.startswith(prefix) or not rel.endswith(".py"):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    imported.add(node.module.split(".")[0])
        try:
            try:
                lines = read_text(manifest).splitlines()
            except HygieneError as error:
                # Manifest é entrada da classe: falha de leitura não pode sair do relatório só porque o
                # sufixo dele não está no corpus de citação.
                refused.append({"path": relative(manifest, root), "reason": str(error)})
                continue
        except HygieneError:
            continue
        for raw in lines:
            line = COMMENT_START_RE.split(raw, maxsplit=1)[0].strip()
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
    return findings, refused


def detect_complexity(policy: dict, modules: dict[str, ast.Module]) -> list[dict]:
    config = policy["classes"]["complexity"]
    if "max_complexity" not in config:
        raise HygieneError("politica: classes.complexity.max_complexity precisa ser declarado")
    limit = int(config["max_complexity"])
    findings: list[dict] = []
    for rel in sorted(modules):
        tree = modules[rel]
        parents = parent_map(tree)
        every: list[tuple[int, int, str]] = []
        measured: list[tuple[int, int, str, int]] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            symbol_of_node = qualname(node, parents)
            every.append((node.lineno, node.col_offset, symbol_of_node))
            score = cyclomatic_complexity(node)
            if score <= limit:
                continue
            measured.append((node.lineno, node.col_offset, symbol_of_node, score))
        every.sort()
        measured.sort()
        labels = dict(
            zip(
                every,
                disambiguate([(rel, symbol) for _, _, symbol in every]),
                strict=True,
            )
        )
        for label, (_, _, _, score) in [
            (labels[(line, column, symbol)], (line, column, symbol, score))
            for line, column, symbol, score in measured
        ]:
            symbol = label.split("::", 1)[1]
            findings.append(
                {
                    "id": finding_identity("complexity", [rel, label, str(score)]),
                    "class": "complexity",
                    "location": label,
                    "path": rel,
                    "symbol": symbol,
                    "value": score,
                    "detail": f"complexidade ciclomatica {score} acima do teto declarado {limit}",
                }
            )
    return findings


def apply_policy_states(policy: dict, findings: list[dict]) -> tuple[list[dict], list[str]]:
    """Aplica exceções declaradas e calcula o estado de cada achado; devolve problemas da política.

    Classe medida contra linha de base não aceita exceção item a item: a dívida dela é agregada e
    medida contra a história declarada, e aceitar um item esconderia justamente a contagem que a
    linha de base existe para medir.
    """
    classes = policy.get("classes") if isinstance(policy.get("classes"), dict) else {}
    measured = {
        name
        for name, config in classes.items()
        if isinstance(config, dict) and config.get("state") == "reported"
    }
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
        if reason is not None and finding["class"] in measured:
            problems.append(
                f"classe medida contra linha de base nao aceita excecao: {identity} "
                f"(a divida e agregada: ajuste a linha de base com motivo declarado)"
            )
            reason = None
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
    root = Path(root).resolve()
    files, refused, excluded = scope_files(root, policy, paths)
    modules: dict[str, ast.Module] = {}
    not_analyzed: list[dict] = list(refused)
    for path in files:
        tree, problems = parse_module(path, root)
        if tree is None:
            not_analyzed.extend(problems)
            continue
        modules[relative(path, root)] = tree
    texts, refused_corpus = corpus_texts(root, policy)
    not_analyzed.extend(refused_corpus)
    findings: list[dict] = []
    findings.extend(detect_duplication(root, policy, modules, texts))
    findings.extend(detect_dead_modules(root, policy, modules, texts))
    findings.extend(detect_dead_symbols(root, policy, modules, texts))
    dependency_findings, refused_manifests = detect_unused_dependencies(root, policy, modules, paths)
    not_analyzed.extend(refused_manifests)
    findings.extend(dependency_findings)
    findings.extend(detect_complexity(policy, modules))
    findings, problems = apply_policy_states(policy, findings)
    findings.sort(key=lambda item: (item["class"], item["location"]))
    # Um caminho pode ser recusado por mais de uma leitura — escopo e corpus —, e o relatório precisa
    # de uma entrada por caminho: duplicata de cobertura inflaria a contagem sem informar nada novo.
    not_analyzed = list({entry["path"]: entry for entry in not_analyzed}.values())
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
        "excluded": excluded,
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
    parser.add_argument("--paths", nargs="+", default=None, help="modo direcionado a caminhos")
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
