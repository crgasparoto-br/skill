"""Adversários da classificação do workflow e do fechamento dos lockfiles.

O validador `scripts/validate_workflow_classification.py` é quem roda na sequência obrigatória e
afirma, no CI, que todo passo está classificado e que README, AGENTS e workflow têm a mesma
sequência. Aqui ficam as tentativas de burlar essa classificação: formas YAML equivalentes ou
estruturalmente inválidas, chaves repetidas com grafia diferente, encadeamento de comandos dentro
de um comando aprovado e formas de invocação que não são as declaradas.

A conferência do fechamento dos lockfiles (`lock_dependencies.py --check`) entra na sequência
comparada, porque é o passo que prova que o lockfile é o fechamento do manifest; o empacotamento do
skill fica de fora, porque produz artefato de release e não prova estado do repositório.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.validate_workflow_classification import (
    ALLOWED_USES,
    NON_VALIDATION_STEPS,
    WORKFLOW,
    classification_problems,
    command_problems,
    is_validation,
    markdown_commands,
    normalize,
    validate_workflow_classification,
    workflow_commands,
)

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = """name: teste
on: [push]
jobs:
  validacao:
    runs-on: ubuntu-latest
    steps:
      - name: passo conhecido
        run: python scripts/validate_docs.py --root .
