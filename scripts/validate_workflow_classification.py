"""Classificação dos passos do workflow de validação e paridade com a sequência documentada.

`README.md` e `AGENTS.md` afirmam que sua sequência de validação é idêntica à do workflow do CI, e
a afirmação já divergiu porque nada conferia. Este validador lê os passos com um parser de YAML, e
não com expressões regulares sobre o texto: chave entre aspas, espaço antes dos dois-pontos,
mapeamento em fluxo, bloco vazio e chave repetida são formas válidas de escrever o mesmo passo
ativo, e uma leitura textual deixaria passar um passo que entra no CI sem entrar na comparação.

A classificação de comando tem duas partes, e nenhuma delas é procura textual:

1. a linha inteira precisa casar com a gramática declarada — `python` seguido de um alvo e de
   argumentos sem metacaractere de shell, com no máximo um redirecionamento simples de saída, com
   ou sem `2>&1`. Composição (`&&`, `||`, `;`, `|`, `&`), substituição (`$()`, crase), aspas,
   escape, descritor de arquivo, redirecionamento extra e invólucros (`eval`, `env`, `sudo`,
   `time`, `nohup`, `xargs`, `sh -c`, `python -c`) não casam;
2. o alvo precisa estar declarado: um script de validação do repositório que existe como arquivo
   regular, ou um dos módulos declarados (`pip`, `pytest`). Assim, um marcador escrito em um
   argumento não transforma um script arbitrário em validação, e um nome parecido sem arquivo não
   passa.

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
import sys
from pathlib import Path

import yaml

WORKFLOW = Path(".github") / "workflows" / "validate.yml"
DOCUMENTED = (Path("README.md"), Path("AGENTS.md"))
SHELL_FENCES = {"```bash", "```sh", "```shell"}
# Scripts de validação declarados pelo nome. `scripts/validate_*.py` também vale, mas sempre com o
# arquivo existindo sob a raiz, porque o nome sozinho seria só um marcador.
VALIDATION_SCRIPTS = (
    "scripts/sync_contracts.py",
    "scripts/build_catalog_docs.py",
    "scripts/lock_dependencies.py",
    "evals/run_evals.py",
    "entregar-issue/scripts/validate_skill_genericity.py",
)
VALIDATION_SCRIPT_RE = re.compile(r"scripts/validate_[a-z0-9_]+\.py")
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
# Argumento aceito: sem metacaractere de shell, então nada de `&&`, `;`, `|`, crase, `$`, parêntese,
# colchete, chave, aspas, escape ou curinga. O que passa aqui é dado do comando, não composição.
SAFE_ARG = r"[A-Za-z0-9_@%+=:,./-]+"
GRAMMAR_RE = re.compile(
    r"python3? (?:-m (?P<module>[a-z][a-z0-9_]*)|(?P<script>[A-Za-z0-9_][A-Za-z0-9_./-]*\.py))"
    rf"(?: {SAFE_ARG})*(?: > {SAFE_ARG})?(?: 2>&1)?"
)


def normalize(command: str) -> str:
    command = " ".join(command.split())
    command = re.sub(r"\s+#.*$", "", command)
    command = re.split(r"\s+>\s*", command)[0]
    return re.sub(r"\s+2>&1\s*$", "", command).strip()


def strip_comment(line: str) -> str:
    return re.sub(r"\s+#.*$", "", line).strip()


def target_of(command: str) -> tuple[str, str] | None:
    """Alvo declarado do comando: `("script", caminho)` ou `("module", nome)`; `None` fora da gramática."""
    match = GRAMMAR_RE.fullmatch(strip_comment(command))
    if match is None:
        return None
    if match.group("module") is not None:
        return "module", match.group("module")
    return "script", match.group("script")


def is_declared_script(target: str, root: Path | None) -> bool:
    """Script de validação declarado, existindo como arquivo regular sob a raiz."""
    if ".." in target or target.startswith("/"):
        return False
    if target not in VALIDATION_SCRIPTS and not VALIDATION_SCRIPT_RE.fullmatch(target):
        return False
    if root is None:
        return True
    candidate = root / target
    return candidate.is_file() and root.resolve() in candidate.resolve().parents


def is_validation(command: str, root: Path | None = None) -> bool:
    """Validação é o comando cujo alvo está declarado; marca textual em argumento não conta."""
    if "--write" in command:
        return False
    target = target_of(command)
    if target is None:
        return False
    kind, name = target
    if kind == "module":
        return name in ALLOWED_MODULES
    return is_declared_script(name, root)


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


def read_text(path: Path) -> tuple[str, list[str]]:
    """Conteúdo do arquivo e o problema de leitura, quando houver; nada aqui levanta exceção."""
    try:
        return path.read_text(encoding="utf-8"), []
    except FileNotFoundError:
        return "", [f"arquivo ausente: {path.name}"]
    except UnicodeDecodeError:
        return "", [f"arquivo nao esta em UTF-8: {path.name}"]
    except OSError as error:
        return "", [f"arquivo ilegivel: {path.name} ({error.strerror or error.__class__.__name__})"]


def load_workflow(path: Path) -> tuple[object, list[str]]:
    """Documento do workflow e problemas de forma; não levanta exceção."""
    text, problems = read_text(path)
    if problems:
        return None, [f"workflow: {problem}" for problem in problems]
    try:
        documents = list(yaml.load_all(text, Loader=StrictLoader))
    except yaml.YAMLError as error:
        return None, [f"workflow: YAML invalido ({type(error).__name__})"]
    if len(documents) != 1:
        return None, [
            f"workflow: precisa de um unico documento YAML, encontrado {len(documents)}"
        ]
    return documents[0], []


def root_of(path: Path) -> Path:
    """Raiz do repositório a que um arquivo pertence, pelo próprio caminho."""
    resolved = path.resolve()
    if resolved.parent.name == "workflows" and resolved.parent.parent.name == ".github":
        return resolved.parents[2]
    return resolved.parent


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


def workflow_commands(path: Path, root: Path | None = None) -> list[str]:
    root = root if root is not None else root_of(path)
    return [
        command for command in workflow_run_commands(path) if is_validation(command, root)
    ]


def command_problems(line: str) -> list[str]:
    """Gramática de uma linha de `run`: invocação simples com alvo declarado."""
    command = strip_comment(line)
    if not command:
        # Comentário puro não executa nada, então não há o que classificar.
        return []
    target = target_of(command)
    if target is None:
        return [f"comando fora da gramatica declarada: {command!r}"]
    kind, name = target
    if kind == "module" and name not in ALLOWED_MODULES:
        return [f"modulo nao declarado: {name!r}"]
    return []


def step_problems(job_name: str, index: int, step: object, root: Path) -> list[str]:
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
        if not is_validation(command, root) and command not in NON_VALIDATION_STEPS:
            problems.append(f"{name}: comando sem classificação de validação ({command})")
    return problems


def classification_problems(path: Path, root: Path | None = None) -> list[str]:
    """Forma do documento e classificação de cada passo; nada aqui levanta exceção."""
    root = root if root is not None else root_of(path)
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
            problems.extend(step_problems(str(job_name), index, step, root))
    return problems


def markdown_commands(path: Path, root: Path | None = None) -> list[str]:
    """Comandos de validação que um documento declara em bloco de shell."""
    root = root if root is not None else root_of(path)
    text, problems = read_text(path)
    if problems:
        return []
    commands: list[str] = []
    inside = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            inside = (not inside) and stripped in SHELL_FENCES
            continue
        if inside and stripped.startswith("python "):
            normalized = normalize(stripped)
            if is_validation(normalized, root):
                commands.append(normalized)
    return commands


def validate_workflow_classification(root: Path) -> list[str]:
    """Classificação do workflow e paridade da sequência entre CI, README e AGENTS."""
    workflow = root / WORKFLOW
    if not workflow.is_file():
        return [f"workflow ausente: {WORKFLOW}"]
    problems = classification_problems(workflow, root)
    ci = workflow_commands(workflow, root)
    if not ci:
        problems.append("workflow: nenhum comando de validacao declarado")
    for document in DOCUMENTED:
        path = root / document
        _text, read_problems = read_text(path)
        if read_problems:
            problems.extend(f"{document}: {problem}" for problem in read_problems)
            continue
        documented = markdown_commands(path, root)
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
    commands = len(workflow_commands(root / WORKFLOW, root))
    print(
        f"Classificacao OK: {steps} passo(s) classificados, {commands} comando(s) de validacao "
        f"em paridade com a sequencia documentada."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
