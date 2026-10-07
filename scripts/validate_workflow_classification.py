"""Classificação dos passos do workflow de validação e paridade com a sequência documentada.

`README.md` e `AGENTS.md` afirmam que sua sequência de validação é idêntica à do workflow do CI, e
a afirmação já divergiu porque nada conferia. Este validador lê os passos com um parser de YAML, e
não com expressões regulares sobre o texto: chave entre aspas, espaço antes dos dois-pontos,
mapeamento em fluxo, bloco vazio e chave repetida são formas válidas de escrever o mesmo passo
ativo, e uma leitura textual deixaria passar um passo que entra no CI sem entrar na comparação.

A classificação de comando é gramatical, e não textual. Cada linha precisa ser uma invocação
simples de um script do repositório ou de um módulo declarado, porque encadear outro comando
dentro de um comando aprovado esconderia o que executa, e nenhuma marca textual distingue
`python validador.py` de `python validador.py && outra coisa`.

O limite da comparação é deliberado: entra o que prova o estado do repositório, e o empacotamento
do skill (`package_chatgpt_skill.py`), que produz o artefato de release, fica de fora por não ser
validação. A conferência do fechamento dos lockfiles (`lock_dependencies.py --check`) entra, porque
é o passo que prova que o lockfile é o fechamento do manifest.

A checagem cobre o workflow de validação; os outros workflows do repositório são escopo de outro
item do roadmap, que trata da pinagem completa das ações que eles usam.
"""
from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

import yaml

WORKFLOW = Path(".github") / "workflows" / "validate.yml"
DOCUMENTED = (Path("README.md"), Path("AGENTS.md"))
SHELL_FENCES = {"```bash", "```sh", "```shell"}
VALIDATION_MARKERS = (
    "scripts/validate_",
    "scripts/sync_contracts.py",
    "scripts/build_catalog_docs.py",
    "scripts/lock_dependencies.py",
    "evals/run_evals.py",
    "-m pytest",
    "-m pip install",
)
# Ações de infraestrutura que não provam estado do repositório: preparar o ambiente e publicar o
# artefato de release. Qualquer uso novo precisa ser classificado aqui de propósito.
ALLOWED_USES = (
    "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
)
NON_VALIDATION_STEPS = (
    # Produz o artefato de release; não prova estado do repositório, então não entra na comparação.
    "python scripts/package_chatgpt_skill.py entregar-issue --output dist/skill.zip",
)
# Módulos que a sequência executa com `python -m`. Qualquer outro módulo é passo não classificado.
ALLOWED_MODULES = ("pip", "pytest")
PYTHON = ("python", "python3")
SCRIPT_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]*\.py")
# Argumento aceito: sem metacaractere de shell, então nada de `&&`, `;`, `|`, crase, `$`, parêntese,
# colchete, chave, aspas ou curinga. O que passa aqui é dado do comando, não composição.
SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9_@%+=:,./-]+")
REDIRECT_TAIL = ("2", ">&", "1")
SHELL_OPERATORS = ("&&", "||", ";", "|", "&", ">", "<", "(", ")", ">&", "<<<", ">>")


def normalize(command: str) -> str:
    command = " ".join(command.split())
    command = re.sub(r"\s+#.*$", "", command)
    command = re.split(r"\s+>\s*", command)[0]
    return re.sub(r"\s+2>&1\s*$", "", command).strip()


def is_validation(command: str) -> bool:
    if "--write" in command:
        return False
    return command.startswith("python ") and any(marker in command for marker in VALIDATION_MARKERS)


