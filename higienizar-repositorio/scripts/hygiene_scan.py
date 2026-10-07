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
import fnmatch
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

# A varredura não escreve na árvore analisada, e bytecode de módulo importado é escrita: sem isto, a
# própria execução deixaria `__pycache__` dentro da raiz que ela afirma não alterar.
sys.dont_write_bytecode = True

DEFAULT_POLICY = Path("config") / "hygiene-policy.json"
SHARED_FILES = Path("config") / "shared-files.json"
def identifier_tokens(text: str) -> list[str]:
    """Identificadores do texto, pela gramática de identificador de Python.

    Classe de caractere não cobre a gramática: marca combinante e símbolo aceito por `str.isidentifier()`
    ficam de fora, e a contagem textual acusaria símbolo morto em código que se referencia. A regra é a
    do próprio interpretador, aplicada caractere a caractere, com o custo de uma passada por arquivo.
    """
    tokens: list[str] = []
    current = ""
    for character in text:
        if current and f"{current}{character}".isidentifier():
            current += character
            continue
        if current:
            tokens.append(current)
            current = ""
        if character == "_" or character.isidentifier():
            current = character
    if current:
        tokens.append(current)
    return tokens
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


# Caractere que não pode fazer parte de nome de arquivo: a coleta para trás para aqui. Deliberadamente
# curto, porque nome Unicode, inclusive com marca combinante, precisa ser recolhido como qualquer outro.
PATH_STOP_CHARS = frozenset(" \t\n\r\"'`()[]{}<>,;:=|*?")


def citation_suffixes(policy: dict) -> set[str]:
    """Sufixos que ancoram citação de caminho: os do corpus e os das classes cobertas."""
    suffixes = {*corpus_suffixes(policy), *(scope_of(policy).get("include_suffixes") or [])}
    return {str(suffix) for suffix in suffixes if str(suffix).startswith(".")}


def citation_paths(text: str, suffixes: set[str]) -> list[tuple[str, int]]:
    """Caminhos citados no texto, com a posição do início de cada um.

    O sufixo declarado ancora o fim do caminho e o início é recolhido para trás até um caractere que não
    pode fazer parte de nome de arquivo. Montar isso como classe de caractere deixaria de fora nome
    Unicode com marca combinante, e o arquivo seria acusado de morto com a citação presente no texto.
    """
    endings = sorted(suffixes, key=len, reverse=True)
    if not endings:
        return []
    pattern = re.compile("|".join(re.escape(suffix) for suffix in endings))
    found: list[tuple[str, int]] = []
    for match in pattern.finditer(text):
        end = match.end()
        if end < len(text) and (text[end] == "." or f"a{text[end]}".isidentifier()):
            # `x.pyc`, `x.py.bak` e `x.py` seguido de marca combinante não citam `x.py`: o sufixo
            # declarado seguido de caractere que continua identificador pertence a outro nome.
            continue
        start = end
        while start > 0 and text[start - 1] not in PATH_STOP_CHARS:
            start -= 1
        candidate = text[start:end]
        if len(candidate) > len(match.group(0)):
            found.append((candidate, start))
    return found


def identifier_counts(texts: dict[str, str]) -> Counter[str]:
    """Contagem de cada identificador do corpus, em uma passada só.

    Contar por definição recompilando expressão sobre o corpus inteiro custa definições vezes corpus e
    torna o gate lento em árvore grande; uma passada mantém o custo proporcional ao corpus.
    """
    counts: Counter[str] = Counter()
    for text in texts.values():
        counts.update(identifier_tokens(text))
    return counts


def read_text(path: Path, label: str | None = None) -> str:
    name = label or path.name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise HygieneError(f"arquivo ausente: {path}") from error
    except UnicodeDecodeError as error:
        raise HygieneError(f"arquivo nao esta em UTF-8: {name}") from error
    except OSError as error:
        raise HygieneError(
            f"arquivo ilegivel: {name} ({error.strerror or error.__class__.__name__})"
        ) from error


