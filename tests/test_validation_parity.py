"""The documented validation sequence must be the executed one.

`README.md` and `AGENTS.md` claim their sequence is identical to the CI workflow.
That claim drifted twice already, because nothing checked it. This test reads the
commands out of the workflow and out of the documented bash blocks and compares
them in order.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "validate.yml"
SHELL_FENCES = {"```bash", "```sh", "```shell"}
VALIDATION_MARKERS = (
    "scripts/validate_",
    "scripts/sync_contracts.py",
    "scripts/build_catalog_docs.py",
    "evals/run_evals.py",
    "-m pytest",
    "-m pip install",
)


def normalize(command: str) -> str:
    command = " ".join(command.split())
    command = re.split(r"\s+>\s*", command)[0]
    return re.sub(r"\s+2>&1\s*$", "", command).strip()


def is_validation(command: str) -> bool:
    if "--write" in command:
        return False
    return command.startswith("python ") and any(marker in command for marker in VALIDATION_MARKERS)


def workflow_commands(path: Path) -> list[str]:
    commands: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        match = re.match(r"^(\s*)run:\s*(.*)$", lines[index])
        if not match:
            index += 1
            continue
        indent, value = match.group(1), match.group(2).strip()
        if value in {"|", "|-", ">", ">-"}:
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if not candidate.strip():
                    index += 1
                    continue
                if len(candidate) - len(candidate.lstrip()) <= len(indent):
                    break
                commands.append(candidate.strip())
                index += 1
            continue
        commands.append(value)
        index += 1
    return [normalized for normalized in (normalize(command) for command in commands) if is_validation(normalized)]


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


def test_local_validation_sequence_matches_the_ci_workflow() -> None:
    ci = workflow_commands(WORKFLOW)
    assert ci, "o workflow não declara nenhum comando de validação"
    for document in ("README.md", "AGENTS.md"):
        documented = markdown_commands(ROOT / document)
        assert documented == ci, f"{document} diverge da sequência executada pelo CI"


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


def invoked_scripts(ci: list[str]) -> list[Path]:
    """Return the repository scripts that a workflow command executes."""
    found: list[Path] = []
    for command in ci:
        for part in command.split():
            candidate = ROOT / part
            if part.endswith(".py") and candidate.is_file():
                found.append(candidate)
    return found
