"""A sequência de validação documentada precisa ser a executada.

`README.md` e `AGENTS.md` afirmam que sua sequência de validação é idêntica à do workflow do CI.
A afirmação já divergiu duas vezes, porque nada conferia. Este teste lê os passos do workflow com
um parser de YAML, e não com expressões regulares sobre o texto: chave entre aspas, espaço antes
dos dois-pontos, mapeamento em fluxo e bloco vazio são formas válidas de escrever o mesmo passo
ativo, e uma leitura textual deixaria passar um passo que entra no CI sem entrar na comparação.

O limite da comparação é deliberado: entra o que prova o estado do repositório, e o empacotamento
do skill (`package_chatgpt_skill.py`), que produz o artefato de release, fica de fora por não ser
validação. A conferência do fechamento dos lockfiles (`lock_dependencies.py --check`) entra, porque
é o passo que prova que o lockfile é o fechamento do manifest. Um passo de validação novo que fique
fora da lista de marcadores não é comparado, então a lista precisa acompanhar a sequência.

A checagem cobre o workflow de validação; os outros workflows do repositório são escopo de outro
item do roadmap, que trata da pinagem completa das ações que eles usam.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"
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


def normalize(command: str) -> str:
    command = " ".join(command.split())
    command = re.sub(r"\s+#.*$", "", command)
    command = re.split(r"\s+>\s*", command)[0]
    return re.sub(r"\s+2>&1\s*$", "", command).strip()


def is_validation(command: str) -> bool:
    if "--write" in command:
        return False
    return command.startswith("python ") and any(marker in command for marker in VALIDATION_MARKERS)


def workflow_steps(path: Path) -> list[dict]:
    """Passos reais dos jobs, materializados pelo parser de YAML."""
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    jobs = document.get("jobs") or {}
    steps: list[dict] = []
    if not isinstance(jobs, dict):
        return steps
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        declared = job.get("steps") or []
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
        commands.extend(command for command in (normalize(line) for line in text.splitlines()) if command)
    return commands


def workflow_commands(path: Path) -> list[str]:
    return [command for command in workflow_run_commands(path) if is_validation(command)]


def classification_problems(path: Path) -> list[str]:
    """Passos do workflow que não estão classificados como validação nem declarados como não."""
    problems: list[str] = []
    for step in workflow_steps(path):
        name = str(step.get("name", "<sem nome>"))
        if "run" in step and "uses" in step:
            problems.append(f"{name}: passo com run e uses ao mesmo tempo")
            continue
        if "uses" in step:
            used = str(step.get("uses"))
            if used not in ALLOWED_USES:
                problems.append(f"{name}: ação sem classificação declarada ({used})")
            continue
        if "run" not in step:
            problems.append(f"{name}: passo sem run e sem uses")
            continue
        text = step.get("run")
        if not isinstance(text, str) or not text.strip():
            problems.append(f"{name}: passo de comando vazio")
            continue
        for line in text.splitlines():
            command = normalize(line)
            if not command:
                continue
            if not is_validation(command) and command not in NON_VALIDATION_STEPS:
                problems.append(f"{name}: comando sem classificação de validação ({command})")
    return problems


def markdown_commands(path: Path) -> list[str]:
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


def invoked_scripts(ci: list[str]) -> list[Path]:
    """Scripts do repositório que um comando do workflow executa."""
    found: list[Path] = []
    for command in ci:
        for part in command.split():
            candidate = ROOT / part
            if part.endswith(".py") and candidate.is_file():
                found.append(candidate)
    return found


def test_local_validation_sequence_matches_the_ci_workflow() -> None:
    ci = workflow_commands(WORKFLOW)
    assert ci, "o workflow não declara nenhum comando de validação"
    for document in ("README.md", "AGENTS.md"):
        documented = markdown_commands(ROOT / document)
        assert documented == ci, f"{document} diverge da sequência executada pelo CI"


def test_closure_check_is_part_of_the_compared_sequence() -> None:
    """A conferência do fechamento dos lockfiles é validação e não pode sair da comparação."""
    assert is_validation("python scripts/lock_dependencies.py --root . --check")


def test_packaging_is_not_part_of_the_validation_sequence() -> None:
    """O empacotamento do skill é release: fica fora da sequência comparada de propósito."""
    assert not is_validation(
        "python scripts/package_chatgpt_skill.py entregar-issue --output dist/skill.zip"
    )


def test_every_workflow_step_is_classified() -> None:
    """Todo passo do workflow, comando ou ação externa, precisa estar classificado."""
    assert classification_problems(WORKFLOW) == []


def test_yaml_forms_cannot_hide_an_unclassified_step(tmp_path: Path) -> None:
    """Formas YAML equivalentes não podem esconder um passo ativo do classificador."""
    template = """name: teste
on: [push]
jobs:
  validacao:
    runs-on: ubuntu-latest
    steps:
      - name: passo conhecido
        run: python scripts/validate_docs.py --root .
"""
    hidden = {
        "chave uses entre aspas": '      - name: escondido\n        "uses": actions/cache@1111111111111111111111111111111111111111\n',
        "chave uses com espaco antes dos dois-pontos": "      - name: escondido\n        uses : actions/cache@1111111111111111111111111111111111111111\n",
        "mapeamento em fluxo com uses": "      - {name: escondido, uses: actions/cache@1111111111111111111111111111111111111111}\n",
        "chave run entre aspas": '      - name: escondido\n        "run": echo escondido\n',
        "chave run com espaco antes dos dois-pontos": "      - name: escondido\n        run : echo escondido\n",
        "mapeamento em fluxo com run": "      - {name: escondido, run: echo escondido}\n",
        "bloco de run vazio": "      - name: escondido\n        run: |\n",
        "bloco dobrado vazio": "      - name: escondido\n        run: >\n",
    }
    for label, snippet in hidden.items():
        path = tmp_path / "workflow.yml"
        path.write_text(template + snippet, encoding="utf-8")
        problems = classification_problems(path)
        assert problems, f"{label} passou sem ser classificada"
    path = tmp_path / "limpo.yml"
    path.write_text(template, encoding="utf-8")
    assert classification_problems(path) == []


def test_validation_sequence_has_no_duplicated_step() -> None:
    ci = workflow_commands(WORKFLOW)
    assert len(ci) == len(set(ci)), "a sequência de validação contém passo duplicado"


def test_workflow_runs_every_standalone_validator() -> None:
    ci = workflow_commands(WORKFLOW)
    validators = sorted(path.name for path in (ROOT / "scripts").glob("validate_*.py"))
    assert validators
    invoked_sources = "".join(
        path.read_text(encoding="utf-8") for path in invoked_scripts(ci)
    )
    uncovered = [
        name
        for name in validators
        if not any(name in command for command in ci) and name[: -len(".py")] not in invoked_sources
    ]
    assert uncovered == [], (
        "validadores que nenhum passo do workflow executa, direta ou transitivamente: "
        + ", ".join(uncovered)
    )