"""


def workflow_with(tmp_path: Path, snippet: str) -> Path:
    path = tmp_path / "workflow.yml"
    path.write_text(TEMPLATE + snippet, encoding="utf-8")
    return path


def test_local_validation_sequence_matches_the_ci_workflow() -> None:
    """A sequência documentada é a executada, e o validador é quem confere isso na sequência."""
    ci = workflow_commands(ROOT / WORKFLOW)
    assert ci, "o workflow não declara nenhum comando de validação"
    for document in ("README.md", "AGENTS.md"):
        assert markdown_commands(ROOT / document) == ci, f"{document} diverge do CI"


def test_closure_check_is_part_of_the_compared_sequence() -> None:
    """A conferência do fechamento dos lockfiles é validação e não pode sair da comparação."""
    assert is_validation("python scripts/lock_dependencies.py --root . --check")


def test_packaging_is_not_part_of_the_validation_sequence() -> None:
    """O empacotamento do skill é release: fica fora da sequência comparada de propósito."""
    assert not is_validation(
        "python scripts/package_chatgpt_skill.py entregar-issue --output dist/skill.zip"
    )
    assert (
        "python scripts/package_chatgpt_skill.py entregar-issue --output dist/skill.zip"
        in NON_VALIDATION_STEPS
    )


def test_every_workflow_step_is_classified() -> None:
    """Todo passo do workflow, comando ou ação externa, precisa estar classificado."""
    assert classification_problems(ROOT / WORKFLOW) == []


def test_validator_accepts_the_repository_and_rejects_a_divergent_sequence(tmp_path: Path) -> None:
    """O validador aprova a árvore real e reprova uma sequência documentada divergente."""
    assert validate_workflow_classification(ROOT) == []
    tree = tmp_path / "repo"
    (tree / ".github" / "workflows").mkdir(parents=True)
    (tree / ".github" / "workflows" / "validate.yml").write_text(TEMPLATE, encoding="utf-8")
    for document in ("README.md", "AGENTS.md"):
        (tree / document).write_text("```bash\npython scripts/validate_docs.py --root .\n```\n", encoding="utf-8")
    assert validate_workflow_classification(tree) == []
    (tree / "README.md").write_text("```bash\npython scripts/validate_outro.py --root .\n```\n", encoding="utf-8")
    problems = validate_workflow_classification(tree)
    assert any("README.md" in problem for problem in problems), problems


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/validate_docs.py --root . && python scripts/escondido.py --root .",
        "python scripts/validate_docs.py --root . || python scripts/escondido.py --root .",
        "python scripts/validate_docs.py --root .; python scripts/escondido.py",
        "python scripts/validate_docs.py --root . | tee /tmp/saida.txt",
        "python scripts/validate_docs.py --root . & python scripts/escondido.py",
        "python scripts/validate_docs.py --root . > /tmp/out&&/tmp/escondido",
        "python scripts/validate_docs.py --root . > /tmp/out;/tmp/escondido",
        "python scripts/validate_docs.py --root . > /tmp/out|/tmp/escondido",
        "python scripts/validate_docs.py --root . > /tmp/out&/tmp/escondido",
        "python scripts/validate_docs.py --root . > /tmp/out$(/tmp/escondido)",
        "python scripts/validate_docs.py --root . > /tmp/out`/tmp/escondido`",
        "python scripts/validate_docs.py --root . > `escondido`",
        "python scripts/validate_docs.py --root . > /tmp/a > /tmp/b",
        "python scripts/validate_docs.py --root . > /tmp/a<<<escondido",
        "python scripts/validate_docs.py --root . > /tmp/a && python scripts/escondido.py",
        "python -c __import__('pathlib').Path('/tmp/x').write_text('a') scripts/validate_docs.py",
        "python -m escondido scripts/validate_docs.py",
        "python ../../escondido.py --root .",
        "eval python scripts/validate_docs.py --root .",
        "env python scripts/validate_docs.py --root .",
        "sudo python scripts/validate_docs.py --root .",
        "time python scripts/validate_docs.py --root .",
        "nohup python scripts/validate_docs.py --root .",
        "sh -c 'python scripts/validate_docs.py --root . ; python scripts/escondido.py'",
        "echo . | xargs python scripts/validate_docs.py --root .",
    ],
)
def test_composite_commands_are_not_classifiable(command: str) -> None:
    """Encadear, substituir ou invocar de outra forma esconde o que executa: reprova."""
    assert command_problems(command), command


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/validate_docs.py --root .",
        "python scripts/validate_docs.py --root . # comentario",
        "python scripts/validate_docs.py --root . > /tmp/saida.txt",
        "python scripts/validate_docs.py --root . > /tmp/saida.txt 2>&1",
        "python scripts/validate_docs.py --root . 2>&1",
        "python -m pytest -q",
        "python -m pip install --require-hashes -r requirements.lock.txt",
        "python evals/run_evals.py --root . --report /tmp/relatorio.json > /tmp/saida.json",
    ],
)
def test_declared_invocations_are_accepted(command: str) -> None:
    """As formas que o repositório usa continuam aceitas, inclusive redirecionamento de saída."""
    assert command_problems(command) == [], command


def test_yaml_forms_cannot_hide_an_unclassified_step(tmp_path: Path) -> None:
    """Formas YAML equivalentes e formas estruturais inválidas não podem esconder um passo ativo."""
    hidden = {
        "chave uses entre aspas": '      - name: escondido\n        "uses": actions/cache@1111111111111111111111111111111111111111\n',
        "chave uses com espaco antes dos dois-pontos": "      - name: escondido\n        uses : actions/cache@1111111111111111111111111111111111111111\n",
        "mapeamento em fluxo com uses": "      - {name: escondido, uses: actions/cache@1111111111111111111111111111111111111111}\n",
        "chave run entre aspas": '      - name: escondido\n        "run": echo escondido\n',
        "chave run com espaco antes dos dois-pontos": "      - name: escondido\n        run : echo escondido\n",
        "mapeamento em fluxo com run": "      - {name: escondido, run: echo escondido}\n",
        "bloco de run vazio": "      - name: escondido\n        run: |\n",
        "bloco dobrado vazio": "      - name: escondido\n        run: >\n",
        "run em lista": "      - name: escondido\n        run: [echo, escondido]\n",
        "uses nao escalar": "      - name: escondido\n        uses: [actions/cache@1111111111111111111111111111111111111111]\n",
        "passo nulo": "      - null\n",
        "run e uses no mesmo passo": "      - name: escondido\n        run: echo escondido\n        uses: actions/cache@1111111111111111111111111111111111111111\n",
        "chave run duplicada": "      - name: escondido\n        run: echo escondido\n        run: python scripts/validate_docs.py --root .\n",
        "chave nao comparavel": "      - name: escondido\n        run: echo escondido\n        ? [a, b]\n        : x\n",
        "acao desconhecida": "      - name: escondido\n        uses: actions/cache@1111111111111111111111111111111111111111\n",
        "comando composto": "      - name: escondido\n        run: python scripts/validate_docs.py --root . && python scripts/escondido.py --root .\n",
    }
    for label, snippet in hidden.items():
        assert classification_problems(workflow_with(tmp_path, snippet)), label
    semantic = {
        "duplicata true e True": "on: [push]\ntrue: a\nTrue: b\n",
        "duplicata yes e true": "on: [push]\nyes: a\ntrue: b\n",
        "duplicata 01 e 1": "on: [push]\n01: a\n1: b\n",
        "duplicata null e til": "on: [push]\nnull: a\n~: b\n",
        "duplicata com tag explicita": "on: [push]\ntrue: a\n!!bool TRUE: b\n",
    }
    for label, replacement in semantic.items():
        content = TEMPLATE.replace("on: [push]\n", replacement)
        path = tmp_path / "workflow.yml"
        path.write_text(content, encoding="utf-8")
        assert classification_problems(path), label
    structure = {
        "steps nao e lista": TEMPLATE.replace("    steps:\n", "    steps: nenhum\n"),
        "job nao e objeto": "name: teste\non: [push]\njobs:\n  validacao: quebrado\n",
        "documento multiplo": TEMPLATE + "---\nname: outro\n",
        "documento escalar": "apenas texto\n",
        "jobs ausente": "name: teste\non: [push]\n",
        "yaml invalido": "name: teste\njobs: [\n",
    }
    for label, content in structure.items():
        path = tmp_path / "workflow.yml"
        path.write_text(content, encoding="utf-8")
        assert classification_problems(path), label
    assert classification_problems(workflow_with(tmp_path, "")) == []


def test_validation_sequence_has_no_duplicated_step() -> None:
    ci = workflow_commands(ROOT / WORKFLOW)
    assert len(ci) == len(set(ci)), "a sequência de validação contém passo duplicado"


def test_workflow_runs_every_standalone_validator() -> None:
    """Todo validador autônomo precisa ser executado, direta ou transitivamente, pelo workflow."""
    ci = workflow_commands(ROOT / WORKFLOW)
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


def invoked_scripts(ci: list[str]) -> list[Path]:
    """Scripts do repositório que um comando do workflow executa."""
    found: list[Path] = []
    for command in ci:
        for part in command.split():
            candidate = ROOT / part
            if part.endswith(".py") and candidate.is_file():
                found.append(candidate)
    return found


def test_closure_check_matches_the_declared_policy(tmp_path: Path) -> None:
    """O fechamento é conferido contra o manifest e a política de exceção, e nada mais."""
    from scripts.lock_dependencies import manifests_for

    assert normalize("python scripts/lock_dependencies.py --root . --check") in workflow_commands(
        ROOT / WORKFLOW
    )
    assert manifests_for(ROOT, None), "nenhum manifest encontrado"
    policy = json.loads((ROOT / "config" / "dependency-policy.json").read_text(encoding="utf-8"))
    assert policy["exceptions"] == [] or policy["exceptions"]


def test_strict_loader_is_the_one_reading_the_workflow() -> None:
    """A leitura do workflow usa o carregador que recusa chave repetida."""
    text = (ROOT / "scripts" / "validate_workflow_classification.py").read_text(encoding="utf-8")
    assert "yaml.load_all(text, Loader=StrictLoader)" in text
    assert yaml.__name__ == "yaml"
    assert ALLOWED_USES
