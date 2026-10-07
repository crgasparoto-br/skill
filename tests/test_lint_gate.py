"""Regressao do gate de lint: politica completa, discriminacao, supressao declarada e fail-closed.

Os testes usam a politica real do repositorio e arvores temporarias, de modo que a decisao de
politica nao possa afrouxar sem que um teste mude de resultado.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_lint import POLICY, catalog_of, tool_path, validate_lint

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / POLICY
CLEAN_MODULE = "def total(values: list[int]) -> int:\n    return sum(values)\n"
UNUSED_IMPORT_MODULE = "import json\n\n\ndef total(values: list[int]) -> int:\n    return sum(values)\n"


def load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def make_tree(tmp_path: Path, policy: dict, sources: dict[str, str]) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "lint-policy.json").write_text(
        json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, content in sources.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return tmp_path


UNUSED_VARIABLE_MODULE = "def f() -> None:\n    unused = 1\n"


def set_family(policy: dict, prefix: str, state: str, select: list[str], ignore: list[str]) -> None:
    """Troca a decisao de uma familia para exercitar a tentativa de burla do gate."""
    for entry in policy["families"]:
        if entry["prefix"] == prefix:
            entry.update({"state": state, "select": select, "ignore": ignore})
            entry["reason"] = (
                None
                if state == "selected"
                else "motivo declarado apenas para exercitar a tentativa de burla do gate"
            )
            return
    raise AssertionError(f"familia {prefix} ausente")


def dismiss(policy: dict, prefix: str, reason: str = "dispensa declarada de teste com motivo escrito suficiente") -> None:
    for entry in policy["families"]:
        if entry["prefix"] == prefix:
            entry["state"] = "dismissed"
            entry["select"] = []
            entry["ignore"] = []
            entry["reason"] = reason
            return
    raise AssertionError(f"familia {prefix} ausente na politica")


def test_repository_tree_passes_the_gate() -> None:
    assert validate_lint(ROOT) == []


def test_policy_covers_every_family_of_the_installed_tool() -> None:
    errors: list[str] = []
    catalog = catalog_of(tool_path(), errors)
    if not catalog:
        pytest.skip(f"ruff indisponivel para listar o catalogo: {errors}")
    declared = {entry["prefix"] for entry in load_policy()["families"]}
    assert set(catalog.values()) == declared


def test_clean_module_is_approved(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, load_policy(), {"mod.py": CLEAN_MODULE})
    assert validate_lint(tree) == []


def test_unused_import_is_reported(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, load_policy(), {"mod.py": UNUSED_IMPORT_MODULE})
    errors = validate_lint(tree)
    assert any("F401" in error for error in errors), errors


def test_dismissing_a_family_changes_the_verdict(tmp_path: Path) -> None:
    """Discriminacao: a mesma violacao deixa de ser reportada quando a familia e dispensada."""
    policy = load_policy()
    failing = make_tree(tmp_path / "estrito", policy, {"mod.py": UNUSED_IMPORT_MODULE})
    assert any("F401" in error for error in validate_lint(failing))

    lenient = load_policy()
    dismiss(lenient, "F")
    passing = make_tree(tmp_path / "dispensado", lenient, {"mod.py": UNUSED_IMPORT_MODULE})
    assert validate_lint(passing) == []


def test_dismissed_family_without_reason_is_rejected(tmp_path: Path) -> None:
    policy = load_policy()
    dismiss(policy, "F", reason="curto")
    tree = make_tree(tmp_path, policy, {"mod.py": CLEAN_MODULE})
    errors = validate_lint(tree)
    assert any("motivo" in error for error in errors), errors


def test_family_missing_from_the_policy_is_rejected(tmp_path: Path) -> None:
    policy = load_policy()
    policy["families"] = [entry for entry in policy["families"] if entry["prefix"] != "F"]
    tree = make_tree(tmp_path, policy, {"mod.py": CLEAN_MODULE})
    errors = validate_lint(tree)
    assert any("sem decisao" in error for error in errors), errors


def test_declared_version_must_match_the_installed_tool(tmp_path: Path) -> None:
    policy = load_policy()
    policy["tool"]["version"] = "0.0.1"
    tree = make_tree(tmp_path, policy, {"mod.py": CLEAN_MODULE})
    errors = validate_lint(tree)
    assert any("diverge da declarada" in error for error in errors), errors


def test_undeclared_suppression_is_rejected(tmp_path: Path) -> None:
    source = "import json  # noqa: F401 - import mantido de proposito para o teste\n"
    tree = make_tree(tmp_path, load_policy(), {"mod.py": source})
    errors = validate_lint(tree)
    assert any("fora da lista permitida" in error for error in errors), errors


def test_suppression_without_justification_is_rejected(tmp_path: Path) -> None:
    policy = load_policy()
    policy["allowed_suppressions"].append({"code": "F401", "reason": "supressao declarada apenas para o teste de justificativa inline"})
    source = "import json  # noqa: F401\n"
    tree = make_tree(tmp_path, policy, {"mod.py": source})
    errors = validate_lint(tree)
    assert any("sem justificativa" in error for error in errors), errors


def test_missing_tool_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = make_tree(tmp_path, load_policy(), {"mod.py": CLEAN_MODULE})
    monkeypatch.setenv("PATH", "")
    errors = validate_lint(tree)
    assert any("nao instalado" in error for error in errors), errors


def test_gate_runs_without_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("o gate nao pode abrir rede")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    tree = make_tree(tmp_path, load_policy(), {"mod.py": CLEAN_MODULE})
    assert validate_lint(tree) == []


def test_gate_does_not_leave_a_cache(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, load_policy(), {"mod.py": CLEAN_MODULE})
    assert validate_lint(tree) == []
    assert not (tree / ".ruff_cache").exists()


def test_line_length_comes_from_the_policy(tmp_path: Path) -> None:
    """Import longo nao pode ser rewrapped: o limite de linha e o declarado na politica."""
    source = (
        "from collections import OrderedDict\n\n\n"
        "def make() -> OrderedDict[str, str]:\n"
        f"    return OrderedDict([(\"chave\", {('\"' + 'x' * 150 + '\"')})])\n"
    )
    tree = make_tree(tmp_path, load_policy(), {"mod.py": source})
    assert validate_lint(tree) == []


def test_cli_reports_failure_with_non_zero_exit(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, load_policy(), {"mod.py": UNUSED_IMPORT_MODULE})
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_lint.py"), "--root", str(tree)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(ROOT),
    )
    assert completed.returncode == 1
    assert "F401" in completed.stderr


def test_policy_declares_the_pinned_tool_version() -> None:
    lock = (ROOT / "requirements.lock.txt").read_text(encoding="utf-8")
    version = load_policy()["tool"]["version"]
    assert f"ruff=={version}" in lock


def test_policy_artifacts_are_registered_in_the_aggregate_validator() -> None:
    text = (ROOT / "scripts" / "validate_repository.py").read_text(encoding="utf-8")
    assert '"config/lint-policy.json"' in text
    assert '"scripts/validate_lint.py"' in text
    assert "validate_lint(ROOT)" in text


def test_validation_sequence_runs_the_gate_everywhere() -> None:
    command = "python scripts/validate_lint.py --root ."
    for name in ("README.md", "AGENTS.md", ".github/workflows/validate.yml"):
        assert command in (ROOT / name).read_text(encoding="utf-8"), name


@pytest.mark.parametrize("state", ["selected", "partial", "dismissed"])
def test_states_are_only_the_declared_ones(state: str) -> None:
    states = {entry["state"] for entry in load_policy()["families"]}
    assert states <= {"selected", "partial", "dismissed"}
    assert state in states


def test_repository_has_no_untracked_ruff_cache() -> None:
    assert not (ROOT / ".ruff_cache").exists()


def test_tool_is_available_for_the_gate() -> None:
    executable = shutil.which("ruff")
    if executable is None:  # pragma: no cover - ambiente sem a ferramenta
        pytest.skip("ruff indisponivel neste ambiente")
    completed = subprocess.run([executable, "--version"], capture_output=True, text=True, check=False)
    assert load_policy()["tool"]["version"] in completed.stdout


def test_environment_can_locate_python_for_the_gate() -> None:
    assert os.environ.get("PATH")


def test_narrow_selection_inside_an_applied_family_is_rejected(tmp_path: Path) -> None:
    """Cobertura e conferida no nivel da regra: select estreito nao pode encolher a familia."""
    policy = load_policy()
    set_family(policy, "F", "selected", ["F401"], [])
    tree = make_tree(tmp_path, policy, {"mod.py": UNUSED_VARIABLE_MODULE})
    errors = validate_lint(tree)
    assert any("nao decide sobre toda a familia" in error for error in errors), errors


def test_partial_family_without_disabled_part_is_rejected(tmp_path: Path) -> None:
    policy = load_policy()
    set_family(policy, "F", "partial", ["F401"], [])
    tree = make_tree(tmp_path, policy, {"mod.py": UNUSED_VARIABLE_MODULE})
    errors = validate_lint(tree)
    assert any("parte desligada" in error for error in errors), errors


def test_applied_family_cannot_disable_rules(tmp_path: Path) -> None:
    policy = load_policy()
    set_family(policy, "F", "selected", ["F"], ["F"])
    tree = make_tree(tmp_path, policy, {"mod.py": UNUSED_IMPORT_MODULE})
    errors = validate_lint(tree)
    assert any("nao pode desligar regra" in error for error in errors), errors


def test_entry_from_another_family_is_rejected(tmp_path: Path) -> None:
    policy = load_policy()
    set_family(policy, "F", "selected", ["A"], [])
    tree = make_tree(tmp_path, policy, {"mod.py": UNUSED_VARIABLE_MODULE})
    errors = validate_lint(tree)
    assert any("nao pertence a familia" in error for error in errors), errors


def test_partial_family_that_disables_everything_is_rejected(tmp_path: Path) -> None:
    policy = load_policy()
    set_family(policy, "PERF", "partial", ["PERF"], ["PERF"])
    tree = make_tree(tmp_path, policy, {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"})
    errors = validate_lint(tree)
    assert any("desliga a familia inteira" in error for error in errors), errors


def test_uppercase_directive_is_read_as_suppression(tmp_path: Path) -> None:
    source = "import json  # NOQA: F401 - motivo proprio da tentativa de burla\n"
    tree = make_tree(tmp_path, load_policy(), {"mod.py": source})
    errors = validate_lint(tree)
    assert any("fora da lista permitida" in error for error in errors), errors


def test_file_level_directive_is_read_as_suppression(tmp_path: Path) -> None:
    source = "import json  # ruff: noqa: F401\n"
    tree = make_tree(tmp_path, load_policy(), {"mod.py": source})
    errors = validate_lint(tree)
    assert any("fora da lista permitida" in error for error in errors), errors


def test_file_level_directive_without_codes_is_rejected(tmp_path: Path) -> None:
    source = "import json  # ruff: noqa\n"
    tree = make_tree(tmp_path, load_policy(), {"mod.py": source})
    errors = validate_lint(tree)
    assert any("supressao de arquivo sem codigo declarado" in error for error in errors), errors


def test_stub_file_is_covered_by_the_scope(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, load_policy(), {"mod.pyi": "import json\n"})
    errors = validate_lint(tree)
    assert any("F401" in error for error in errors), errors


def test_symlink_outside_the_root_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("import json\n", encoding="utf-8")
    tree = make_tree(tmp_path / "tree", load_policy(), {})
    (tree / "link.py").symlink_to(outside)
    errors = validate_lint(tree)
    assert any("fora da raiz do repositorio" in error for error in errors), errors


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignora permissao de diretorio")
def test_unreadable_directory_is_rejected(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, load_policy(), {"secret/mod.py": UNUSED_IMPORT_MODULE})
    secret = tree / "secret"
    secret.chmod(0o000)
    try:
        errors = validate_lint(tree)
    finally:
        secret.chmod(0o755)
    assert any("diretorio ilegivel" in error for error in errors), errors


def test_unexpected_tool_output_is_a_controlled_failure(tmp_path: Path) -> None:
    fake = tmp_path / "bin"
    fake.mkdir()
    executable = fake / "ruff"
    executable.write_text("#!/usr/bin/env python3\nimport sys\nprint('null')\n", encoding="utf-8")
    executable.chmod(0o755)
    tree = make_tree(tmp_path / "tree", load_policy(), {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"})
    environment = dict(os.environ)
    environment["PATH"] = f"{fake}:{environment.get('PATH', '')}"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_lint.py"), "--root", str(tree)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(ROOT),
        env=environment,
    )
    assert completed.returncode == 1
    assert "Traceback" not in completed.stderr
    assert "formato inesperado" in completed.stderr


def test_scope_is_declared_in_the_policy() -> None:
    scope = load_policy()["scope"]
    assert scope["extensions"] == [".py", ".pyi"]
    assert "dist" in scope["excluded_directories"]
    assert len(scope["reason"]) >= 40


def test_directory_symlink_outside_the_root_is_rejected(tmp_path: Path) -> None:
    """Diretório linkado para fora não pode sair da análise em silêncio."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "bad.py").write_text(UNUSED_IMPORT_MODULE, encoding="utf-8")
    tree = make_tree(tmp_path / "tree", load_policy(), {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"})
    (tree / "link").symlink_to(outside, target_is_directory=True)
    errors = validate_lint(tree)
    assert any("diretorio do escopo aponta para fora da raiz" in error for error in errors), errors


def test_directory_symlink_inside_the_root_is_rejected(tmp_path: Path) -> None:
    """Diretório linkado não é seguido, então o caso é reprovado em vez de analisado em parte."""
    tree = make_tree(tmp_path, load_policy(), {"real/mod.py": UNUSED_IMPORT_MODULE})
    (tree / "link").symlink_to(tree / "real", target_is_directory=True)
    errors = validate_lint(tree)
    assert any("link simbolico e nao e seguido" in error for error in errors), errors


def test_tree_without_covered_files_is_rejected(tmp_path: Path) -> None:
    """Conjunto vazio de arquivos cobertos não pode ser aprovado."""
    tree = make_tree(tmp_path, load_policy(), {"notes.md": "sem codigo aqui\n"})
    errors = validate_lint(tree)
    assert any("nenhum arquivo coberto encontrado" in error for error in errors), errors


def test_justification_without_text_is_rejected(tmp_path: Path) -> None:
    """O separador sozinho, mesmo com o código permitido, não é justificativa."""
    source = "import json  # noqa: E402 -   \n"
    tree = make_tree(tmp_path, load_policy(), {"mod.py": source})
    errors = validate_lint(tree)
    assert any("sem justificativa propria" in error for error in errors), errors


def test_entry_with_letters_of_another_family_is_rejected(tmp_path: Path) -> None:
    """A parte alfabética da entrada precisa ser o prefixo da família, não um começo textual."""
    policy = load_policy()
    set_family(policy, "PLC", "selected", ["P"], [])
    tree = make_tree(tmp_path, policy, {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"})
    errors = validate_lint(tree)
    assert any("nao pertence a familia" in error for error in errors), errors


def test_empty_tool_output_is_a_controlled_failure(tmp_path: Path) -> None:
    """Saída vazia da ferramenta não pode virar aprovação."""
    real = shutil.which("ruff")
    assert real, "o gate exige a ferramenta instalada para este teste"
    fake = tmp_path / "bin"
    fake.mkdir()
    executable = fake / "ruff"
    # Catalogo e versao vem da ferramenta real: a politica fica integra e o caso isola a
    # saida vazia da analise, que e o comportamento em teste.
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import subprocess\n"
        "import sys\n"
        f"REAL = {real!r}\n"
        "arguments = sys.argv[1:]\n"
        "if arguments and arguments[0] == 'check':\n"
        "    sys.exit(0)\n"
        "sys.exit(subprocess.run([REAL, *arguments]).returncode)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    tree = make_tree(tmp_path / "tree", load_policy(), {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"})
    environment = dict(os.environ)
    environment["PATH"] = f"{fake}:{environment.get('PATH', '')}"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_lint.py"), "--root", str(tree)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(ROOT),
        env=environment,
    )
    assert completed.returncode == 1
    assert "saida da analise vazia" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_broken_policy_does_not_run_the_analysis(tmp_path: Path) -> None:
    """Política quebrada é a causa: a análise não roda em cima de uma seleção inválida."""
    policy = load_policy()
    set_family(policy, "F", "selected", ["f"], [])
    tree = make_tree(
        tmp_path,
        policy,
        {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"},
    )
    errors = validate_lint(tree)
    assert any("select invalido" in error for error in errors), errors
    assert not any(error.startswith("ruff:") for error in errors), errors


def test_broken_directory_symlink_is_rejected(tmp_path: Path) -> None:
    """Link de diretório quebrado aparece como arquivo e não pode sair da análise em silêncio."""
    tree = make_tree(tmp_path, load_policy(), {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"})
    (tree / "link").symlink_to(tmp_path / "inexistente", target_is_directory=True)
    errors = validate_lint(tree)
    assert any("link simbolico quebrado ou ciclico" in error for error in errors), errors


def test_cyclic_symlink_is_rejected(tmp_path: Path) -> None:
    """Ciclo de links não pode desaparecer do conjunto varrido."""
    tree = make_tree(tmp_path, load_policy(), {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"})
    (tree / "a").symlink_to(tree / "b", target_is_directory=True)
    (tree / "b").symlink_to(tree / "a", target_is_directory=True)
    errors = validate_lint(tree)
    assert any("link simbolico quebrado ou ciclico" in error for error in errors), errors


def test_lowercase_entry_is_rejected_by_the_policy(tmp_path: Path) -> None:
    """Entrada em caixa diferente reprova na política, antes de chegar à ferramenta."""
    policy = load_policy()
    set_family(policy, "F", "selected", ["f"], [])
    tree = make_tree(tmp_path, policy, {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"})
    errors = validate_lint(tree)
    assert any("select invalido" in error for error in errors), errors


def test_tool_that_disappears_before_the_analysis_is_rejected(tmp_path: Path) -> None:
    """Executável que desaparece entre a versão e a análise não pode virar aprovação."""
    real = shutil.which("ruff")
    assert real, "o gate exige a ferramenta instalada para este teste"
    fake = tmp_path / "bin"
    fake.mkdir()
    executable = fake / "ruff"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import subprocess\n"
        "import sys\n"
        f"REAL = {real!r}\n"
        "arguments = sys.argv[1:]\n"
        "if '--version' in arguments:\n"
        "    print('ruff 0.14.1')\n"
        "    os.remove(__file__)\n"
        "    sys.exit(0)\n"
        "sys.exit(subprocess.run([REAL, *arguments]).returncode)\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    tree = make_tree(tmp_path / "tree", load_policy(), {"mod.py": "def total(values: list[int]) -> int:\n    return sum(values)\n"})
    environment = dict(os.environ)
    environment["PATH"] = f"{fake}:{environment.get('PATH', '')}"
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_lint.py"), "--root", str(tree)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(ROOT),
        env=environment,
    )
    assert completed.returncode == 1
    assert "indisponivel no momento da analise" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_structurally_invalid_policy_fails_with_only_the_cause(tmp_path: Path) -> None:
    """Forma bruta inválida reprova com a causa da política, sem traceback e sem sintoma da ferramenta."""
    clean = "def total(values: list[int]) -> int:\n    return sum(values)\n"

    def drop_families(policy: dict) -> None:
        policy.pop("families")

    def null_families(policy: dict) -> None:
        policy["families"] = None

    def entry_not_object(policy: dict) -> None:
        policy["families"].append("quebrado")

    def null_select(policy: dict) -> None:
        policy["families"][0]["select"] = None

    def null_suppressions(policy: dict) -> None:
        policy["allowed_suppressions"] = None

    def scalar_line_length(policy: dict) -> None:
        policy["line_length"] = "100"

    def list_line_length(policy: dict) -> None:
        policy["line_length"] = [100]

    shapes = {
        "families-ausente": drop_families,
        "families-nulo": null_families,
        "entrada-nao-objeto": entry_not_object,
        "select-nulo": null_select,
        "supressoes-nulas": null_suppressions,
        "line-length-escalar": scalar_line_length,
        "line-length-lista": list_line_length,
    }
    for label, mutate in shapes.items():
        policy = load_policy()
        mutate(policy)
        tree = make_tree(tmp_path / label, policy, {"mod.py": clean})
        errors = validate_lint(tree)
        assert errors, label
        assert any(error.startswith("politica:") for error in errors), (label, errors)
        assert not any(error.startswith("ruff:") for error in errors), (label, errors)