# Chave de decisão obrigatória por classe: o validador e a varredura leem a mesma tabela, para que a
# varredura isolada não caia em default silencioso que o gate rejeitaria.
REQUIRED_CLASS_KEYS = {
    "duplication": ("min_body_lines", "exclude_declared_copies", "exclude_tests"),
    "dead-module": ("entry_points", "exclude_tests", "package_init_is_entry"),
    "dead-symbol": ("exclude_tests", "ignore_names"),
    "unused-dependency": ("import_name_map", "tool_dependencies", "manifest_patterns"),
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
    """Caminho relativo à raiz; fora dela, apenas o nome do arquivo.

    Caminho absoluto no relatório faria duas cópias equivalentes da mesma árvore produzirem relatórios
    diferentes, e o relatório é a evidência que precisa ser comparável entre cópias.
    """
    try:
        return relative(path, root)
    except ValueError:
        # A raiz do sistema não tem nome: o rótulo precisa existir para o relatório manter contrato.
        return path.name or path.anchor or "."


def declared_exclusions(policy: dict) -> dict[str, str]:
    """Exclusão declarada de caminho: motivo escrito na política, nunca otimização silenciosa."""
    scope = policy.get("scope") if isinstance(policy.get("scope"), dict) else {}
    declared: dict[str, str] = {}
    for entry in scope.get("exclude_paths") or []:
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            declared[entry["path"]] = str(entry.get("reason") or "")
    return declared


def walk_scope(start: Path, root: Path, skip: set[str]) -> tuple[list[Path], list[dict]]:
    """Todos os caminhos sob `start`, e o que não pôde ser percorrido.

    `rglob` não desce diretório sem permissão de leitura e não avisa, e não segue link para diretório: a
    varredura mediria menos do que o escopo inclui e ainda assim declararia cobertura completa. Diretório
    excluído por declaração não é percorrido nem recusado, porque a exclusão já está no relatório.
    A recusa é sempre relativa a `root`: no modo direcionado o início é o alvo, e dois alvos com o mesmo
    nome de diretório recusado ficariam indistinguíveis se o caminho fosse relativo ao alvo.
    """
    found: list[Path] = []
    refused: list[dict] = []
    pending = [start]
    while pending:
        current = pending.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda item: item.as_posix())
        except OSError as error:
            refused.append(
                {
                    "path": safe_relative(current, root) or ".",
                    "reason": f"diretorio ilegivel ({error.strerror or error.__class__.__name__})",
                }
            )
            continue
        for entry in entries:
            rel = safe_relative(entry, root)
            if in_excluded_dir(rel, skip):
                continue
            found.append(entry)
            if entry.is_symlink() and entry.is_dir():
                # Link de diretório não é seguido: entrar nele mediria fora da raiz em silêncio.
                refused.append(
                    {
                        "path": rel,
                        "reason": "link simbolico para diretorio: a varredura nao segue link",
                    }
                )
                continue
            if entry.is_dir():
                pending.append(entry)
    return found, refused