class StrictLoader(yaml.SafeLoader):
    """Carregador que constrói cada chave e recusa duplicata, inclusive com grafia diferente.

    O carregador padrão sobrescreve a chave repetida em silêncio, e comparar o texto da chave
    deixaria passar `true` e `True`, `yes` e `true`, `01` e `1`, `null` e `~`, que são o mesmo
    valor depois de construídos. Chave que não pode ser comparada, como uma sequência, também
    reprova em vez de estourar exceção.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        self.flatten_mapping(node)
        mapping: dict = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicated = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    None, None, f"chave nao comparavel: {key!r}", key_node.start_mark
                ) from error
            if duplicated:
                raise yaml.constructor.ConstructorError(
                    None, None, f"chave duplicada no mapeamento: {key!r}", key_node.start_mark
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def load_workflow(path: Path) -> tuple[object, list[str]]:
    """Documento do workflow e problemas de forma; não levanta exceção."""
    text = path.read_text(encoding="utf-8")
    try:
        documents = list(yaml.load_all(text, Loader=StrictLoader))
    except yaml.YAMLError as error:
        return None, [f"workflow: YAML invalido ({type(error).__name__})"]
    if len(documents) != 1:
        return None, [
            f"workflow: precisa de um unico documento YAML, encontrado {len(documents)}"
        ]
    return documents[0], []


def workflow_steps(path: Path) -> list[dict]:
    """Passos reais dos jobs, materializados pelo parser de YAML."""
    document, _ = load_workflow(path)
    if not isinstance(document, dict):
        return []
    jobs = document.get("jobs")
    if not isinstance(jobs, dict):
        return []
    steps: list[dict] = []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        declared = job.get("steps")
        if not isinstance(declared, list):
            continue
        steps.extend(step for step in declared if isinstance(step, dict))
    return steps


def workflow_run_commands(path: Path) -> list[str]:
    """Comandos executados pelos passos, um por linha de bloco, já normalizados."""
    commands: list[str] = []
    for step in workflow_steps(path):
        text = step.get("run")
        if not isinstance(text, str):
            continue
        commands.extend(
            command for command in (normalize(line) for line in text.splitlines()) if command
        )
    return commands


def workflow_commands(path: Path) -> list[str]:
    return [command for command in workflow_run_commands(path) if is_validation(command)]


def tokenize(line: str) -> list[str] | None:
    """Tokens da linha, com os operadores de shell separados; `None` quando as aspas não fecham."""
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def split_redirects(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Corpo do comando e o rabo de redirecionamento declarado, separados."""
    body = list(tokens)
    tail: list[str] = []
    if body[-len(REDIRECT_TAIL) :] == list(REDIRECT_TAIL):
        tail = list(REDIRECT_TAIL)
        body = body[: -len(REDIRECT_TAIL)]
    if len(body) >= 2 and body[-2] == ">":
        tail = body[-2:] + tail
        body = body[:-2]
    return body, tail


def command_problems(line: str) -> list[str]:
    """Gramática de uma linha de `run`: invocação simples de script declarado ou módulo permitido."""
    command = re.sub(r"\s+#.*$", "", line).strip()
    if not command or command.startswith("#"):
        # Comentário puro não executa nada, então não há o que classificar.
        return []
    tokens = tokenize(command)
    if tokens is None:
        return [f"comando com aspas nao balanceadas: {command!r}"]
    if not tokens or tokens[0] not in PYTHON:
        return [f"comando fora da forma aceita: {command!r}"]
    if len(tokens) < 2:
        return [f"comando python sem alvo: {command!r}"]
    if tokens[1] == "-m":
        if len(tokens) < 3 or tokens[2] not in ALLOWED_MODULES:
            module = tokens[2] if len(tokens) > 2 else ""
            return [f"modulo nao declarado: {module!r}"]
        body = tokens[3:]
    elif SCRIPT_RE.fullmatch(tokens[1]) and ".." not in tokens[1]:
        body = tokens[2:]
    else:
        return [f"alvo nao e script declarado nem modulo permitido: {tokens[1]!r}"]
    body, tail = split_redirects(body)
    problems: list[str] = []
    for token in body:
        if SAFE_TOKEN_RE.fullmatch(token):
            continue
        if token in SHELL_OPERATORS:
            problems.append(f"comando com operador de shell: {token!r}")
        else:
            problems.append(f"argumento com metacaractere de shell: {token!r}")
    if tail:
        extra = tail[2:]
        target = tail[1] if len(tail) >= 2 and tail[0] == ">" else None
        if target is not None and extra in ([], list(REDIRECT_TAIL)):
            # O destino do redirecionamento também é texto de comando: `> /tmp/a`/tmp/evil`` executaria
            # o que estiver entre crases, e o rabo não pode ser a porta de entrada do que o corpo recusa.
            if not SAFE_TOKEN_RE.fullmatch(target):
                problems.append(f"destino de redirecionamento com metacaractere: {target!r}")
        elif tail != list(REDIRECT_TAIL):
            problems.append(f"rabo de redirecionamento nao declarado: {' '.join(tail)!r}")
    return problems