def normalized_targets(root: Path, paths: list[str] | None) -> set[str] | None:
    """Alvos do modo direcionado em forma canônica relativa à raiz; `None` quando não há restrição.

    Alvo absoluto dentro da raiz e `.` precisam virar o mesmo caminho relativo que o resto do relatório
    usa, senão a subárvore seria analisada e o manifest dela ficaria de fora. Conjunto vazio e conjunto
    sem restrição são coisas diferentes: alvo que escapa deixa o escopo vazio, e não a árvore inteira.
    """
    if not paths:
        # Ausência de alvo é ausência de restrição; conjunto vazio significa escopo vazio.
        return None
    targets: set[str] = set()
    for raw in paths:
        try:
            candidate = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        except (OSError, RuntimeError):
            # Link quebrado ou em ciclo não resolve: a recusa já está no conjunto analisado, e aqui o
            # alvo simplesmente não restringe manifest nenhum.
            continue
        if not candidate.is_relative_to(root):
            # Alvo que escapa já é recusa visível no conjunto analisado; aqui ele simplesmente não
            # alcança manifest nenhum, porque não há manifest dentro de caminho fora da raiz.
            continue
        rel = safe_relative(candidate, root)
        if not rel or rel == ".":
            # `.` e a propria raiz: cobre a arvore inteira, e comparar com "." deixaria o manifest da
            # subarvore de fora enquanto os arquivos eram analisados.
            return None
        targets.add(rel)
    return targets


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
        for raw in sorted(paths):
            literal = root / raw if not Path(raw).is_absolute() else Path(raw)
            if literal.is_symlink() and not literal.exists():
                # Link quebrado ou em ciclo: o percurso livre recusa pelo caminho literal, e o modo
                # direcionado precisa do mesmo rótulo, em vez de seguir para um alvo que não existe.
                missing.append(
                    {
                        "path": safe_relative(literal, root),
                        "reason": "link simbolico quebrado: o alvo nao existe",
                    }
                )
                continue
            try:
                candidate = literal.resolve()
            except (OSError, RuntimeError):
                # Ciclo de link não resolve, e abortar deixaria a varredura sem relatório nenhum: a
                # recusa visível é o que mantém o conjunto analisado honesto.
                missing.append(
                    {
                        "path": safe_relative(literal, root),
                        "reason": "link simbolico em ciclo: o alvo nao resolve",
                    }
                )
                continue
            if not candidate.is_relative_to(root):
                # Alvo que resolve para fora é cobertura não analisada, e não erro fatal: o sweep já
                # recusa o mesmo link, e abortar no modo direcionado seria contrato diferente por modo.
                missing.append(
                    {
                        "path": safe_relative(literal, root),
                        "reason": "alvo direcionado que resolve para fora da raiz",
                    }
                )
                continue
            if candidate.is_dir():
                walked, refusals = walk_scope(candidate, root, exclude_dirs)
                candidates.extend(walked)
                missing.extend(refusals)
            elif candidate.is_file():
                candidates.append(candidate)
            else:
                # Alvo que não existe não é escopo vazio: sem a recusa, um erro de digitação produziria
                # relatório limpo com modo direcionado, que é indistinguível de uma árvore sem achado. O
                # caminho é o canônico relativo, porque publicar o caminho informado faria o relatório
                # depender de onde a árvore está no disco.
                missing.append(
                    {
                        "path": safe_relative(literal, root),
                        "reason": "alvo direcionado que nao existe",
                    }
                )
    else:
        walked, refusals = walk_scope(root, root, exclude_dirs)
        candidates.extend(walked)
        missing.extend(refusals)
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
        text = read_text(path, rel)
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
    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> ast.AST:
        # `except Error as first` e `except Error as second` diferem só no nome local da exceção.
        if node.name:
            node.name = "ID"
        self.generic_visit(node)
        return node
    def visit_Global(self, node: ast.Global) -> ast.AST:
        node.names = ["ID"] * len(node.names)
        return node
    def visit_Nonlocal(self, node: ast.Nonlocal) -> ast.AST:
        node.names = ["ID"] * len(node.names)
        return node
    def visit_Import(self, node: ast.Import) -> ast.AST:
        # Só o apelido é nome local; o módulo importado é semântica da chamada e permanece.
        for alias in node.names:
            if alias.asname:
                alias.asname = "ID"
        return node
    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST:
        for alias in node.names:
            if alias.asname:
                alias.asname = "ID"
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
    walked, refusals = walk_scope(root, root, exclude_dirs)
    refused.extend(refusals)
    for path in sorted(walked, key=lambda item: item.as_posix()):
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


def named_paths(
    texts: dict[str, str], root: Path, suffixes: set[str], policy: dict
) -> dict[str, set[str]]:
    """Caminhos citados por algum arquivo, resolvidos na raiz e no diretório de quem cita.

    A citação pode vir como caminho a partir da raiz (`scripts/x.py`), como caminho a partir do
    diretório do arquivo que cita (`scripts/x.py` dentro de uma skill) ou como nome solto. As três
    formas contam, porque todas são invocação declarada para quem lê a instrução.
    """
    named: dict[str, set[str]] = defaultdict(set)
    resolved_root = root.resolve()
    exclude_dirs = set(scope_of(policy).get("exclude_dirs") or [])
    excluded_paths = set(declared_exclusions(policy))
    walked, _ = walk_scope(root, root, exclude_dirs)
    known = {
        relative(path, root)
        for path in walked
        if path.is_file()
        and path.resolve().is_relative_to(resolved_root)
        and not in_excluded_dir(relative(path, root), exclude_dirs)
        and relative(path, root) not in excluded_paths
    }
    by_name: dict[str, list[str]] = defaultdict(list)
    for rel in sorted(known):
        by_name[Path(rel).name].append(rel)
    for rel, text in texts.items():
        directory = Path(rel).parent.as_posix()
        skill_root = Path(rel).parts[0] if len(Path(rel).parts) > 1 else ""
        for cited, start in citation_paths(text, suffixes):
            cleaned = cited.removeprefix("./")
            if cleaned.startswith("/"):
                # A barra inicial só é âncora quando o caminho vem logo depois de um marcador de lugar,
                # como em `<skill>/scripts/x.py`: fora disso é caminho absoluto, que não é citação de
                # arquivo da árvore e não pode manter módulo vivo.
                if not PLACEHOLDER_ANCHOR_RE.search(text[:start]):
                    continue
                cleaned = cleaned.lstrip("/")
            if not cleaned:
                continue
            parts = Path(cleaned).parts
            resolved = ""
            if ".." in parts:
                # Citação com `..` só é recusada quando de fato sai da raiz: `sub/../x.py` cita `x.py`
                # dentro da árvore, e descartar por conter `..` acusaria dívida que não existe.
                base = (root / directory) if directory != "." else root
                try:
                    inside = (base / cleaned).resolve()
                except (OSError, RuntimeError):
                    continue
                if not inside.is_relative_to(root.resolve()):
                    continue
                resolved = inside.relative_to(root.resolve()).as_posix()
            candidates = {resolved or cleaned}
            if not resolved and directory != ".":
                candidates.add(f"{directory}/{cleaned}")
            if not resolved and skill_root:
                candidates.add(f"{skill_root}/{cleaned}")
            matched = {candidate for candidate in candidates if candidate in known}
            if not matched and len(parts) == 1:
                # Nome solto alcança o arquivo de mesmo nome só quando ele é único na árvore: havendo
                # homônimos, o nome solto é ambíguo e não identifica invocação de nenhum deles.
                homonyms = by_name.get(cleaned, [])
                if len(homonyms) == 1:
                    matched = {homonyms[0]}
            for item in matched:
                named[item].add(rel)
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