def step_problems(job_name: str, index: int, step: object) -> list[str]:
    """Classificação de um passo: comando de validação declarado ou ação permitida."""
    where = f"{job_name} passo {index}"
    if not isinstance(step, dict):
        return [f"{where}: passo precisa ser objeto"]
    name = str(step.get("name") or where)
    has_run = "run" in step
    has_uses = "uses" in step
    if has_run and has_uses:
        return [f"{name}: passo com run e uses ao mesmo tempo"]
    if has_uses:
        used = step.get("uses")
        if not isinstance(used, str):
            return [f"{name}: uses precisa ser texto"]
        if used not in ALLOWED_USES:
            return [f"{name}: ação sem classificação declarada ({used})"]
        return []
    if not has_run:
        return [f"{name}: passo sem run e sem uses"]
    text = step.get("run")
    if not isinstance(text, str) or not text.strip():
        return [f"{name}: passo de comando vazio"]
    problems: list[str] = []
    for line in text.splitlines():
        problems.extend(f"{name}: {problem}" for problem in command_problems(line))
        command = normalize(line)
        if not command:
            continue
        if not is_validation(command) and command not in NON_VALIDATION_STEPS:
            problems.append(f"{name}: comando sem classificação de validação ({command})")
    return problems


def classification_problems(path: Path) -> list[str]:
    """Forma do documento e classificação de cada passo; nada aqui levanta exceção."""
    document, problems = load_workflow(path)
    if not isinstance(document, dict):
        return [*problems, "workflow: documento precisa ser objeto"]
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        return [*problems, "workflow: jobs precisa ser objeto nao vazio"]
    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            problems.append(f"{job_name}: job precisa ser objeto")
            continue
        steps = job.get("steps")
        if not isinstance(steps, list) or not steps:
            problems.append(f"{job_name}: steps precisa ser lista nao vazia")
            continue
        for index, step in enumerate(steps, start=1):
            problems.extend(step_problems(str(job_name), index, step))
    return problems


def markdown_commands(path: Path) -> list[str]:
    """Comandos de validação que um documento declara em bloco de shell."""
    commands: list[str] = []
    inside = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            inside = (not inside) and stripped in SHELL_FENCES
            continue
        if inside and stripped.startswith("python "):
            normalized = normalize(stripped)
            if is_validation(normalized):
                commands.append(normalized)
    return commands


def validate_workflow_classification(root: Path) -> list[str]:
    """Classificação do workflow e paridade da sequência entre CI, README e AGENTS."""
    workflow = root / WORKFLOW
    if not workflow.is_file():
        return [f"workflow ausente: {WORKFLOW}"]
    problems = classification_problems(workflow)
    ci = workflow_commands(workflow)
    if not ci:
        problems.append("workflow: nenhum comando de validacao declarado")
    for document in DOCUMENTED:
        documented = markdown_commands(root / document)
        if documented != ci:
            problems.append(f"{document}: sequencia documentada diverge da executada pelo CI")
    if len(ci) != len(set(ci)):
        problems.append("workflow: sequencia de validacao com passo duplicado")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classifica os passos do workflow de validação")
    parser.add_argument("--root", default=".", help="raiz do repositório")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    problems = validate_workflow_classification(root)
    if problems:
        print("Classificacao de workflow falhou:")
        print("\n".join(f"- {problem}" for problem in sorted(set(problems))))
        return 1
    steps = len(workflow_steps(root / WORKFLOW))
    commands = len(workflow_commands(root / WORKFLOW))
    print(
        f"Classificacao OK: {steps} passo(s) classificados, {commands} comando(s) de validacao "
        f"em paridade com a sequencia documentada."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