def requirement_name(line: str) -> str:
    """Nome da distribuição declarada, pelo parser canônico quando ele está disponível.

    Requisito com URL direta, como `requests @ https://example.invalid/requests.whl`, tem o nome antes do
    `@`: cortar só em operador de versão trataria a linha inteira como nome e acusaria dependência que é
    importada.
    """
    try:
        from packaging.requirements import InvalidRequirement, Requirement
    except ImportError:  # pragma: no cover - ausencia da biblioteca cai no corte textual
        return re.split(r"[<>=!~\[;@]", line, maxsplit=1)[0].strip()
    try:
        return Requirement(line).name
    except InvalidRequirement:
        # Requisito de VCS, como `git+https://example.invalid/repo.git#egg=requests`, não é PEP 508 e declara o nome
        # no fragmento: sem o fragmento o corte textual devolveria a URL truncada e a dependência
        # importada viraria achado falso.
        fragment = re.search(r"[#&]egg=([A-Za-z0-9._-]+)", line)
        if fragment:
            return fragment.group(1)
        return re.split(r"[<>=!~\[;@]", line, maxsplit=1)[0].strip()


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
                if depth > len(package) or (node.level == 1 and not package and not root_is_package):
                    # `from . import x` na raiz só alcança irmão quando a própria raiz é pacote
                    # declarado; sem `__init__.py` na raiz o relativo não alcança módulo nenhum.
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
    declared_entries = {
        entry["name"]
        for entry in config.get("entry_points", [])
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
    named = named_paths(texts, root, citation_suffixes(policy), policy)
    imported = imported_modules(modules)
    findings: list[dict] = []
    for rel in sorted(modules):
        path = Path(rel)
        if package_init_is_entry and path.name == "__init__.py":
            continue
        if exclude_tests and (path.name.startswith("test_") or "tests" in path.parts):
            continue
        # Autocitação não é invocação: o arquivo que cita a si próprio continua sem importador e sem
        # invocação declarada por outro arquivo, que é a definição da classe.
        if rel in declared_entries or named.get(rel, set()) - {rel}:
            continue
        dotted = rel[:-3].replace("/", ".")
        # `import pkg` e `import pkg.sub` alcançam `pkg/__init__.py`: importar subpacote executa o módulo
        # de inicialização do pacote, e comparar só `pkg.__init__` acusaria módulo morto em pacote normal.
        package = dotted[:-9] if dotted.endswith(".__init__") else None
        if dotted in imported or (
            package is not None
            and any(name == package or name.startswith(f"{package}.") for name in imported)
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


def assigned_names(node: ast.stmt) -> list[str]:
    """Nomes simples atribuídos no nível do módulo; desempacotamento e alvo não textual ficam fora."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [target.id for target in targets if isinstance(target, ast.Name) and target.id.isidentifier()]


def detect_dead_symbols(
    root: Path, policy: dict, modules: dict[str, ast.Module], texts: dict[str, str]
) -> list[dict]:
    config = policy["classes"]["dead-symbol"]
    exclude_tests = bool(config.get("exclude_tests", True))
    ignore = {
        entry["name"]
        for entry in config.get("ignore_names", [])
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }
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


def in_targets(rel: str, targets: set[str] | None) -> bool:
    """Alvo do modo direcionado cobre o caminho e a subárvore; `None` significa sem restrição.

    Conjunto vazio não é ausência de restrição: quando todo alvo escapa da raiz, o escopo é vazio, e
    tratar isso como percurso livre analisaria manifest que o alvo direcionado exclui.
    """
    if targets is None:
        return True
    return any(rel == target or rel.startswith(target + "/") for target in targets)


def scoped_manifests(
    root: Path, policy: dict, paths: list[str] | None
) -> tuple[list[Path], list[dict]]:
    """Manifests no escopo declarado, e o que ficou fora por resolver para fora da raiz.

    Os padrões de nome vêm da política: conjunto fixo no código seria escopo escondido, e manifest que a
    política não declara medido é o mesmo problema na direção oposta. Manifest é lido do disco: link que
    resolve para fora da árvore entraria como declaração de fora e faria o resultado depender de arquivo
    que a varredura não mede.
    """
    exclude_dirs = set(scope_of(policy).get("exclude_dirs") or [])
    excluded_paths = set(declared_exclusions(policy))
    targets = normalized_targets(root.resolve(), paths)
    resolved_root = root.resolve()
    patterns = [str(item) for item in policy["classes"]["unused-dependency"]["manifest_patterns"]]
    manifests: list[Path] = []
    refused: list[dict] = []
    walked, walk_refusals = walk_scope(root, root, exclude_dirs)
    refused.extend(walk_refusals)
    for path in sorted(walked, key=lambda item: item.as_posix()):
        if not any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns):
            continue
        if is_lockfile(path.name):
            # Arquivo de trava é gerado do próprio manifest: ler os dois contaria a mesma dependência duas
            # vezes e acusaria achado de arquivo que a política não trata como declaração de dependência.
            continue
        rel = relative(path, root)
        if in_excluded_dir(rel, exclude_dirs) or rel in excluded_paths or not in_targets(rel, targets):
            continue
        if path.is_symlink() and not path.is_file():
            refused.append({"path": rel, "reason": "manifest que e link quebrado"})
            continue
        if not path.resolve().is_relative_to(resolved_root):
            refused.append({"path": rel, "reason": "manifest que resolve para fora da raiz"})
            continue
        if not path.is_file():
            refused.append({"path": rel, "reason": "manifest que nao e arquivo regular"})
            continue
        manifests.append(path)
    return manifests, refused


def is_lockfile(name: str) -> bool:
    """Nome de arquivo de trava, por convenção: `.lock` no fim ou `.lock.` no meio do nome.

    A trava é gerada do manifest, e não declaração de dependência: lê-la como manifest primário contaria
    a mesma dependência duas vezes e faria a classe acusar arquivo gerado.
    """
    return name.endswith(".lock") or ".lock." in name


def manifest_requirements(path: Path, text: str) -> list[str]:
    """Requisitos declarados em um manifest, pelo formato do arquivo.

    Formato sem leitura declarada é recusado, e não lido como texto de requisito: interpretar arquivo de
    outro formato como lista de linhas produziria achado inventado.
    """
    if path.suffix == ".toml":
        return toml_requirements(text)
    if path.suffix == ".txt":
        return [
            cleaned
            for cleaned in (
                COMMENT_START_RE.split(raw, maxsplit=1)[0].strip() for raw in text.splitlines()
            )
            if cleaned and not cleaned.startswith(("-", "#"))
        ]
    # Formato sem leitura declarada é recusa visível: interpretar INI, JSON ou YAML como lista de linhas
    # inventaria dependência que o manifest não declara.
    raise HygieneError(f"manifest de formato sem leitura declarada: {path.name}")


def requirement_list(value: object, label: str) -> list[str]:
    """Lista de requisitos do PEP 621, exigindo lista de texto.

    Estrutura fora disso é manifest inválido: iterar string escalar produziria uma dependência por
    caractere, que é achado inventado da classe.
    """
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise HygieneError(f"manifest toml invalido: {label} precisa ser lista de texto")
    return list(value)


def toml_document_tables(document: dict) -> tuple[dict, dict]:
    """Tabelas do documento TOML, com estrutura inválida recusada em vez de tratada como ausência.

    Tabela inválida não é ausência: tratar `project` ou `tool` escalar como vazio faria a declaração de
    dependência desaparecer da medição, que é a forma mais barata de esconder dependência não usada.
    """
    for key in ("project", "tool"):
        if key in document and not isinstance(document[key], dict):
            raise HygieneError(f"manifest toml invalido: {key} precisa ser tabela")
    tool = document.get("tool") or {}
    if "poetry" in tool and not isinstance(tool["poetry"], dict):
        raise HygieneError("manifest toml invalido: tool.poetry precisa ser tabela")
    return document.get("project") or {}, tool.get("poetry") or {}


def poetry_dependency_tables(poetry: dict) -> list:
    """Tabelas de dependência do Poetry, com hierarquia inválida recusada.

    Chave não lida dentro do grupo esconderia dependência: `[tool.poetry.group.dev.metadata]` com
    requisitos dentro é declaração válida para o formato e invisível para a medição.
    """
    tables = [poetry.get("dependencies"), poetry.get("dev-dependencies")]
    groups = poetry.get("group")
    if groups is not None and not isinstance(groups, dict):
        raise HygieneError("manifest toml invalido: tool.poetry.group precisa ser tabela")
    for name, group in (groups or {}).items():
        if not isinstance(group, dict):
            raise HygieneError(f"manifest toml invalido: tool.poetry.group.{name} precisa ser tabela")
        unknown = sorted(set(group) - {"dependencies", "optional"})
        if unknown:
            raise HygieneError(
                f"manifest toml invalido: tool.poetry.group.{name} tem chave nao lida ({unknown[0]})"
            )
        if "optional" in group and not isinstance(group["optional"], bool):
            raise HygieneError(
                f"manifest toml invalido: tool.poetry.group.{name}.optional precisa ser booleano"
            )
        table = group.get("dependencies")
        if table is not None and not isinstance(table, dict):
            raise HygieneError(
                f"manifest toml invalido: tool.poetry.group.{name}.dependencies precisa ser tabela"
            )
        tables.append(table)
    return tables


def toml_requirements(text: str) -> list[str]:
    """Requisitos de `pyproject.toml`: padrão do empacotador e tabelas do Poetry.

    `python` fica de fora porque é a versão exigida do interpretador, e não distribuição importável.
    """
    try:
        import tomllib
    except ImportError as error:  # pragma: no cover - versao sem tomllib
        raise HygieneError("manifest toml sem leitura suportada nesta versao") from error
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise HygieneError(f"manifest toml invalido ({error.__class__.__name__})") from error
    project, poetry = toml_document_tables(document)
    declared = list(requirement_list(project.get("dependencies"), "project.dependencies"))
    optional = project.get("optional-dependencies")
    if optional is not None and not isinstance(optional, dict):
        raise HygieneError("manifest toml invalido: project.optional-dependencies precisa ser tabela")
    for group, value in (optional or {}).items():
        declared.extend(requirement_list(value, f"project.optional-dependencies.{group}"))
    # `python` vale para as duas formas: é a versão exigida do interpretador, e não distribuição.
    requirements = [
        line for line in declared if requirement_name(line).lower() != "python"
    ]
    for table in poetry_dependency_tables(poetry):
        if table is not None and not isinstance(table, dict):
            raise HygieneError("manifest toml invalido: tabela de dependencia do Poetry precisa ser tabela")
        if isinstance(table, dict):
            requirements.extend(str(key) for key in table if str(key).lower() != "python")
    return requirements


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
            lines = manifest_requirements(manifest, read_text(manifest, manifest_rel))
        except HygieneError as error:
            # Manifest é entrada da classe: falha de leitura não pode sair do relatório só porque o
            # sufixo dele não está no corpus de citação.
            refused.append({"path": manifest_rel, "reason": str(error)})
            continue
        for line in lines:
            name = requirement_name(line)
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


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "hygiene-report.schema.json"


def report_contract_errors(report: dict) -> list[str]:
    """Relatório conferido contra o contrato, do mesmo modo que o validador faz.

    O produtor precisa conferir antes de gravar: comando documentado como origem do relatório que sai com
    sucesso e grava artefato fora do contrato publica evidência que ninguém pode aceitar.
    """
    if not SCHEMA_PATH.is_file():
        return ["contrato: schema do relatorio ausente"]
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"contrato: schema do relatorio ilegivel ({error.__class__.__name__})"]
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return [
            "contrato: biblioteca de schema ausente; o relatorio nao pode ser aprovado sem ser conferido"
        ]
    validator = Draft202012Validator(schema)
    return [
        f"contrato: {list(error.path)}: {error.message}"
        for error in sorted(validator.iter_errors(report), key=lambda item: list(item.path))
    ]


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
            if not accepted[identity].strip():
                # Exceção sem motivo escrito não é decisão declarada: aceitar aqui produziria achado aceito
                # sem justificativa, que é o que o contrato do relatório proíbe.
                raise HygieneError(f"politica: accepted sem motivo escrito para {identity}")
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
    excluded_dirs = sorted(
        str(item) for item in (scope_of(policy).get("exclude_dirs") or []) if isinstance(item, str)
    )
    report = {
        "schema_version": 1,
        "system": "hygiene-report",
        "policy_system": policy.get("system"),
        "policy_schema_version": policy.get("schema_version"),
        "mode": "targeted" if paths else "sweep",
        "analyzed": len(modules),
        "excluded": excluded,
        "excluded_dirs": excluded_dirs,
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
    if report["excluded"] or report.get("excluded_dirs"):
        # Exclusão fora do artefato humano induziria leitura de cobertura completa sobre escopo
        # reduzido por declaração.
        lines.extend(["", "## Excluídos por declaração", ""])
        lines.extend(f"- `{entry['path']}` — {entry['reason']}" for entry in report["excluded"])
        lines.extend(
            f"- `{name}/` — diretório excluído por declaração"
            for name in report.get("excluded_dirs", [])
        )
    if report["not_analyzed"]:
        lines.extend(["", "## Não analisados", ""])
        lines.extend(
            f"- `{entry['path']}` — {entry['reason']}" for entry in report["not_analyzed"]
        )
    return "\n".join(lines) + "\n"


def write_target(path: Path, root: Path, label: str) -> Path:
    """Destino de escrita do relatório, recusado dentro da árvore medida.

    Relatório é evidência sobre a árvore: gravado dentro dela entra no corpus de citação, altera a medição
    seguinte e pode sobrescrever arquivo coberto. Evidência que muda o objeto medido não é evidência.
    """
    target = path.resolve()
    if target.is_relative_to(root):
        raise HygieneError(f"{label} dentro da arvore medida: use caminho fora de {root.name}")
    if target.exists() and not target.is_dir():
        # Alvo com mais de um link pode ser o mesmo arquivo de dentro da árvore: a checagem de caminho é
        # lexical, e a escrita por link alteraria a árvore medida sem sair dela. Diretório tem mais de um
        # link por construção, e o diretório de destino é conferido por quem escreve.
        if target.stat().st_nlink > 1:
            raise HygieneError(f"{label} aponta para arquivo com mais de um link: use arquivo novo")
        if not target.is_file():
            raise HygieneError(f"{label} precisa ser arquivo regular")
    return target


def policy_contract_errors(policy: dict) -> list[str]:
    """Forma da política conferida pelo mesmo validador do gate, sem duplicar a regra aqui.

    A importação é tardia porque o gate importa este módulo, e importá-lo no topo fecharia o ciclo.
    """
    try:
        from validate_hygiene import policy_errors
    except ImportError:  # pragma: no cover - gate ausente no caminho de importacao
        return ["politica: validador de politica indisponivel"]
    return list(policy_errors(policy))


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
        if (
            args.report is not None
            and args.markdown is not None
            and args.report.resolve() == args.markdown.resolve()
        ):
            # Um artefato sobrescrevendo o outro deixaria o JSON perdido e o Markdown publicado como se
            # fosse o relatório.
            raise HygieneError("--report e --markdown precisam ser caminhos diferentes")
        targets = {
            label: write_target(path, root, label)
            for label, path in (("--report", args.report), ("--markdown", args.markdown))
            if path is not None
        }
        policy = load_policy(root, args.policy)
        # A varredura só produz relatório de política íntegra: medir com política incompleta seria medir
        # outra coisa e publicar evidência que o gate recusa.
        contract = policy_contract_errors(policy)
        if contract:
            print("Politica invalida:", file=sys.stderr)
            for problem in sorted(set(contract)):
                print(f"- {problem}", file=sys.stderr)
            return 1
        report, problems = build_report(root, policy, args.paths)
    except HygieneError as error:
        print(f"ERRO: {error}", file=sys.stderr)
        return 2
    contract = report_contract_errors(report)
    if contract:
        print("Relatorio fora do contrato:", file=sys.stderr)
        for problem in contract:
            print(f"- {problem}", file=sys.stderr)
        return 1
    if problems:
        # Relatório de política com problema não é publicado: artefato gravado antes da reprovação
        # circularia como evidência de uma medição que a política não sustenta.
        print("Problemas na politica:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.report:
        targets["--report"].write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    if args.markdown:
        targets["--markdown"].write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
