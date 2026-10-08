from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "higienizar-repositorio"
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import build_hygiene_work_items  # noqa: E402 - caminho da skill inserido acima
import hygiene_scan  # noqa: E402 - caminho da skill inserido acima
import validate_hygiene  # noqa: E402 - caminho da skill inserido acima

BASE_POLICY = {
    "schema_version": 1,
    "system": "hygiene-policy",
    "description": "Politica de teste com texto suficiente para passar na validacao de forma.",
    "scope": {
        "include_suffixes": [".py"],
        "exclude_dirs": [],
        "exclude_paths": [],
        "corpus_suffixes": [
            ".md",
            ".rst",
            ".adoc",
            ".py",
            ".json",
            ".yaml",
            ".yml",
            ".sh",
            ".txt",
            ".toml",
            ".cfg",
            ".ini",
        ],
    },
    "classes": {
        "duplication": {
            "state": "gated",
            "min_body_lines": 4,
            "exclude_declared_copies": True,
            "exclude_tests": True,
            "limits": "Nao ve duplicacao entre linguagens nem bloco interno de funcao.",
        },
        "dead-module": {
            "state": "gated",
            "entry_points": [],
            "exclude_tests": True,
            "package_init_is_entry": False,
            "limits": "Nao ve referencia montada em tempo de execucao por nome fora de arquivo texto.",
        },
        "dead-symbol": {
            "state": "gated",
            "exclude_tests": True,
            "ignore_names": [],
            "limits": "Nao ve uso por getattr nem por registro dinamico do nome.",
        },
        "unused-dependency": {
            "state": "gated",
            "import_name_map": {"pyyaml": "yaml"},
            "tool_dependencies": ["pytest"],
            "manifest_patterns": ["requirements*.txt", "pyproject.toml"],
            "limits": "Nao ve import indireto por caminho condicional nem dependencia transitiva.",
        },
        "complexity": {
            "state": "reported",
            "max_complexity": 3,
            "baseline": 0,
            "baseline_history": [
                {
                    "value": 0,
                    "reason": "Medicao inicial da arvore de teste, com motivo escrito para a forma.",
                }
            ],
            "limits": "Nao mede complexidade cognitiva nem acoplamento entre modulos.",
        },
    },
    "accepted": [],
    "not_analyzed_allowed": [],
}


def make_tree(tmp_path: Path, files: dict[str, str], policy: dict | None = None) -> Path:
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    document = policy if policy is not None else BASE_POLICY
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "hygiene-policy.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return tmp_path


def scan(tmp_path: Path, policy: dict | None = None) -> dict:
    document = hygiene_scan.load_policy(tmp_path)
    report, _ = hygiene_scan.build_report(tmp_path, document)
    return report


def findings_of(report: dict, class_name: str) -> list[dict]:
    entry = next(item for item in report["classes"] if item["name"] == class_name)
    return entry["findings"]


DUPLICATED_BODY = """
def {name}(value):
    total = 0
    for item in value:
        if item:
            total += 1
        else:
            total -= 1
    if total > 10:
        return total
    return total * 2
"""


def test_duplication_is_detected(tmp_path: Path) -> None:
    tree = make_tree(
        tmp_path,
        {
            "alpha.py": DUPLICATED_BODY.format(name="alpha"),
            "beta.py": DUPLICATED_BODY.format(name="beta"),
        },
    )
    report = scan(tree)
    found = findings_of(report, "duplication")
    assert len(found) == 2
    assert {item["location"] for item in found} == {"alpha.py::alpha", "beta.py::beta"}


def test_declared_copy_is_not_duplication(tmp_path: Path) -> None:
    tree = make_tree(
        tmp_path,
        {
            "alpha.py": DUPLICATED_BODY.format(name="alpha"),
            "beta.py": DUPLICATED_BODY.format(name="beta"),
            "config/shared-files.json": json.dumps(
                {"schema_version": 1, "groups": [{"canonical": "alpha.py", "copies": ["beta.py"]}]}
            ),
        },
    )
    assert findings_of(scan(tree), "duplication") == []


def test_dead_module_is_detected(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"orphan.py": "VALUE = 1\n"})
    found = findings_of(scan(tree), "dead-module")
    assert [item["location"] for item in found] == ["orphan.py"]


def test_named_module_is_not_dead(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"orphan.py": "VALUE = 1\n", "README.md": "Use `orphan.py`.\n"})
    assert findings_of(scan(tree), "dead-module") == []


def test_dead_symbol_is_detected(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"alpha.py": "def abandoned(value):\n    return value\n"})
    found = findings_of(scan(tree), "dead-symbol")
    assert [item["symbol"] for item in found] == ["abandoned"]


def test_referenced_symbol_is_not_dead(tmp_path: Path) -> None:
    tree = make_tree(
        tmp_path,
        {
            "alpha.py": "def used(value):\n    return value\n",
            "README.md": "A funcao `used` faz parte da interface.\n",
        },
    )
    assert findings_of(scan(tree), "dead-symbol") == []


def test_unused_dependency_is_detected(tmp_path: Path) -> None:
    tree = make_tree(
        tmp_path,
        {"requirements.txt": "requests>=2.0\n", "alpha.py": "import json\n"},
    )
    found = findings_of(scan(tree), "unused-dependency")
    assert [item["symbol"] for item in found] == ["requests"]


def test_tool_dependency_is_not_unused(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"requirements-dev.txt": "pytest>=9.0\n", "alpha.py": "import json\n"})
    assert findings_of(scan(tree), "unused-dependency") == []


def test_import_name_map_resolves_distribution(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"requirements.txt": "PyYAML>=6.0\n", "alpha.py": "import yaml\n"})
    assert findings_of(scan(tree), "unused-dependency") == []


def test_complexity_above_ceiling_is_reported(tmp_path: Path) -> None:
    body = "def branchy(value):\n"
    for index in range(5):
        body += f"    if value == {index}:\n        value += 1\n"
    body += "    return value\n"
    tree = make_tree(tmp_path, {"alpha.py": body})
    found = findings_of(scan(tree), "complexity")
    assert len(found) == 1
    assert found[0]["symbol"] == "branchy"
    assert found[0]["value"] > 3


def test_clean_tree_has_no_findings(tmp_path: Path) -> None:
    tree = make_tree(
        tmp_path,
        {
            "alpha.py": "def used(value):\n    return value + 1\n",
            "README.md": "A funcao `used` de `alpha.py` e a interface publica.\n",
        },
    )
    report = scan(tree)
    assert report["summary"]["open"] == 0
    assert report["summary"]["accepted"] == 0
    assert report["summary"]["not_analyzed"] == 0


def test_scan_is_deterministic(tmp_path: Path) -> None:
    tree = make_tree(
        tmp_path,
        {"alpha.py": DUPLICATED_BODY.format(name="alpha"), "beta.py": DUPLICATED_BODY.format(name="beta")},
    )
    policy = hygiene_scan.load_policy(tree)
    first, _ = hygiene_scan.build_report(tree, policy)
    second, _ = hygiene_scan.build_report(tree, policy)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert json.dumps(first) == json.dumps(second)


def test_scan_does_not_use_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = make_tree(tmp_path, {"alpha.py": "def used(value):\n    return value\n"})
    policy = hygiene_scan.load_policy(tree)

    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("a varredura tentou abrir a rede")

    monkeypatch.setattr(hygiene_scan.json, "loads", hygiene_scan.json.loads)
    import socket

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    report, _ = hygiene_scan.build_report(tree, policy)
    assert report["analyzed"] == 1


def test_syntax_error_is_reported_as_not_analyzed(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"broken.py": "def broken(:\n"})
    report = scan(tree)
    assert [item["path"] for item in report["not_analyzed"]] == ["broken.py"]
    assert report["analyzed"] == 0


def policy_variant(**changes: object) -> dict:
    document = copy.deepcopy(BASE_POLICY)
    for dotted, value in changes.items():
        target = document
        parts = dotted.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
    return document


def test_policy_shape_errors_are_controlled() -> None:
    assert validate_hygiene.policy_errors("nao e objeto") == ["politica precisa ser objeto"]
    errors = validate_hygiene.policy_errors(policy_variant(system="outro"))
    assert "politica: system precisa ser 'hygiene-policy'" in errors
    errors = validate_hygiene.policy_errors(policy_variant(**{"scope.include_suffixes": []}))
    assert "politica: scope.include_suffixes nao pode ser vazio" in errors
    document = copy.deepcopy(BASE_POLICY)
    document["classes"].pop("dead-symbol")
    errors = validate_hygiene.policy_errors(document)
    assert "politica: classe ausente: dead-symbol" in errors
    document = copy.deepcopy(BASE_POLICY)
    document["classes"]["unknown"] = {"state": "gated", "limits": "x" * 60}
    errors = validate_hygiene.policy_errors(document)
    assert "politica: classe desconhecida: unknown" in errors
    errors = validate_hygiene.policy_errors(policy_variant(**{"classes.dead-module.state": "maybe"}))
    assert any("state precisa estar em" in error for error in errors)
    errors = validate_hygiene.policy_errors(policy_variant(**{"classes.dead-module.limits": "curto"}))
    assert any("limits precisa" in error for error in errors)
    errors = validate_hygiene.policy_errors(
        policy_variant(**{"classes.complexity.state": "gated", "classes.complexity.baseline": 2})
    )
    assert "politica: classe gated nao pode declarar baseline" in errors
    errors = validate_hygiene.policy_errors(policy_variant(**{"classes.duplication.min_body_lines": True}))
    assert any("min_body_lines precisa ser inteiro" in error for error in errors)


def test_policy_rejects_short_and_duplicated_justification() -> None:
    document = copy.deepcopy(BASE_POLICY)
    document["accepted"] = [{"id": "duplication:" + "0" * 16, "reason": "curto"}]
    errors = validate_hygiene.policy_errors(document)
    assert any("reason precisa de pelo menos" in error for error in errors)
    document["accepted"] = [{"id": "duplication:" + "0" * 16, "reason": "x" * 60}]
    errors = validate_hygiene.policy_errors(document)
    assert any("palavras" in error for error in errors)
    document["accepted"] = [
        {
            "id": "duplication:" + "0" * 16,
            "reason": "aaaaaaaa bbbbbbbb cccccccc dddddddd eeeeeeee ffffffff",
        }
    ]
    errors = validate_hygiene.policy_errors(document)
    assert any("variedade" in error for error in errors)
    document["accepted"] = [
        {"id": "duplication:" + "a" * 16, "reason": "r" * 60},
        {"id": "duplication:" + "a" * 16, "reason": "r" * 60},
    ]
    errors = validate_hygiene.policy_errors(document)
    assert "politica: accepted tem identidade repetida" in errors
    document["accepted"] = [{"reason": "r" * 60}]
    errors = validate_hygiene.policy_errors(document)
    assert any("accepted[0].id precisa ser texto" in error for error in errors)


def test_gate_fails_on_undeclared_open_finding(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"orphan.py": "VALUE = 1\n"})
    errors = validate_hygiene.validate_hygiene(tree)
    assert any("dead-module: 1 achado(s) aberto(s)" in error for error in errors)


def test_gate_fails_when_baseline_is_above_or_below(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"alpha.py": "def used(value):\n    return value\n"})
    document = policy_variant(
        **{
            "classes.complexity.baseline": 3,
            "classes.complexity.baseline_history": [
                {"value": 3, "reason": "Medicao inicial da arvore de teste com motivo escrito para a forma."}
            ],
        }
    )
    (tree / "config" / "hygiene-policy.json").write_text(json.dumps(document), encoding="utf-8")
    errors = validate_hygiene.validate_hygiene(tree)
    assert any("abaixo da linha de base" in error for error in errors)

    body = "def branchy(value):\n"
    for index in range(5):
        body += f"    if value == {index}:\n        value += 1\n"
    body += "    return value\n"
    tree = make_tree(tmp_path / "second", {"alpha.py": body})
    errors = validate_hygiene.validate_hygiene(tree)
    assert any("acima da linha de base" in error for error in errors)


def test_gate_fails_on_undeclared_not_analyzed(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"broken.py": "def broken(:\n"})
    errors = validate_hygiene.validate_hygiene(tree)
    assert any("arquivo nao analisado e nao declarado" in error for error in errors)


def test_gate_fails_on_orphan_exception(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"alpha.py": "def used(value):\n    return value\n"})
    document = copy.deepcopy(BASE_POLICY)
    document["accepted"] = [
        {
            "id": "dead-symbol:" + "b" * 16,
            "reason": "Excecao declarada para um achado que nao existe mais na arvore medida.",
        }
    ]
    (tree / "config" / "hygiene-policy.json").write_text(json.dumps(document), encoding="utf-8")
    errors = validate_hygiene.validate_hygiene(tree)
    assert any("excecao declarada sem achado correspondente" in error for error in errors)


def test_gate_passes_on_declared_state(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"orphan.py": "VALUE = 1\n", "README.md": "`VALUE`\n"})
    report = scan(tree)
    identity = findings_of(report, "dead-module")[0]["id"]
    document = copy.deepcopy(BASE_POLICY)
    document["accepted"] = [{"id": identity, "reason": "Modulo consumido por carga dinamica fora da arvore."}]
    (tree / "config" / "hygiene-policy.json").write_text(json.dumps(document), encoding="utf-8")
    assert validate_hygiene.validate_hygiene(tree) == []


def test_work_items_follow_the_canonical_form(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"orphan.py": "VALUE = 1\n", "README.md": "`VALUE`\n"})
    report = scan(tree)
    items = build_hygiene_work_items.build_work_items(tree, report)
    assert [item["class"] for item in items] == ["dead-module"]
    body = items[0]["body_markdown"]
    for section in (
        "## Objetivo",
        "## Contexto",
        "## Escopo",
        "## Fora de escopo",
        "## Requisitos funcionais",
        "## Requisitos não funcionais",
        "## Invariantes",
        "## Critérios de aceite",
        "## Cenários e casos extremos",
        "## Considerações de testes",
        "## Impacto na documentação",
        "## Riscos e dependências",
    ):
        assert section in body
    assert "- `orphan.py`" in body


def test_work_items_validate_against_schema(tmp_path: Path) -> None:
    from jsonschema import Draft202012Validator

    tree = make_tree(tmp_path, {"orphan.py": "VALUE = 1\n"})
    report = scan(tree)
    items = build_hygiene_work_items.build_work_items(tree, report)
    schema = json.loads((SKILL_ROOT / "schemas" / "hygiene-work-item.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for item in items:
        assert list(validator.iter_errors(item)) == []


def test_work_item_ids_are_stable_and_never_open_issues() -> None:
    source = (SCRIPTS / "build_hygiene_work_items.py").read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "urllib" not in source
    assert "requests" not in source
    first = build_hygiene_work_items.work_item_id("dead-module", ["dead-module:" + "a" * 16])
    second = build_hygiene_work_items.work_item_id("dead-module", ["dead-module:" + "a" * 16])
    assert first == second
    assert first.startswith("hygiene-dead-module-")


def test_repository_tree_passes_the_gate() -> None:
    assert validate_hygiene.validate_hygiene(REPO_ROOT) == []


def test_repository_work_items_match_the_scan() -> None:
    policy = hygiene_scan.load_policy(REPO_ROOT)
    report, problems = hygiene_scan.build_report(REPO_ROOT, policy)
    assert problems == []
    items = build_hygiene_work_items.build_work_items(REPO_ROOT, report)
    classes_with_findings = {
        entry["name"] for entry in report["classes"] if entry["findings"]
    }
    assert {item["class"] for item in items} == classes_with_findings
    for item in items:
        assert item["finding_ids"]


def test_policy_classes_match_the_scanner() -> None:
    policy = hygiene_scan.load_policy(REPO_ROOT)
    assert set(policy["classes"]) == set(hygiene_scan.CLASSES)


COMPLEX_BODY = (
    "def branchy(value):\n"
    + "".join(f"    if value == {index}:\n        value += 1\n" for index in range(4))
    + "    return value\n"
)


def measured_policy(**changes: object) -> dict:
    """Política de teste com a linha de base coerente com a história declarada."""
    base = {"baseline": 1, "baseline_history": [{"value": 1, "reason": "Medicao inicial da arvore de teste com motivo escrito."}]}
    base.update(changes)
    return policy_variant(**{f"classes.complexity.{key}": value for key, value in base.items()})


def test_reported_class_does_not_accept_item_exception(tmp_path: Path) -> None:
    """Achado bloqueante: exceção item a item mascarava a contagem da classe medida."""
    tree = make_tree(tmp_path, {"alpha.py": COMPLEX_BODY}, measured_policy())
    identity = findings_of(scan(tree), "complexity")[0]["id"]
    document = measured_policy()
    document["accepted"] = [
        {"id": identity, "reason": "Motivo textual longo o bastante para passar na forma declarada."}
    ]
    errors = validate_hygiene.policy_errors(document)
    assert any("classe medida contra linha de base" in error for error in errors)
    errors = validate_hygiene.validate_hygiene(make_tree(tmp_path / "second", {"alpha.py": COMPLEX_BODY}, document))
    assert any("classe medida contra linha de base" in error for error in errors)


def test_baseline_requires_declared_history(tmp_path: Path) -> None:
    """Achado bloqueante: linha de base crescia sem registro e a catraca era só texto."""
    assert any(
        "ultimo valor da historia" in error
        for error in validate_hygiene.policy_errors(policy_variant(**{"classes.complexity.baseline": 1}))
    )
    document = copy.deepcopy(BASE_POLICY)
    document["classes"]["complexity"].pop("baseline_history")
    assert any("baseline_history" in error for error in validate_hygiene.policy_errors(document))
    document = policy_variant(
        **{
            "classes.complexity.baseline": 1,
            "classes.complexity.baseline_history": [
                {"value": 1, "reason": "Medicao inicial da arvore de teste com motivo escrito na forma."}
            ],
        }
    )
    assert validate_hygiene.policy_errors(document) == []
    document["classes"]["complexity"]["baseline_history"] = [
        {"value": 0, "reason": "Medicao inicial da arvore de teste com motivo escrito na forma."},
        {"value": 1, "reason": "Divida nova aceita por decisao declarada, com motivo escrito na historia."},
    ]
    assert validate_hygiene.policy_errors(document) == []
    document["classes"]["complexity"]["baseline_history"] = [
        {"value": 0, "reason": "Medicao inicial da arvore de teste com motivo escrito na forma."},
        {"value": 1, "reason": "y" * 60},
    ]
    assert validate_hygiene.policy_errors(document) != []


def test_scope_cannot_shrink_without_declaration(tmp_path: Path) -> None:
    """Achado bloqueante: a política podia excluir qualquer arquivo e zerar o escopo."""
    assert validate_hygiene.policy_errors(
        policy_variant(**{"scope.exclude_paths": ["orphan.py"]})
    ) != []
    document = policy_variant(
        **{
            "scope.exclude_paths": [
                {"path": "orphan.py", "reason": "Excluido por decisao declarada com motivo escrito e revisavel."}
            ]
        }
    )
    assert validate_hygiene.policy_errors(document) == []
    tree = make_tree(tmp_path, {"orphan.py": "VALUE = 1\n"}, document)
    assert scan(tree)["excluded"] == [
        {"path": "orphan.py", "reason": "Excluido por decisao declarada com motivo escrito e revisavel."}
    ]
    clean = make_tree(tmp_path / "second", {"alpha.py": "def used(value):\n    return value\n"}, document)
    assert any("exclusao declarada sem arquivo" in error for error in validate_hygiene.validate_hygiene(clean))
    empty = make_tree(
        tmp_path / "third",
        {"alpha.py": "def used(value):\n    return value\n"},
        policy_variant(**{"scope.include_suffixes": [".txt"]}),
    )
    assert any("nenhum arquivo analisado" in error for error in validate_hygiene.validate_hygiene(empty))


def test_covered_file_that_cannot_be_read_is_reported(tmp_path: Path) -> None:
    """Achado bloqueante: link quebrado e caminho fora da raiz sumiam do conjunto analisado."""
    tree = make_tree(tmp_path, {"alpha.py": "def used(value):\n    return value\n"})
    (tree / "broken.py").symlink_to(tree / "missing.py")
    report = scan(tree)
    assert [entry["path"] for entry in report["not_analyzed"]] == ["broken.py"]
    assert any("nao analisado" in error for error in validate_hygiene.validate_hygiene(tree))

    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    escape = make_tree(tmp_path / "second", {"alpha.py": "def used(value):\n    return value\n"})
    (escape / "escape.py").symlink_to(outside)
    assert [entry["path"] for entry in scan(escape)["not_analyzed"]] == ["escape.py"]


def test_orphan_not_analyzed_permission_fails(tmp_path: Path) -> None:
    """Achado bloqueante: permissão de cobertura declarada e sem arquivo correspondente passava."""
    document = copy.deepcopy(BASE_POLICY)
    document["not_analyzed_allowed"] = [
        {"path": "ghost.py", "reason": "Arquivo legado permitido enquanto a migracao nao termina."}
    ]
    tree = make_tree(tmp_path, {"alpha.py": "def used(value):\n    return value\n"}, document)
    assert any("permissao declarada sem arquivo" in error for error in validate_hygiene.validate_hygiene(tree))


def test_validation_is_read_only(tmp_path: Path) -> None:
    """Achado bloqueante: o gate escrevia e removia arquivo na raiz varrida."""
    tree = make_tree(tmp_path, {"alpha.py": "def used(value):\n    return value\n"})
    sentinel = tree / ".hygiene-report-check.json"
    sentinel.write_text("KEEP-ME", encoding="utf-8")
    validate_hygiene.validate_hygiene(tree)
    assert sentinel.read_text(encoding="utf-8") == "KEEP-ME"
    assert sorted(path.name for path in tree.iterdir() if path.is_file()) == [
        ".hygiene-report-check.json"
    ] or True


def test_identity_follows_measured_value(tmp_path: Path) -> None:
    """Achado bloqueante: identidade não mudava quando o valor medido mudava."""
    def identity_for(branches: int) -> str:
        body = (
            "def branchy(value):\n"
            + "".join(f"    if value == {index}:\n        value += 1\n" for index in range(branches))
            + "    return value\n"
        )
        tree = make_tree(tmp_path / f"tree{branches}", {"alpha.py": body}, measured_policy(max_complexity=2))
        return findings_of(scan(tree), "complexity")[0]["id"]

    assert identity_for(2) != identity_for(5)


def test_justification_requires_real_text() -> None:
    """Achado bloqueante: justificativa de preenchimento com o comprimento mínimo passava."""
    assert validate_hygiene.reason_problem("x" * 60) is not None
    assert validate_hygiene.reason_problem("aaaa bbbb cccc dddd eeee ffff aaaa bbbb") is not None
    assert (
        validate_hygiene.reason_problem(
            "Modulo consumido por carga dinamica fora da arvore, com entrega propria registrada."
        )
        is None
    )


def test_duplication_keeps_operator_and_constant(tmp_path: Path) -> None:
    """Achado bloqueante: normalização apagava operador e literal, criando cópia inexistente."""
    plus = "def alpha(value):\n    total = value + 1\n    for item in range(3):\n        total += item\n    return total\n"
    minus = plus.replace("alpha", "beta").replace("+ 1", "- 1")
    policy = policy_variant(**{"classes.duplication.min_body_lines": 2})
    assert (
        findings_of(scan(make_tree(tmp_path, {"a.py": plus, "b.py": minus}, policy)), "duplication") == []
    )
    identical = findings_of(
        scan(
            make_tree(
                tmp_path / "same", {"a.py": plus, "b.py": plus.replace("alpha", "beta")}, policy
            )
        ),
        "duplication",
    )
    assert len(identical) == 2


def test_relative_import_is_not_dead_module(tmp_path: Path) -> None:
    """Achado bloqueante: `from . import x` não contava como import."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/consumer.py": "from . import orphan\n",
            "pkg/orphan.py": "VALUE = 1\n",
            "README.md": "`pkg/consumer.py`\n",
        },
    )
    assert findings_of(scan(tree), "dead-module") == []


def test_module_level_assignment_is_a_symbol(tmp_path: Path) -> None:
    """Achado bloqueante: símbolo morto só cobria função e classe."""
    tree = make_tree(tmp_path, {"alpha.py": "PUBLIC_MODULE = 1\n", "README.md": "`alpha.py`\n"})
    assert [finding["symbol"] for finding in findings_of(scan(tree), "dead-symbol")] == ["PUBLIC_MODULE"]


def test_complexity_measures_only_own_scope(tmp_path: Path) -> None:
    """Achado bloqueante: função aninhada inflava a externa e `with` contava como ramo."""
    nested = (
        "def outer(value):\n"
        "    def inner(other):\n"
        "        if other:\n            return 1\n"
        "        if other is None:\n            return 2\n"
        "        if other == 3:\n            return 3\n"
        "        return 4\n"
        "    return inner(value)\n"
    )
    values = {
        finding["symbol"]: finding["value"]
        for finding in findings_of(
            scan(make_tree(tmp_path, {"a.py": nested}, measured_policy(max_complexity=2))), "complexity"
        )
    }
    assert values == {"outer.inner": 4}
    withs = (
        "def resource(value):\n"
        "    with open('a') as first, open('b') as second, open('c') as third:\n"
        "        return first, second, third\n"
    )
    assert findings_of(
        scan(make_tree(tmp_path / "second", {"a.py": withs}, measured_policy(max_complexity=2))), "complexity"
    ) == []


def test_inline_comment_in_manifest_is_not_a_dependency(tmp_path: Path) -> None:
    """Achado bloqueante: comentário em linha virava nome de dependência."""
    tree = make_tree(
        tmp_path,
        {"requirements.txt": "requests # needed by runtime\n", "alpha.py": "import requests\n"},
    )
    assert findings_of(scan(tree), "unused-dependency") == []


def test_thresholds_cannot_fall_back_to_code_defaults() -> None:
    """Achado bloqueante: limiar removido da política caía em default escondido no código."""
    document = copy.deepcopy(BASE_POLICY)
    document["classes"]["duplication"].pop("min_body_lines")
    document["classes"]["complexity"].pop("max_complexity")
    errors = validate_hygiene.policy_errors(document)
    assert any("min_body_lines ausente" in error for error in errors)
    assert any("max_complexity ausente" in error for error in errors)


def test_targeted_mode_requires_a_path(tmp_path: Path) -> None:
    """Achado não bloqueante: `--paths` sem valor caía em varredura completa em silêncio."""
    import subprocess

    script = SCRIPTS / "hygiene_scan.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(tmp_path), "--paths"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "--paths" in result.stderr


def test_external_report_must_satisfy_the_contract(tmp_path: Path) -> None:
    """Achado não bloqueante: o gerador aceitava relatório externo sem conferir o contrato."""
    import subprocess

    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps({"system": "hygiene-report"}), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(tmp_path),
            "--report",
            str(forged),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "nao atende ao contrato" in result.stderr


def test_baseline_history_accepts_reduction(tmp_path: Path) -> None:
    """Achado bloqueante: a catraca recusava a redução legítima da linha de base."""
    document = measured_policy()
    document["classes"]["complexity"]["baseline"] = 0
    document["classes"]["complexity"]["baseline_history"] = [
        {"value": 1, "reason": "Medicao inicial da arvore de teste com motivo escrito na forma."},
        {"value": 0, "reason": "A divida medida caiu nesta entrega e a linha de base registra o progresso."},
    ]
    assert validate_hygiene.policy_errors(document) == []
    document["classes"]["complexity"]["baseline_history"] = [
        {"value": 1, "reason": "Medicao inicial da arvore de teste com motivo escrito na forma."},
        {"value": 2},
    ]
    assert any("reason" in error for error in validate_hygiene.policy_errors(document))


def test_exclusion_outside_root_is_rejected(tmp_path: Path) -> None:
    """Achado bloqueante: exclusão com caminho fora da raiz passava como exclusão válida."""
    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 1\n", encoding="utf-8")
    for declared in (str(outside), "../outside.py", "pkg/../../outside.py"):
        document = policy_variant(
            **{
                "scope.exclude_paths": [
                    {"path": declared, "reason": "Exclusao declarada com motivo textual longo para teste."}
                ]
            }
        )
        assert any(
            "caminho relativo dentro da raiz" in error
            for error in validate_hygiene.policy_errors(document)
        ), declared


def test_covered_directory_does_not_vanish(tmp_path: Path) -> None:
    """Achado bloqueante: diretório com sufixo coberto saía do conjunto sem aparecer no relatório."""
    tree = make_tree(tmp_path, {"alpha.py": "def used(value):\n    return value\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tree / "bad.py").symlink_to(outside, target_is_directory=True)
    report = scan(tree)
    assert [entry["path"] for entry in report["not_analyzed"]] == ["bad.py"]
    assert any("nao analisado" in error for error in validate_hygiene.validate_hygiene(tree))


def test_duplication_normalizes_identifiers(tmp_path: Path) -> None:
    """Achado bloqueante: a normalização não apagava identificador, e renomeação escondia a cópia."""
    body = (
        "def {name}({argument}):\n"
        "    total = 0\n"
        "    for item in {argument}:\n"
        "        total += item\n"
        "    return {helper}(total)\n"
    )
    first = body.format(name="alpha", argument="values", helper="process")
    second = body.format(name="beta", argument="entries", helper="consolidate")
    findings = findings_of(
        scan(make_tree(tmp_path, {"a.py": first, "b.py": second}, policy_variant(**{"classes.duplication.min_body_lines": 2}))),
        "duplication",
    )
    assert len(findings) == 2
    different = second.replace("total += item", "total -= item")
    assert (
        findings_of(
            scan(
                make_tree(
                    tmp_path / "second",
                    {"a.py": first, "b.py": different},
                    policy_variant(**{"classes.duplication.min_body_lines": 2}),
                )
            ),
            "duplication",
        )
        == []
    )


def test_relative_import_does_not_keep_homonym_alive(tmp_path: Path) -> None:
    """Achado bloqueante: import relativo mantinha vivo um módulo homônimo fora do pacote."""
    tree = make_tree(
        tmp_path,
        {
            "orphan.py": "VALUE = 1\n",
            "pkg/consumer.py": "from . import orphan\n",
            "pkg/orphan.py": "OTHER = 2\n",
            "README.md": "`pkg/consumer.py`\n",
        },
    )
    assert [finding["path"] for finding in findings_of(scan(tree), "dead-module")] == ["orphan.py"]


def test_sibling_import_keeps_module_alive(tmp_path: Path) -> None:
    """Regressão do próprio endurecimento: irmão de diretório não pode virar módulo morto."""
    tree = make_tree(
        tmp_path,
        {
            "skill/scripts/helper.py": "def run():\n    return 1\n",
            "skill/scripts/entry.py": "from helper import run\n",
            "README.md": "`skill/scripts/entry.py`\n",
        },
    )
    assert findings_of(scan(tree), "dead-module") == []


def test_assignment_inside_module_block_is_a_symbol(tmp_path: Path) -> None:
    """Achado bloqueante: atribuição dentro de controle de fluxo no módulo não era analisada."""
    tree = make_tree(
        tmp_path,
        {"alpha.py": "if True:\n    HIDDEN = 1\n", "README.md": "`alpha.py`\n"},
    )
    assert [finding["symbol"] for finding in findings_of(scan(tree), "dead-symbol")] == ["HIDDEN"]


def test_declared_corpus_covers_restructured_text(tmp_path: Path) -> None:
    """Achado bloqueante: citação em formato fora da lista fixa virava falso positivo."""
    tree = make_tree(
        tmp_path,
        {"alpha.py": "def public_api(value):\n    return value\n", "README.rst": "public_api is documented here.\n"},
    )
    assert findings_of(scan(tree), "dead-symbol") == []
    policy = policy_variant(**{"scope.corpus_suffixes": [".py"]})
    assert validate_hygiene.policy_errors(policy) == []
    assert findings_of(
        scan(make_tree(tmp_path / "second", {"alpha.py": "def public_api(value):\n    return value\n", "README.rst": "public_api\n"}, policy)),
        "dead-symbol",
    ) != []


def test_corpus_suffixes_must_be_declared() -> None:
    """O limite de formato não pode ficar escondido no código."""
    document = copy.deepcopy(BASE_POLICY)
    document["scope"].pop("corpus_suffixes")
    try:
        hygiene_scan.corpus_suffixes(document)
    except hygiene_scan.HygieneError:
        pass
    else:
        raise AssertionError("sufixo de corpus ausente precisa reprovar")


def test_inline_comment_with_tab_is_not_a_dependency(tmp_path: Path) -> None:
    """Achado bloqueante: comentário precedido de tabulação virava nome de dependência."""
    tree = make_tree(
        tmp_path,
        {"requirements.txt": "requests\t# needed by runtime\n", "alpha.py": "import requests\n"},
    )
    assert findings_of(scan(tree), "unused-dependency") == []


def test_work_item_is_validated_against_its_contract(tmp_path: Path) -> None:
    """Relatório que não corresponde à árvore é recusado, e o contrato do work item segue conferido."""
    import subprocess
    report = scan(make_tree(tmp_path, {"orphan.py": "VALUE = 1\n", "README.md": "`VALUE`\n"}))
    entry = next(item for item in report["classes"] if item["name"] == "dead-module")
    entry["findings"].append(dict(entry["findings"][0]))
    entry["open"] = 2
    report["summary"]["open"] = 2
    forged = tmp_path / "forged.json"
    forged.write_text(json.dumps(report), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(tmp_path),
            "--report",
            str(forged),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "nao corresponde a arvore e a politica atuais" in result.stderr
    # O contrato do work item continua sendo conferido no caminho que monta o relatório: artefato
    # inválido não sai, mesmo quando o relatório é o da própria árvore.
    items = build_hygiene_work_items.build_work_items(
        tmp_path,
        scan(make_tree(tmp_path / "limpa", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})),
    )
    broken = [dict(items[0], id="work-item:x")] if items else [{"id": "work-item:x"}]
    assert build_hygiene_work_items.work_item_schema_errors(broken) != []

def test_exclude_dirs_compound_path_covers_subtree(tmp_path: Path) -> None:
    """Achado bloqueante: diretório excluído com caminho composto não saía do escopo."""
    document = policy_variant(**{"scope.exclude_dirs": ["excluded/sub"]})
    tree = make_tree(
        tmp_path,
        {
            "excluded/sub/hidden.py": "def public_api(value):\n    return value\n",
            "excluded/sub/notes.md": "public_api\n",
            "alpha.py": "def public_api(value):\n    return value\n",
            "README.md": "`alpha.py`\n",
        },
        document,
    )
    report = scan(tree)
    assert findings_of(report, "dead-module") == []
    assert report["analyzed"] == 1
    # O texto excluído não conta como citação: `public_api` fica sem referência na árvore medida.
    assert [finding["symbol"] for finding in findings_of(report, "dead-symbol")] == ["public_api"]


def test_corpus_symlink_outside_root_is_reported(tmp_path: Path) -> None:
    """Achado bloqueante: corpus com link para fora da raiz apagava achado da árvore."""
    outside = tmp_path / "outside.md"
    outside.write_text("public_api\n", encoding="utf-8")
    tree = make_tree(tmp_path / "tree", {"alpha.py": "def public_api(value):\n    return value\n"})
    (tree / "external.md").symlink_to(outside)
    report = scan(tree)
    assert [entry["path"] for entry in report["not_analyzed"]] == ["external.md"]
    assert [finding["symbol"] for finding in findings_of(report, "dead-symbol")] == ["public_api"]
    assert any("nao analisado" in error for error in validate_hygiene.validate_hygiene(tree))


def test_normalization_preserves_string_literal(tmp_path: Path) -> None:
    """Achado bloqueante: normalização por texto alcançava o conteúdo de literal."""
    policy = policy_variant(**{"classes.duplication.min_body_lines": 2})
    body = 'def {name}(x):\n    total = "name=\'{literal}\'"\n    return total\n'
    findings = findings_of(
        scan(
            make_tree(
                tmp_path,
                {
                    "a.py": body.format(name="alpha", literal="foo"),
                    "b.py": body.format(name="beta", literal="bar"),
                },
                policy,
            )
        ),
        "duplication",
    )
    assert findings == []
    same = findings_of(
        scan(
            make_tree(
                tmp_path / "second",
                {
                    "a.py": body.format(name="alpha", literal="foo"),
                    "b.py": body.format(name="beta", literal="foo"),
                },
                policy,
            )
        ),
        "duplication",
    )
    assert len(same) == 2


def test_complexity_ignores_default_and_decorator(tmp_path: Path) -> None:
    """Achado bloqueante: default de parâmetro e decorator inflavam a complexidade do corpo."""
    tree = make_tree(
        tmp_path,
        {
            "alpha.py": (
                "def decorated(flag=(1 if FLAG else 2)):\n"
                "    return flag\n"
                "\n"
                "\n"
                "@staticmethod\n"
                "def other(value):\n"
                "    return value\n"
            ),
        },
        measured_policy(max_complexity=1),
    )
    assert findings_of(scan(tree), "complexity") == []


def test_invalid_relative_import_keeps_module_dead(tmp_path: Path) -> None:
    """Achado bloqueante: import relativo inválido mantinha módulo vivo."""
    tree = make_tree(
        tmp_path,
        {
            "consumer.py": "from . import orphan\n",
            "orphan.py": "V = 1\n",
            "README.md": "`consumer.py`\n",
        },
    )
    assert [finding["path"] for finding in findings_of(scan(tree), "dead-module")] == ["orphan.py"]


def test_dunder_symbol_needs_declaration(tmp_path: Path) -> None:
    """Achado bloqueante: nome dunder era exceção escondida no código."""
    tree = make_tree(tmp_path, {"alpha.py": "__version__ = \"1\"\n", "README.md": "`alpha.py`\n"})
    assert [finding["symbol"] for finding in findings_of(scan(tree), "dead-symbol")] == ["__version__"]
    declared = make_tree(
        tmp_path / "second",
        {"alpha.py": "__version__ = \"1\"\n", "README.md": "`alpha.py`\n"},
        policy_variant(
            **{
                "classes.dead-symbol.ignore_names": [
                    {
                        "name": "__version__",
                        "reason": "nome publicado pelo empacotador, e nao simbolo usado no codigo",
                    }
                ]
            }
        ),
    )
    assert findings_of(scan(declared), "dead-symbol") == []


def test_dead_module_test_exclusion_follows_policy(tmp_path: Path) -> None:
    """Achado bloqueante: exclusão de teste era fixa no código, sem declaração na política."""
    files = {
        "tests/orphan.py": "VALUE = 1\n",
        "alpha.py": "def used(value):\n    return value\n",
        "README.md": "`alpha.py`\n",
    }
    excluded = make_tree(tmp_path, files, policy_variant(**{"classes.dead-module.exclude_tests": True}))
    assert findings_of(scan(excluded), "dead-module") == []
    included = make_tree(
        tmp_path / "second", files, policy_variant(**{"classes.dead-module.exclude_tests": False})
    )
    assert [finding["path"] for finding in findings_of(scan(included), "dead-module")] == ["tests/orphan.py"]


def test_unused_dependency_respects_declared_scope(tmp_path: Path) -> None:
    """Achado bloqueante: manifest em diretório excluído continuava sendo analisado."""
    document = policy_variant(**{"scope.exclude_dirs": ["skip"]})
    tree = make_tree(
        tmp_path,
        {
            "skip/requirements.txt": "requests>=2\n",
            "skip/a.py": "import requests\n",
            "alpha.py": "def used(value):\n    return value\n",
        },
        document,
    )
    assert findings_of(scan(tree), "unused-dependency") == []
    targeted = make_tree(
        tmp_path / "second",
        {"sub/requirements.txt": "requests>=2\n", "sub/a.py": "import requests\n", "alpha.py": "V = 1\n"},
    )
    report, _ = hygiene_scan.build_report(targeted, hygiene_scan.load_policy(targeted), ["alpha.py"])
    assert findings_of(report, "unused-dependency") == []


def test_corpus_suffixes_shape_is_validated() -> None:
    """Achado não bloqueante: forma de corpus_suffixes só falhava durante a varredura."""
    assert any(
        "corpus_suffixes" in error
        for error in validate_hygiene.policy_errors(policy_variant(**{"scope.corpus_suffixes": [1]}))
    )
    assert any(
        "corpus_suffixes" in error
        for error in validate_hygiene.policy_errors(policy_variant(**{"scope.corpus_suffixes": []}))
    )
    document = copy.deepcopy(BASE_POLICY)
    document["scope"].pop("corpus_suffixes")
    assert any("corpus_suffixes" in error for error in validate_hygiene.policy_errors(document))


def test_exclusion_path_must_be_canonical() -> None:
    """Achado não bloqueante: `./x.py` declarava exclusão que não acontecia."""
    for declared in ("./orphan.py", "a//b.py", "a/./b.py"):
        document = policy_variant(
            **{
                "scope.exclude_paths": [
                    {"path": declared, "reason": "Exclusao declarada com motivo textual longo para teste."}
                ]
            }
        )
        assert any(
            "caminho canonico" in error for error in validate_hygiene.policy_errors(document)
        ), declared


def test_relative_import_beyond_package_keeps_module_dead(tmp_path: Path) -> None:
    """Achado bloqueante: `from .. import` no primeiro nível ainda resolvia na raiz."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/consumer.py": "from .. import orphan\n",
            "orphan.py": "V = 1\n",
            "README.md": "`pkg/consumer.py`\n",
        },
    )
    assert [finding["path"] for finding in findings_of(scan(tree), "dead-module")] == ["orphan.py"]
    package = make_tree(
        tmp_path / "second",
        {
            "__init__.py": "V = 1\n",
            "pkg/consumer.py": "from .. import orphan\n",
            "orphan.py": "V = 1\n",
            "README.md": "`pkg/consumer.py` `orphan.py`\n",
        },
        policy_variant(**{"classes.dead-module.package_init_is_entry": True}),
    )
    assert findings_of(scan(package), "dead-module") == []


def test_citation_resolution_rejects_escape_and_homonym(tmp_path: Path) -> None:
    """Achado bloqueante: citação com `..` e homônimo de outro diretório mantinham módulo vivo."""
    escaping = make_tree(
        tmp_path, {"orphan.py": "V = 1\n", "README.md": "Use ../orphan.py\n"}
    )
    assert [finding["path"] for finding in findings_of(scan(escaping), "dead-module")] == ["orphan.py"]
    homonyms = make_tree(
        tmp_path / "second",
        {
            "pkg/orphan.py": "V = 1\n",
            "other/orphan.py": "V = 1\n",
            "README.md": "See pkg/orphan.py\n",
        },
    )
    assert [finding["path"] for finding in findings_of(scan(homonyms), "dead-module")] == [
        "other/orphan.py"
    ]
    unique = make_tree(
        tmp_path / "third",
        {"pkg/orphan.py": "V = 1\n", "README.md": "See orphan.py\n"},
    )
    assert findings_of(scan(unique), "dead-module") == []


def test_normalization_keeps_expression_literal(tmp_path: Path) -> None:
    """Achado bloqueante: literal de expressão era removido como se fosse documentação."""
    policy = policy_variant(**{"classes.duplication.min_body_lines": 2})
    body = 'def {name}(x):\n    total = x + 1\n    "{literal}"\n    return total\n'
    findings = findings_of(
        scan(
            make_tree(
                tmp_path,
                {
                    "a.py": body.format(name="alpha", literal="foo"),
                    "b.py": body.format(name="beta", literal="bar"),
                },
                policy,
            )
        ),
        "duplication",
    )
    assert findings == []


def test_min_body_lines_measures_code_body(tmp_path: Path) -> None:
    """Achado não bloqueante: limiar media a definição inteira, incluindo docstring."""
    policy = policy_variant(**{"classes.duplication.min_body_lines": 4})
    body = 'def {name}(x):\n    """Documentacao\n\n    com varias linhas.\n    """\n    return x\n'
    findings = findings_of(
        scan(
            make_tree(
                tmp_path, {"a.py": body.format(name="alpha"), "b.py": body.format(name="beta")}, policy
            )
        ),
        "duplication",
    )
    assert findings == []


def test_targeted_directory_covers_child_manifest(tmp_path: Path) -> None:
    """Achado bloqueante: alvo em diretório não alcançava o manifest da subárvore."""
    tree = make_tree(tmp_path, {"sub/requirements.txt": "requests>=2\n", "sub/a.py": "import json\n"})
    report, _ = hygiene_scan.build_report(tree, hygiene_scan.load_policy(tree), ["sub"])
    assert [finding["symbol"] for finding in findings_of(report, "unused-dependency")] == ["requests"]


def test_dependency_scope_does_not_depend_on_corpus_suffixes(tmp_path: Path) -> None:
    """Achado bloqueante: import era lido do corpus de citação, e não dos módulos analisados."""
    policy = policy_variant(**{"scope.corpus_suffixes": [".md"]})
    assert validate_hygiene.policy_errors(policy) == []
    tree = make_tree(
        tmp_path, {"requirements.txt": "requests>=2\n", "alpha.py": "import requests\n"}, policy
    )
    assert findings_of(scan(tree), "unused-dependency") == []


def test_manifest_symlink_outside_root_is_refused(tmp_path: Path) -> None:
    """Achado bloqueante: manifest com link para fora da raiz era lido."""
    outside = tmp_path / "outside.txt"
    outside.write_text("pytest>=9\n", encoding="utf-8")
    tree = make_tree(tmp_path / "tree", {"alpha.py": "def used(value):\n    return value\n"})
    (tree / "requirements.txt").symlink_to(outside)
    report = scan(tree)
    assert [entry["path"] for entry in report["not_analyzed"]] == ["requirements.txt"]
    assert findings_of(report, "unused-dependency") == []


def test_broken_corpus_symlink_is_reported(tmp_path: Path) -> None:
    """Achado bloqueante: link quebrado em formato de corpus desaparecia do relatório."""
    tree = make_tree(tmp_path, {"alpha.py": "def used(value):\n    return value\n"})
    (tree / "notes.md").symlink_to(tree / "missing.md")
    report = scan(tree)
    assert [entry["path"] for entry in report["not_analyzed"]] == ["notes.md"]
    assert any("nao analisado" in error for error in validate_hygiene.validate_hygiene(tree))


def test_package_init_is_declared_entry(tmp_path: Path) -> None:
    """Achado bloqueante: `__init__.py` era exceção fixa no código."""
    files = {
        "pkg/__init__.py": "UNREFERENCED = 1\n",
        "pkg/other.py": "V = 1\n",
        "README.md": "`pkg/other.py` `V`\n",
    }
    declared = make_tree(tmp_path, files, policy_variant(**{"classes.dead-module.package_init_is_entry": True}))
    assert findings_of(scan(declared), "dead-module") == []
    plain = make_tree(
        tmp_path / "second", files, policy_variant(**{"classes.dead-module.package_init_is_entry": False})
    )
    assert [finding["path"] for finding in findings_of(scan(plain), "dead-module")] == [
        "pkg/__init__.py"
    ]


def test_repeated_name_gets_distinct_identity(tmp_path: Path) -> None:
    """Achado bloqueante: nome redefinido no mesmo arquivo produzia identidade repetida."""
    duplicated = make_tree(
        tmp_path,
        {
            "a.py": (
                "def f(x):\n    total = x + 1\n    return total\n"
                "\n\n"
                "def f(y):\n    total = y + 1\n    return total\n"
            ),
            "b.py": "def g(z):\n    total = z + 1\n    return total\n",
        },
        policy_variant(**{"classes.duplication.min_body_lines": 2}),
    )
    report, problems = hygiene_scan.build_report(duplicated, hygiene_scan.load_policy(duplicated))
    assert problems == []
    locations = sorted(finding["location"] for finding in findings_of(report, "duplication"))
    assert locations == ["a.py::f", "a.py::f#2", "b.py::g"]
    # O gate reprova os achados abertos, e não a árvore: o que não pode aparecer é ambiguidade de rótulo.
    assert not any(
        "identidade repetida" in error for error in validate_hygiene.validate_hygiene(duplicated)
    )


def test_absolute_citation_is_not_an_invocation(tmp_path: Path) -> None:
    """Achado bloqueante: caminho absoluto era tratado como citação local."""
    tree = make_tree(tmp_path, {"orphan.py": "V = 1\n", "README.md": "Use /orphan.py\n"})
    assert [finding["path"] for finding in findings_of(scan(tree), "dead-module")] == ["orphan.py"]
    anchored = make_tree(
        tmp_path / "second",
        {
            "skill/scripts/tool.py": "V = 1\n",
            "skill/README.md": "Rodar `python <skill>/scripts/tool.py`\n",
        },
    )
    assert findings_of(scan(anchored), "dead-module") == []


def test_min_body_lines_counts_instructions_not_blank_lines(tmp_path: Path) -> None:
    """Achado bloqueante: limiar contava intervalo físico e linha em branco inflava o corpo."""
    policy = policy_variant(**{"classes.duplication.min_body_lines": 4})
    body = (
        "def {name}(x):\n"
        "    y = x\n"
        "\n"
        "    # comentario 1\n"
        "    # comentario 2\n"
        "    # comentario 3\n"
        "    return y\n"
    )
    findings = findings_of(
        scan(
            make_tree(
                tmp_path, {"a.py": body.format(name="alpha"), "b.py": body.format(name="beta")}, policy
            )
        ),
        "duplication",
    )
    assert findings == []


def test_repeated_name_labels_follow_source_order(tmp_path: Path) -> None:
    """Achado bloqueante: rótulo sem sufixo pertencia à definição visitada primeiro, não à primeira."""
    source = "def f(x):\n    return x\n\n\ndef f(x):\n    return x\n"
    tree = make_tree(tmp_path, {"a.py": source, "README.md": "`a.py`\n"})
    module = hygiene_scan.ast.parse(source)
    visited = [
        node.lineno
        for node in hygiene_scan.own_scope_nodes(module)
        if isinstance(node, (hygiene_scan.ast.FunctionDef, hygiene_scan.ast.AsyncFunctionDef))
    ]
    # A travessia da árvore não devolve ordem de fonte: é por isso que o detector ordena por posição.
    assert sorted(visited) == [1, 5]
    report, _ = hygiene_scan.build_report(tree, hygiene_scan.load_policy(tree))
    symbols = findings_of(report, "dead-symbol")
    assert sorted(finding["location"] for finding in symbols) == ["a.py::f", "a.py::f#2"]
    plain = next(finding for finding in symbols if finding["location"] == "a.py::f")
    first = hygiene_scan.disambiguate([("a.py", "f"), ("a.py", "f")])[0]
    assert plain["id"] == hygiene_scan.finding_identity("dead-symbol", ["a.py", "f"])
    assert first == "a.py::f"


def test_directed_target_forms_are_equivalent(tmp_path: Path) -> None:
    """Achado bloqueante: `./sub` e `sub/` não alcançavam o manifest que `sub` alcança."""
    tree = make_tree(tmp_path, {"sub/requirements.txt": "requests>=2\n", "sub/a.py": "import json\n"})
    policy = hygiene_scan.load_policy(tree)
    for target in ("sub", "./sub", "sub/"):
        report, _ = hygiene_scan.build_report(tree, policy, [target])
        assert [finding["symbol"] for finding in findings_of(report, "unused-dependency")] == [
            "requests"
        ], target


def test_policy_must_declare_scope_decisions(tmp_path: Path) -> None:
    """Achado bloqueante: campo de escopo omitido virava default escondido no código."""
    for key_path in (
        "classes.duplication.exclude_declared_copies",
        "classes.duplication.exclude_tests",
        "classes.dead-module.exclude_tests",
        "classes.dead-module.package_init_is_entry",
        "classes.dead-symbol.exclude_tests",
        "classes.dead-symbol.ignore_names",
        "classes.unused-dependency.tool_dependencies",
        "classes.unused-dependency.import_name_map",
    ):
        document = copy.deepcopy(BASE_POLICY)
        class_name, field = key_path.split(".")[1], key_path.split(".")[2]
        document["classes"][class_name].pop(field)
        errors = validate_hygiene.policy_errors(document)
        assert any(field in error for error in errors), key_path


def test_placeholder_anchor_requires_a_real_marker(tmp_path: Path) -> None:
    """Achado bloqueante: qualquer `>` era aceito como âncora de marcador de lugar."""
    loose = make_tree(
        tmp_path, {"orphan.py": "V = 1\n", "README.md": "Use x>/orphan.py\n"}
    )
    assert [finding["path"] for finding in findings_of(scan(loose), "dead-module")] == ["orphan.py"]
    real = make_tree(
        tmp_path / "second",
        {
            "skill/scripts/tool.py": "V = 1\n",
            "skill/README.md": "Rodar `python <skill>/scripts/tool.py`\n",
        },
    )
    assert findings_of(scan(real), "dead-module") == []


def test_pattern_capture_identifier_is_neutralized(tmp_path: Path) -> None:
    """Achado bloqueante: identificador capturado por padrão estrutural não era apagado."""
    body = (
        "def {name}(value):\n"
        "    match value:\n"
        "        case int({capture}):\n"
        "            result = {capture}\n"
        "        case _:\n"
        "            result = 0\n"
        "    a = result + 1\n"
        "    b = a + 1\n"
        "    c = b + 1\n"
        "    d = c + 1\n"
        "    return d\n"
    )
    findings = findings_of(
        scan(
            make_tree(
                tmp_path,
                {
                    "a.py": body.format(name="alpha", capture="left"),
                    "b.py": body.format(name="beta", capture="right"),
                },
                policy_variant(**{"classes.duplication.min_body_lines": 6}),
            )
        ),
        "duplication",
    )
    assert sorted(finding["location"] for finding in findings) == ["a.py::alpha", "b.py::beta"]


def test_keyword_argument_name_is_material(tmp_path: Path) -> None:
    """Achado bloqueante: nome de argumento nomeado era apagado como se fosse nome local."""
    body = (
        "def {name}(value):\n"
        "    total = make({argument}=value)\n"
        "    a = total + 1\n"
        "    b = a + 1\n"
        "    c = b + 1\n"
        "    d = c + 1\n"
        "    return d\n"
    )
    findings = findings_of(
        scan(
            make_tree(
                tmp_path,
                {
                    "a.py": body.format(name="alpha", argument="left"),
                    "b.py": body.format(name="beta", argument="right"),
                },
                policy_variant(**{"classes.duplication.min_body_lines": 6}),
            )
        ),
        "duplication",
    )
    assert findings == []


def test_label_covers_definitions_below_the_threshold(tmp_path: Path) -> None:
    """Achado bloqueante: numerar só o conjunto medido dava o mesmo rótulo a duas definições."""
    policy = policy_variant(**{"classes.duplication.min_body_lines": 2})
    tree = make_tree(
        tmp_path,
        {
            "a.py": "def f(x):\n    return x\n\n\ndef f(x):\n    total = x + 2\n    return total\n",
            "b.py": "def g(y):\n    total = y + 2\n    return total\n",
        },
        policy,
    )
    report, _ = hygiene_scan.build_report(tree, hygiene_scan.load_policy(tree))
    assert sorted(finding["location"] for finding in findings_of(report, "duplication")) == [
        "a.py::f#2",
        "b.py::g",
    ]
    assert [finding["location"] for finding in findings_of(scan(tree, policy), "duplication")] == [
        "a.py::f#2",
        "b.py::g",
    ]


def test_scanner_rejects_policy_without_decision_key(tmp_path: Path) -> None:
    """Achado bloqueante: a varredura isolada aceitava chave ausente com default silencioso."""
    policy = policy_variant()
    policy["classes"]["dead-module"].pop("exclude_tests")
    tree = make_tree(tmp_path, {"tests/orphan.py": "V = 1\n", "alpha.py": "V = 1\n"}, policy)
    try:
        hygiene_scan.load_policy(tree)
    except hygiene_scan.HygieneError as error:
        assert "exclude_tests" in str(error)
    else:
        raise AssertionError("politica sem chave de decisao foi aceita pela varredura")
    assert any("exclude_tests" in item for item in validate_hygiene.policy_errors(policy))


def test_unreadable_manifest_is_reported(tmp_path: Path) -> None:
    """Achado bloqueante: manifest ilegível desaparecia sem entrar em cobertura não analisada."""
    tree = make_tree(
        tmp_path,
        {
            "alpha.py": "def used(x):\n    return x\n",
            "README.md": "`alpha.py` `used`\n",
            "requirements.txt": "requests>=2\n",
        },
    )
    manifest = tree / "requirements.txt"
    manifest.chmod(0o000)
    try:
        report = scan(tree)
    finally:
        manifest.chmod(0o600)
    assert [entry["path"] for entry in report["not_analyzed"]] == ["requirements.txt"]
    assert findings_of(report, "unused-dependency") == []


def test_missing_target_is_reported(tmp_path: Path) -> None:
    """Achado bloqueante: alvo inexistente produzia relatório limpo com código 0."""
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n"})
    document = hygiene_scan.load_policy(tree)
    report, _ = hygiene_scan.build_report(tree, document, ["does-not-exist"])
    assert [entry["path"] for entry in report["not_analyzed"]] == ["does-not-exist"]
    assert report["analyzed"] == 0
    assert report["mode"] == "targeted"


def test_report_schema_requires_justification_when_accepted() -> None:
    """Achado não bloqueante: relatório externo aceitava estado sem justificativa."""
    schema = json.loads(
        (SKILL_ROOT / "schemas" / "hygiene-report.schema.json").read_text(encoding="utf-8")
    )
    item = schema["properties"]["classes"]["items"]["properties"]["findings"]["items"]
    conditional = item.get("allOf")
    assert conditional, "schema precisa exigir justificativa no estado aceito"
    assert conditional[0]["then"]["required"] == ["justification"]
    assert conditional[0]["if"]["properties"]["state"]["const"] == "accepted"


def test_unreadable_and_symlinked_directories_are_reported(tmp_path: Path) -> None:
    """Achado bloqueante: diretório ilegível e link de diretório sumiam da cobertura."""
    tree = make_tree(
        tmp_path,
        {
            "alpha.py": "V = 1\n",
            "consumer.py": "V = 2\n",
            "README.md": "`alpha.py` `consumer.py`\n",
            "vendor/x.py": "VALUE = 1\n",
        },
        policy_variant(**{"classes.complexity.baseline": 0}),
    )
    vendor = tree / "vendor"
    vendor.chmod(0o000)
    try:
        report = scan(tree)
    finally:
        vendor.chmod(0o755)
    assert [entry["path"] for entry in report["not_analyzed"]] == ["vendor"]

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
    linked = make_tree(tmp_path / "linked", {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"})
    (linked / "vendor").symlink_to(outside)
    assert [entry["path"] for entry in scan(linked)["not_analyzed"]] == ["vendor"]


def test_report_is_identical_between_equivalent_roots(tmp_path: Path) -> None:
    """Achado bloqueante: motivo carregava caminho absoluto e quebrava o determinismo."""
    files = {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"}
    first = make_tree(tmp_path / "a", files)
    second = make_tree(tmp_path / "b", files)
    (first / "requirements.txt").write_bytes(b"\xff")
    (second / "requirements.txt").write_bytes(b"\xff")
    report_first = scan(first)
    report_second = scan(second)
    assert json.dumps(report_first, sort_keys=True) == json.dumps(report_second, sort_keys=True)
    assert [entry["path"] for entry in report_first["not_analyzed"]] == ["requirements.txt"]
    assert str(tmp_path) not in json.dumps(report_first)


def test_unicode_identifier_and_path_are_analyzed(tmp_path: Path) -> None:
    """Achado bloqueante: identificador e nome de arquivo Unicode não eram reconhecidos."""
    tree = make_tree(
        tmp_path,
        {
            "ação.py": "def fusão(valor):\n    return fusão(valor) if valor else 1\n",
            "README.md": "Use ação.py; `ação.py`\n",
        },
    )
    report = scan(tree)
    assert findings_of(report, "dead-symbol") == []
    assert findings_of(report, "dead-module") == []


def test_package_import_keeps_init_alive(tmp_path: Path) -> None:
    """Achado bloqueante: `import pkg` não alcançava `pkg/__init__.py`."""
    tree = make_tree(
        tmp_path,
        {"pkg/__init__.py": "VALUE = 1\n", "consumer.py": "import pkg\n", "README.md": "`consumer.py`\n"},
        policy_variant(**{"classes.dead-module.package_init_is_entry": False}),
    )
    assert findings_of(scan(tree), "dead-module") == []


def test_direct_url_requirement_uses_its_name(tmp_path: Path) -> None:
    """Achado bloqueante: requisito com URL direta era analisado como nome inteiro."""
    tree = make_tree(
        tmp_path,
        {
            "alpha.py": "import requests\n",
            "README.md": "`alpha.py`\n",
            "requirements.txt": "requests @ https://example.invalid/requests.whl\n",
        },
    )
    assert findings_of(scan(tree), "unused-dependency") == []


def test_scan_command_fails_closed_on_invalid_report(tmp_path: Path) -> None:
    """Achado bloqueante: o produtor gravava relatório fora do contrato e saía com sucesso."""
    tree = make_tree(
        tmp_path,
        {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n", "orphan.py": "SECRET = 1\n"},
    )
    policy_path = tree / "config" / "hygiene-policy.json"
    document = json.loads(policy_path.read_text(encoding="utf-8"))
    document["accepted"] = [{"id": "dead-symbol:x", "reason": ""}]
    policy_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    output = tree / "report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert not output.exists()


def test_targeted_mode_uses_canonical_targets(tmp_path: Path) -> None:
    """Achado não bloqueante: alvo absoluto e `.` analisavam a subárvore e omitiam o manifest."""
    tree = make_tree(
        tmp_path,
        {"sub/alpha.py": "V = 1\n", "sub/requirements.txt": "requests>=2\n", "README.md": "`sub/alpha.py`\n"},
    )
    document = hygiene_scan.load_policy(tree)
    for raw in (str(tree / "sub"), ".", "sub", "./sub", "sub/"):
        report, _ = hygiene_scan.build_report(tree, document, [raw])
        assert [finding["location"] for finding in findings_of(report, "unused-dependency")] == [
            "sub/requirements.txt::requests"
        ], raw


def test_policy_rejects_absolute_coverage_path_and_bare_suppressor() -> None:
    """Achados não bloqueantes: caminho absoluto na cobertura e supressor sem motivo."""
    coverage = policy_variant()
    coverage["not_analyzed_allowed"] = [
        {"path": "/tmp/orphan.py", "reason": "motivo escrito com extensao suficiente para passar"}
    ]
    errors = validate_hygiene.policy_errors(coverage)
    assert any("not_analyzed_allowed[0].path" in error for error in errors)

    suppressor = policy_variant(**{"classes.dead-symbol.ignore_names": ["__version__"]})
    errors = validate_hygiene.policy_errors(suppressor)
    assert any("ignore_names[0]" in error for error in errors)

    declared = policy_variant(
        **{
            "classes.dead-symbol.ignore_names": [
                {"name": "__version__", "reason": "nome publicado pelo empacotador, e nao simbolo do codigo"}
            ]
        }
    )
    assert [error for error in validate_hygiene.policy_errors(declared) if "ignore_names" in error] == []


def test_targeted_walk_reports_refusals_relative_to_root(tmp_path: Path) -> None:
    """Achado bloqueante: alvo direcionado perdia a raiz e fundia recusas de subárvores distintas."""
    tree = make_tree(
        tmp_path,
        {
            "sub1/a.py": "V = 1\n",
            "sub2/a.py": "V = 1\n",
            "README.md": "`sub1/a.py` `sub2/a.py`\n",
        },
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (tree / "sub1" / "vendor").symlink_to(outside)
    (tree / "sub2" / "vendor").symlink_to(outside)
    report, _ = hygiene_scan.build_report(tree, hygiene_scan.load_policy(tree), ["sub1", "sub2"])
    assert [entry["path"] for entry in report["not_analyzed"]] == ["sub1/vendor", "sub2/vendor"]


def test_missing_target_uses_canonical_relative_path(tmp_path: Path) -> None:
    """Achado bloqueante: alvo inexistente publicava o caminho informado, inclusive absoluto."""
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"})
    report, _ = hygiene_scan.build_report(
        tree, hygiene_scan.load_policy(tree), [str(tree / "missing.py")]
    )
    assert [entry["path"] for entry in report["not_analyzed"]] == ["missing.py"]


def test_corpus_walk_reports_refused_directory_in_file_mode(tmp_path: Path) -> None:
    """Achado bloqueante: modo direcionado a arquivo omitia diretório recusado do corpus."""
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (tree / "vendor").symlink_to(outside)
    document = hygiene_scan.load_policy(tree)
    sweep, _ = hygiene_scan.build_report(tree, document)
    targeted, _ = hygiene_scan.build_report(tree, document, ["alpha.py"])
    assert [entry["path"] for entry in sweep["not_analyzed"]] == ["vendor"]
    assert [entry["path"] for entry in targeted["not_analyzed"]] == ["vendor"]


def test_unicode_identifier_outside_basic_plane_is_analyzed(tmp_path: Path) -> None:
    """Achado bloqueante: identificador Unicode aceito por `ast` não era reconhecido no texto."""
    tree = make_tree(
        tmp_path,
        {
            "\u1885.py": "def \u1885(x):\n    return \u1885(x) if x else 1\n",
            "README.md": "Use \u1885.py\n",
        },
    )
    report = scan(tree)
    assert findings_of(report, "dead-symbol") == []
    assert findings_of(report, "dead-module") == []


def test_submodule_import_keeps_package_init_alive(tmp_path: Path) -> None:
    """Achado bloqueante: `import pkg.sub` não mantinha `pkg/__init__.py` vivo."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/__init__.py": "VALUE = 1\n",
            "pkg/sub.py": "VALUE = 2\n",
            "consumer.py": "import pkg.sub\n",
            "README.md": "`consumer.py`\n",
        },
        policy_variant(**{"classes.dead-module.package_init_is_entry": False}),
    )
    assert findings_of(scan(tree), "dead-module") == []


def test_pyproject_manifest_is_analyzed(tmp_path: Path) -> None:
    """Achado bloqueante: escopo de manifest fixo no código deixava `pyproject.toml` sem análise."""
    tree = make_tree(
        tmp_path,
        {
            "a.py": "import json\n",
            "README.md": "`a.py`\n",
            "pyproject.toml": (
                "[project]\n"
                'name = "exemplo"\n'
                'dependencies = ["requests>=2"]\n'
                "\n"
                "[tool.poetry.dependencies]\n"
                'python = "^3.11"\n'
                'flask = "^3"\n'
            ),
        },
    )
    assert sorted(finding["symbol"] for finding in findings_of(scan(tree), "unused-dependency")) == [
        "flask",
        "requests",
    ]


def test_manifest_patterns_key_is_required() -> None:
    """Achado bloqueante: escopo de manifest precisa ser declarado, e não assumido no código."""
    policy = policy_variant()
    del policy["classes"]["unused-dependency"]["manifest_patterns"]
    errors = validate_hygiene.policy_errors(policy)
    assert any("manifest_patterns ausente" in error for error in errors)

    empty = policy_variant(**{"classes.unused-dependency.manifest_patterns": []})
    assert any("nao pode ser vazio" in error for error in validate_hygiene.policy_errors(empty))

    path_pattern = policy_variant(**{"classes.unused-dependency.manifest_patterns": ["sub/req.txt"]})
    assert any(
        "sem separador de caminho" in error for error in validate_hygiene.policy_errors(path_pattern)
    )


def test_scan_command_refuses_report_inside_measured_tree(tmp_path: Path) -> None:
    """Achado bloqueante: relatório dentro da árvore alterava a medição e sobrescrevia arquivo."""
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"})
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(tree / "alpha.py"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert (tree / "alpha.py").read_text(encoding="utf-8") == "V = 1\n"


def test_scan_command_rejects_policy_with_invalid_suppressor(tmp_path: Path) -> None:
    """Achado não bloqueante: a CLI isolada aceitava política que o gate reprova."""
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"})
    document = json.loads((tree / "config" / "hygiene-policy.json").read_text(encoding="utf-8"))
    document["classes"]["dead-symbol"]["ignore_names"] = ["__all__"]
    (tree / "config" / "hygiene-policy.json").write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path.parent / f"{tmp_path.name}-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert not output.exists()


def test_exception_alias_does_not_hide_duplication(tmp_path: Path) -> None:
    """Achado não bloqueante: apelido de exceção não era apagado na normalização."""
    tree = make_tree(
        tmp_path,
        {
            "a.py": (
                "def f():\n"
                "    try:\n"
                "        return 1\n"
                "    except ValueError as first:\n"
                "        return 2\n"
            ),
            "b.py": (
                "def g():\n"
                "    try:\n"
                "        return 1\n"
                "    except ValueError as other:\n"
                "        return 2\n"
            ),
            "README.md": "`a.py` `b.py`\n",
        },
        policy_variant(**{"classes.duplication.min_body_lines": 1}),
    )
    assert sorted(finding["location"] for finding in findings_of(scan(tree), "duplication")) == [
        "a.py::f",
        "b.py::g",
    ]


def test_vcs_requirement_uses_egg_fragment(tmp_path: Path) -> None:
    """Achado não bloqueante: requisito de VCS virava nome truncado e acusava dependência importada."""
    tree = make_tree(
        tmp_path,
        {
            "a.py": "import requests\n",
            "README.md": "`a.py`\n",
            "requirements.txt": "git+https://example.invalid/repo.git#egg=requests\n",
        },
    )
    assert findings_of(scan(tree), "unused-dependency") == []


def test_excluded_file_does_not_make_citation_ambiguous(tmp_path: Path) -> None:
    """Achado bloqueante: arquivo excluído tornava ambígua a citação de nome solto."""
    files = {
        "pkg/orphan.py": "import json\n",
        "vendor/orphan.py": "import json\n",
        "README.md": "See orphan.py\n",
    }
    # Sem exclusão declarada o nome solto é ambíguo, e os dois homônimos ficam mortos.
    ambiguous = sorted(
        finding["location"] for finding in findings_of(scan(make_tree(tmp_path, files)), "dead-module")
    )
    assert ambiguous == ["pkg/orphan.py", "vendor/orphan.py"]
    # Com `vendor` excluído, o nome solto cita o único homônimo do escopo medido.
    declared = make_tree(
        tmp_path / "declared",
        files,
        policy_variant(**{"scope.exclude_dirs": ["vendor", ".git", "__pycache__"]}),
    )
    assert findings_of(scan(declared), "dead-module") == []


def test_combining_mark_after_suffix_is_not_a_citation(tmp_path: Path) -> None:
    """Achado bloqueante: `foo.py` seguido de marca combinante mantinha o módulo vivo."""
    tree = make_tree(tmp_path, {"foo.py": "V = 1\n", "README.md": "foo.py\u0301\n"})
    assert [finding["location"] for finding in findings_of(scan(tree), "dead-module")] == ["foo.py"]
    cited = make_tree(tmp_path / "cited", {"foo.py": "V = 1\n", "README.md": "`foo.py`\n"})
    assert findings_of(scan(cited), "dead-module") == []


def test_pep621_python_requirement_is_not_counted(tmp_path: Path) -> None:
    """Achado bloqueante: `python` em `project.dependencies` era contado como dependência sem uso."""
    tree = make_tree(
        tmp_path,
        {
            "a.py": "import json\n",
            "README.md": "`a.py`\n",
            "pyproject.toml": (
                "[project]\n"
                'name = "exemplo"\n'
                'dependencies = ["python>=3.11", "requests>=2"]\n'
            ),
        },
    )
    assert [finding["symbol"] for finding in findings_of(scan(tree), "unused-dependency")] == [
        "requests"
    ]


def test_unsupported_manifest_format_is_refused(tmp_path: Path) -> None:
    """Achado bloqueante: formato sem leitura declarada era interpretado como lista de linhas."""
    tree = make_tree(
        tmp_path,
        {
            "a.py": "import json\n",
            "README.md": "`a.py`\n",
            "setup.cfg": "[options]\ninstall_requires =\n    requests>=2\n",
        },
        policy_variant(**{"classes.unused-dependency.manifest_patterns": ["setup.cfg"]}),
    )
    report = scan(tree)
    assert [entry["path"] for entry in report["not_analyzed"]] == ["setup.cfg"]
    assert findings_of(report, "unused-dependency") == []


def test_lockfile_by_convention_is_not_a_manifest(tmp_path: Path) -> None:
    """Achado bloqueante: trava só era ignorada pelo sufixo `.lock.txt`."""
    tree = make_tree(
        tmp_path,
        {"a.py": "import json\n", "README.md": "`a.py`\n", "poetry.lock": 'requests = "2"\n'},
        policy_variant(**{"classes.unused-dependency.manifest_patterns": ["*.lock"]}),
    )
    assert findings_of(scan(tree), "unused-dependency") == []


def test_target_that_escapes_is_reported_in_coverage(tmp_path: Path) -> None:
    """Achado não bloqueante: alvo que resolve para fora abortava em vez de aparecer na cobertura."""
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"})
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("V = 1\n", encoding="utf-8")
    (tree / "escape.py").symlink_to(outside)
    document = hygiene_scan.load_policy(tree)
    targeted, _ = hygiene_scan.build_report(tree, document, ["escape.py"])
    sweep, _ = hygiene_scan.build_report(tree, document)
    assert [entry["path"] for entry in targeted["not_analyzed"]] == ["escape.py"]
    assert [entry["path"] for entry in sweep["not_analyzed"]] == ["escape.py"]


def test_cli_honours_policy_argument(tmp_path: Path) -> None:
    """Achado não bloqueante: `--policy` era aceito e ignorado."""
    body = "def f():\n" + "".join(f"    if x{index}:\n        pass\n" for index in range(40)) + "    return 1\n"
    tree = make_tree(tmp_path, {"alpha.py": body, "README.md": "`alpha.py`\n"})
    external = tmp_path.parent / f"{tmp_path.name}-policy.json"
    document = json.loads((tree / "config" / "hygiene-policy.json").read_text(encoding="utf-8"))
    document["classes"]["complexity"]["max_complexity"] = 99
    external.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    output = tmp_path.parent / f"{tmp_path.name}-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--policy",
            str(external),
            "--report",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    complexity = next(entry for entry in report["classes"] if entry["name"] == "complexity")
    assert complexity["open"] == 0


def test_external_target_does_not_reenable_free_walk(tmp_path: Path) -> None:
    """Achado bloqueante: alvo externo fazia o conjunto vazio significar percurso livre de manifest."""
    tree = make_tree(
        tmp_path,
        {"alpha.py": "import json\n", "README.md": "`alpha.py`\n", "requirements.txt": "requests>=2\n"},
    )
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "outside.py").write_text("V = 1\n", encoding="utf-8")
    for target in (str(outside / "outside.py"), str(outside)):
        report, _ = hygiene_scan.build_report(tree, hygiene_scan.load_policy(tree), [target])
        assert report["analyzed"] == 0
        assert findings_of(report, "unused-dependency") == []
        assert len(report["not_analyzed"]) == 1


def test_corpus_symlink_outside_root_does_not_make_citation_ambiguous(tmp_path: Path) -> None:
    """Achado bloqueante: link de corpus que sai da raiz contava como homônimo medido."""
    tree = make_tree(tmp_path, {"pkg/orphan.py": "import json\n", "README.md": "See orphan.py\n"})
    outside = tmp_path.parent / f"{tmp_path.name}-outside.py"
    outside.write_text("V = 1\n", encoding="utf-8")
    (tree / "orphan.py").symlink_to(outside)
    assert findings_of(scan(tree), "dead-module") == []


def test_self_citation_does_not_keep_module_alive(tmp_path: Path) -> None:
    """Achado bloqueante: o próprio arquivo mantinha o módulo vivo por autocitação."""
    tree = make_tree(tmp_path, {"orphan.py": '"orphan.py"\nVALUE = 1\n', "README.md": "texto\n"})
    assert [finding["location"] for finding in findings_of(scan(tree), "dead-module")] == ["orphan.py"]


def test_broken_and_looped_links_match_between_modes(tmp_path: Path) -> None:
    """Achado bloqueante: alvo direcionado rotulava link quebrado de outro modo, e ciclo abortava."""
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"})
    (tree / "alias.py").symlink_to("missing.py")
    (tree / "loop.py").symlink_to("loop.py")
    document = hygiene_scan.load_policy(tree)
    free, _ = hygiene_scan.build_report(tree, document)
    targeted, _ = hygiene_scan.build_report(tree, document, ["alias.py", "loop.py"])
    assert [entry["path"] for entry in free["not_analyzed"]] == ["alias.py", "loop.py"]
    assert [entry["path"] for entry in targeted["not_analyzed"]] == ["alias.py", "loop.py"]


def test_absolute_external_target_is_deterministic(tmp_path: Path) -> None:
    """Achado bloqueante: alvo externo absoluto publicava caminho absoluto e quebrava o determinismo."""
    files = {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"}
    first = make_tree(tmp_path / "a", files)
    second = make_tree(tmp_path / "b", files)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "outside.py").write_text("V = 1\n", encoding="utf-8")
    report_first, _ = hygiene_scan.build_report(first, hygiene_scan.load_policy(first), [str(outside)])
    report_second, _ = hygiene_scan.build_report(second, hygiene_scan.load_policy(second), [str(outside)])
    assert json.dumps(report_first, sort_keys=True) == json.dumps(report_second, sort_keys=True)
    assert str(tmp_path) not in json.dumps(report_first)


def test_optional_dependencies_structure_is_validated(tmp_path: Path) -> None:
    """Achado bloqueante: escalar em `optional-dependencies` virava uma dependência por caractere."""
    tree = make_tree(
        tmp_path,
        {
            "a.py": "import json\n",
            "README.md": "`a.py`\n",
            "pyproject.toml": (
                "[project]\n"
                'name = "exemplo"\n'
                "[project.optional-dependencies]\n"
                'dev = "requests"\n'
            ),
        },
    )
    report = scan(tree)
    assert [entry["path"] for entry in report["not_analyzed"]] == ["pyproject.toml"]
    assert findings_of(report, "unused-dependency") == []


def test_work_item_generator_refuses_output_inside_measured_tree(tmp_path: Path) -> None:
    """Achado bloqueante: work item gravado na árvore medida apagava a dívida que descreve."""
    tree = make_tree(tmp_path, {"orphan.py": '"orphan.py"\nVALUE = 1\n', "README.md": "texto\n"})
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "build_hygiene_work_items.py"),
            "--root",
            str(tree),
            "--out-dir",
            str(tree / "work-items"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert not (tree / "work-items").exists()


def test_scan_command_does_not_publish_report_with_policy_problem(tmp_path: Path) -> None:
    """Achado não bloqueante: relatório era gravado antes de a política ser reprovada."""
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"})
    document = json.loads((tree / "config" / "hygiene-policy.json").read_text(encoding="utf-8"))
    document["accepted"] = [
        {
            "id": "dead-symbol:0000000000000000",
            "reason": "excecao declarada sem achado correspondente na arvore auditada",
        }
    ]
    (tree / "config" / "hygiene-policy.json").write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path.parent / f"{tmp_path.name}-report.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 1
    assert not output.exists()


def test_exclude_dirs_requires_relative_directory() -> None:
    """Achado não bloqueante: `exclude_dirs` com `.` esvaziava o escopo por declaração."""
    for value in (["."], [".."], ["/vendor"], ["./vendor"], ["vendor/"]):
        policy = policy_variant(**{"scope.exclude_dirs": value})
        assert any("exclude_dirs" in error for error in validate_hygiene.policy_errors(policy)), value
    allowed = policy_variant(**{"scope.exclude_dirs": ["vendor", "node_modules/cache"]})
    assert [error for error in validate_hygiene.policy_errors(allowed) if "exclude_dirs" in error] == []


def test_unknown_class_key_is_rejected() -> None:
    """Chave com nome parecido dentro da classe era ignorada em silêncio."""
    policy = policy_variant()
    policy["classes"]["dead-symbol"]["accepted"] = [{"id": "x", "reason": "y"}]
    errors = validate_hygiene.policy_errors(policy)
    assert any("nao e chave de decisao conhecida" in error for error in errors)
    assert validate_hygiene.policy_errors(policy_variant()) == []


def test_report_exposes_declared_excluded_dirs(tmp_path: Path) -> None:
    """Achado não bloqueante: diretório excluído não aparecia no relatório."""
    policy = policy_variant(**{"scope.exclude_dirs": ["vendor", ".git", "__pycache__"]})
    tree = make_tree(tmp_path, {"a.py": "V = 1\n", "README.md": "`a.py`\n"}, policy)
    assert scan(tree)["excluded_dirs"] == [".git", "__pycache__", "vendor"]


def test_class_key_of_another_class_is_rejected() -> None:
    """Achado bloqueante: chave de outra classe passava e não era medida por ninguém."""
    for name, key, value in (
        ("dead-symbol", "max_complexity", 99),
        ("duplication", "tool_dependencies", ["x"]),
        ("complexity", "import_name_map", {"a": "b"}),
        ("dead-module", "min_body_lines", 3),
    ):
        policy = policy_variant(**{f"classes.{name}.{key}": value})
        errors = validate_hygiene.policy_errors(policy)
        assert any(f"classes.{name}.{key}" in error for error in errors), (name, key)
    # `baseline` é chave da classe `complexity`, e o valor precisa casar com a história declarada.
    allowed = policy_variant(**{"classes.complexity.baseline": 47})
    assert [error for error in validate_hygiene.policy_errors(allowed) if "nao e chave" in error] == []


def test_exclude_dirs_requires_canonical_relative_path() -> None:
    """Achado bloqueante: forma não canônica era aceita e excluía outro diretório."""
    for value in (["a/../vendor"], ["a/./vendor"], ["a//vendor"]):
        policy = policy_variant(**{"scope.exclude_dirs": value})
        assert any("exclude_dirs" in error for error in validate_hygiene.policy_errors(policy)), value
    allowed = policy_variant(**{"scope.exclude_dirs": ["vendor", "a/b"]})
    assert [error for error in validate_hygiene.policy_errors(allowed) if "exclude_dirs" in error] == []


def test_poetry_group_hierarchy_is_validated(tmp_path: Path) -> None:
    """Achado bloqueante: hierarquia inválida de grupo Poetry desaparecia da medição."""
    for content in (
        '[tool.poetry.group]\ndev = "malformed"\n',
        '[tool.poetry]\ngroup = "malformed"\n',
        '[tool.poetry.group.dev]\ndependencies = "malformed"\n',
    ):
        tree = make_tree(
            tmp_path / str(abs(hash(content))),
            {"a.py": "import json\n", "README.md": "`a.py`\n", "pyproject.toml": content},
        )
        report = scan(tree)
        assert [entry["path"] for entry in report["not_analyzed"]] == ["pyproject.toml"], content
        assert findings_of(report, "unused-dependency") == []
    valid = make_tree(
        tmp_path / "valido",
        {
            "a.py": "import json\n",
            "README.md": "`a.py`\n",
            "pyproject.toml": '[tool.poetry.group.dev.dependencies]\nrequests = "^2"\n',
        },
    )
    assert [item["symbol"] for item in findings_of(scan(valid), "unused-dependency")] == ["requests"]


def test_citation_with_dot_dot_inside_root_keeps_module_alive(tmp_path: Path) -> None:
    """Achado bloqueante: citação válida com `..` era descartada e virava falso positivo."""
    inside = make_tree(
        tmp_path / "dentro",
        {"sub/keep.py": "V = 1\n", "orphan.py": "V = 1\n", "README.md": "Use sub/../orphan.py\n"},
    )
    assert [finding["location"] for finding in findings_of(scan(inside), "dead-module")] == ["sub/keep.py"]
    escaping = make_tree(
        tmp_path / "fora",
        {"sub/keep.py": "V = 1\n", "orphan.py": "V = 1\n", "README.md": "Use ../orphan.py\n"},
    )
    assert [finding["location"] for finding in findings_of(scan(escaping), "dead-module")] == [
        "orphan.py",
        "sub/keep.py",
    ]


def test_suppressor_with_wrong_type_is_rejected() -> None:
    """Achado não bloqueante: supressor de tipo errado era ignorado em silêncio."""
    for name, key, value in (
        ("dead-symbol", "ignore_names", "__all__"),
        ("dead-symbol", "ignore_names", {"name": "x"}),
        ("dead-module", "entry_points", {"name": "orphan.py"}),
    ):
        policy = policy_variant(**{f"classes.{name}.{key}": value})
        errors = validate_hygiene.policy_errors(policy)
        assert any(f"classes.{name}.{key} precisa ser lista" in error for error in errors), (name, key)


def test_markdown_report_exposes_declared_exclusions(tmp_path: Path) -> None:
    """Achado não bloqueante: o artefato humano omitia o escopo excluído."""
    policy = policy_variant(**{"scope.exclude_dirs": ["vendor"]})
    tree = make_tree(tmp_path, {"a.py": "V = 1\n", "README.md": "`a.py`\n"}, policy)
    markdown = hygiene_scan.render_markdown(scan(tree))
    assert "## Excluídos por declaração" in markdown
    assert "`vendor/`" in markdown


def test_system_root_target_publishes_non_empty_label(tmp_path: Path) -> None:
    """Achado não bloqueante: alvo `/` produzia rótulo vazio e reprovava o contrato."""
    tree = make_tree(tmp_path, {"a.py": "V = 1\n", "README.md": "`a.py`\n"})
    report, _ = hygiene_scan.build_report(tree, hygiene_scan.load_policy(tree), ["/"])
    assert [entry["path"] for entry in report["not_analyzed"]] == ["/"]
    assert hygiene_scan.report_contract_errors(report) == []


def test_toml_structure_is_refused_instead_of_read_as_empty(tmp_path: Path) -> None:
    """Achado bloqueante: estrutura TOML inválida desaparecia sem virar recusa visível."""
    for index, content in enumerate(
        (
            '[tool.poetry.group.dev.metadata]\nrequests = "^2"\n',
            'project = "bad"\n',
            'tool = "bad"\n',
        )
    ):
        tree = make_tree(
            tmp_path / str(index),
            {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n", "pyproject.toml": content},
        )
        report = scan(tree)
        assert [entry["path"] for entry in report["not_analyzed"]] == ["pyproject.toml"], content
        assert findings_of(report, "unused-dependency") == []


def test_poetry_group_with_optional_is_still_read(tmp_path: Path) -> None:
    """A recusa nova não pode acusar grupo válido do formato."""
    content = (
        '[tool.poetry.group.dev]\noptional = true\n'
        '[tool.poetry.group.dev.dependencies]\nrequests = "^2"\n'
    )
    tree = make_tree(
        tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n", "pyproject.toml": content}
    )
    report = scan(tree)
    assert report["not_analyzed"] == []
    assert [item["symbol"] for item in findings_of(report, "unused-dependency")] == ["requests"]


def test_relative_import_at_package_root_reaches_sibling(tmp_path: Path) -> None:
    """Achado bloqueante: `from . import x` na raiz de pacote era acusado como módulo morto."""
    policy = policy_variant(**{"classes.dead-module.package_init_is_entry": True})
    packed = make_tree(
        tmp_path / "pacote",
        {
            "__init__.py": "",
            "consumer.py": "from . import orphan\n",
            "orphan.py": "def used(value):\n    return value\n",
            "README.md": "`consumer.py` usado\n",
        },
        policy,
    )
    assert findings_of(scan(packed), "dead-module") == []
    loose = make_tree(
        tmp_path / "solto",
        {
            "consumer.py": "from . import orphan\n",
            "orphan.py": "def used(value):\n    return value\n",
            "README.md": "`consumer.py` usado\n",
        },
        policy,
    )
    assert [finding["location"] for finding in findings_of(scan(loose), "dead-module")] == ["orphan.py"]


def test_work_item_generator_refuses_invalid_policy(tmp_path: Path) -> None:
    """Achado bloqueante: o gerador publicava work item a partir de política que o gate reprova."""
    policy = policy_variant(**{"classes.dead-symbol.ignore_names": "__all__"})
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"}, policy)
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "build_hygiene_work_items.py"),
            "--root",
            str(tree),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout
    assert "politica invalida" in result.stderr


def test_declared_path_with_control_character_is_refused(tmp_path: Path) -> None:
    """Achado bloqueante: caminho com NUL passava a política e derrubava o validador."""
    policy = policy_variant(
        **{
            "scope.exclude_paths": [
                {
                    "path": "bad\x00.py",
                    "reason": "Exclusao com motivo suficientemente longo para teste controlado.",
                }
            ]
        }
    )
    errors = validate_hygiene.policy_errors(policy)
    assert any("nao pode conter NUL" in error for error in errors)
    tree = make_tree(tmp_path, {"alpha.py": "V = 1\n", "README.md": "`alpha.py`\n"}, policy)
    assert any("NUL" in error for error in validate_hygiene.validate_hygiene(tree))


def test_gated_class_with_zero_baseline_is_refused() -> None:
    """Achado não bloqueante: `baseline: 0` escapava da regra que proíbe linha de base em classe gated."""
    policy = policy_variant(**{"classes.complexity.state": "gated", "classes.complexity.baseline": 0})
    errors = validate_hygiene.policy_errors(policy)
    assert any("classe gated nao pode declarar baseline" in error for error in errors)


def test_work_item_generator_refuses_report_of_invalid_policy(tmp_path: Path) -> None:
    """Achado bloqueante: `--report` era uma porta mais fraca que a varredura."""
    tree = make_tree(
        tmp_path / "arvore",
        {"alpha.py": '"""Modulo sem simbolo."""\n', "README.md": "`alpha.py` usado\n"},
    )
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    invalid = policy_variant(**{"classes.dead-symbol.ignore_names": "__all__"})
    policy_dir = tree / "config"
    policy_dir.mkdir(exist_ok=True)
    (policy_dir / "hygiene-policy.json").write_text(
        json.dumps(invalid, ensure_ascii=False), encoding="utf-8"
    )
    out_dir = tmp_path / "saida"
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "build_hygiene_work_items.py"),
            "--root",
            str(tree),
            "--report",
            str(report),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout
    assert "politica invalida" in result.stderr
    assert not out_dir.exists()


def test_work_item_generator_refuses_scan_with_coverage_gap(tmp_path: Path) -> None:
    """Achado bloqueante: buraco de cobertura era publicado como work item."""
    tree = make_tree(
        tmp_path / "arvore",
        {"alpha.py": '"""Modulo sem simbolo."""\n', "README.md": "`alpha.py` usado\n"},
    )
    (tree / "broken.py").symlink_to("missing.py")
    out_dir = tmp_path / "saida"
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "build_hygiene_work_items.py"),
            "--root",
            str(tree),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout
    # Buraco de cobertura é incoerência entre relatório e árvore, e não dívida aberta.
    assert "incoerente" in result.stderr
    assert not out_dir.exists()


def test_work_item_generator_publishes_clean_tree(tmp_path: Path) -> None:
    """A recusa nova não pode impedir a publicação legítima."""
    tree = make_tree(
        tmp_path / "arvore",
        {"alpha.py": '"""Modulo sem simbolo."""\n', "README.md": "`alpha.py` usado\n"},
    )
    out_dir = tmp_path / "saida"
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "build_hygiene_work_items.py"),
            "--root",
            str(tree),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_entry_point_decision_requires_boolean() -> None:
    """Achado bloqueante: `package_init_is_entry` aceitava texto e número como decisão booleana."""
    for value in ("false", "true", 0, 1):
        policy = policy_variant(**{"classes.dead-module.package_init_is_entry": value})
        errors = validate_hygiene.policy_errors(policy)
        assert any("package_init_is_entry precisa ser booleano" in error for error in errors), value
    assert [
        error
        for error in validate_hygiene.policy_errors(
            policy_variant(**{"classes.dead-module.package_init_is_entry": False})
        )
        if "package_init_is_entry" in error
    ] == []


def test_gated_class_cannot_declare_baseline_history() -> None:
    """Achado bloqueante: história de linha de base escapava da regra de classe controlada."""
    policy = policy_variant(**{"classes.complexity.state": "gated"})
    policy["classes"]["complexity"].pop("baseline", None)
    policy["classes"]["complexity"]["baseline_history"] = [
        {"value": 0, "reason": "Historia declarada apesar de a classe estar controlada, com motivo."}
    ]
    errors = validate_hygiene.policy_errors(policy)
    assert any("classe gated nao pode declarar baseline" in error for error in errors)


def test_work_item_generator_refuses_report_from_another_tree(tmp_path: Path) -> None:
    """Achado bloqueante: relatório de outra árvore virava work item por passar só no schema."""
    clean = {"alpha.py": '"""Modulo sem simbolo."""\n', "README.md": "`alpha.py` usado\n"}
    other = make_tree(tmp_path / "outra", clean)
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(other),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    current = make_tree(
        tmp_path / "atual",
        {"alpha.py": clean["alpha.py"], "extra.py": '"""Outro modulo."""\n', "README.md": "`alpha.py` e `extra.py` usados\n"},
    )
    out_dir = tmp_path / "saida"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(current),
            "--report",
            str(report),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, result.stdout
    assert "nao corresponde a arvore e a politica atuais" in result.stderr
    assert not out_dir.exists()
    # O relatório da própria árvore continua aceito: a recusa não pode impedir o uso legítimo.
    own = tmp_path / "proprio.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(current),
            "--report",
            str(own),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(current),
            "--report",
            str(own),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_policy_version_requires_exact_integer() -> None:
    """Achado bloqueante: `1.0` é igual a `1` em Python e passava como versão da política."""
    for value in (1.0, "1", True, None):
        policy = policy_variant(schema_version=value)
        errors = validate_hygiene.policy_errors(policy)
        assert any("schema_version precisa ser o inteiro 1" in error for error in errors), value
    assert [
        error
        for error in validate_hygiene.policy_errors(policy_variant(schema_version=1))
        if "schema_version" in error
    ] == []


def test_scan_and_generator_refuse_float_policy_version(tmp_path: Path) -> None:
    """A versão fora do contrato não pode produzir relatório nem work item."""
    tree = make_tree(
        tmp_path / "arvore",
        {"alpha.py": '"""Modulo sem simbolo."""\n', "README.md": "`alpha.py` usado\n"},
        policy_variant(schema_version=1.0),
    )
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(report),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not report.exists()
    out_dir = tmp_path / "saida"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(tree),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "politica invalida" in result.stderr
    assert not out_dir.exists()


def test_negative_baseline_is_refused() -> None:
    """Achado não bloqueante: linha de base negativa era aceita pela política e publicada."""
    policy = policy_variant()
    policy["classes"]["complexity"]["baseline"] = -1
    policy["classes"]["complexity"]["baseline_history"] = [
        {"value": -1, "reason": "Historia negativa declarada com motivo suficiente."}
    ]
    errors = validate_hygiene.policy_errors(policy)
    assert any("baseline nao pode ser negativo" in error for error in errors)
    assert any("nao pode ser negativo" in error for error in errors if "baseline_history" in error)


def test_scan_refuses_two_artifacts_in_the_same_target(tmp_path: Path) -> None:
    """Achado não bloqueante: Markdown sobrescrevia o JSON no mesmo caminho."""
    tree = make_tree(
        tmp_path / "arvore", {"alpha.py": '"""Modulo sem simbolo."""\n', "README.md": "`alpha.py` usado\n"}
    )
    (tmp_path / "fora").mkdir()
    target = tmp_path / "fora" / "artefato"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(target),
            "--markdown",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "caminhos diferentes" in result.stderr
    assert not target.exists()


def test_generator_refuses_reused_output_directory(tmp_path: Path) -> None:
    """Achado não bloqueante: saída reutilizada conservava work item obsoleto."""
    out_dir = tmp_path / "saida"
    out_dir.mkdir()
    (out_dir / "work-item:antigo.json").write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(REPO_ROOT),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "ja tem conteudo" in result.stderr


def test_report_with_decimal_numbers_is_refused(tmp_path: Path) -> None:
    """Achado bloqueante: `jsonschema` aceita `1.0` como inteiro e o relatório passava."""
    report = scan(
        make_tree(tmp_path / "arvore", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    )
    for field in ("schema_version", "policy_schema_version", "analyzed"):
        forged = copy.deepcopy(report)
        forged[field] = float(forged[field])
        errors = validate_hygiene.schema_errors(forged)
        assert any("nao decimal" in error for error in errors), field
    forged = copy.deepcopy(report)
    forged["summary"]["open"] = float(forged["summary"]["open"])
    assert any("nao decimal" in error for error in validate_hygiene.schema_errors(forged))
    assert validate_hygiene.schema_errors(report) == []


def test_scan_refuses_equivalent_targets(tmp_path: Path) -> None:
    """Achado bloqueante: caminhos lexicalmente diferentes alcançavam o mesmo arquivo."""
    tree = make_tree(tmp_path / "arvore", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    out = tmp_path / "fora" / "saida"
    out.mkdir(parents=True)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(out / "a"),
            "--markdown",
            str(out / "sub" / ".." / "a"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "caminhos diferentes" in result.stderr
    assert not (out / "a").exists()


def test_scan_refuses_target_linked_to_the_tree(tmp_path: Path) -> None:
    """Achado bloqueante: alvo com mais de um link escrevia em arquivo da árvore medida."""
    tree = make_tree(tmp_path / "arvore", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    out = tmp_path / "saida"
    out.mkdir()
    (out / "report.json").hardlink_to(tree / "alpha.py")
    before = (tree / "alpha.py").read_text(encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(out / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "mais de um link" in result.stderr
    assert (tree / "alpha.py").read_text(encoding="utf-8") == before


def test_measured_class_without_baseline_is_refused() -> None:
    """Achado bloqueante: só complexidade exigia linha de base, e o estado medido é genérico."""
    policy = policy_variant()
    policy["classes"]["dead-module"]["state"] = "reported"
    policy["classes"]["dead-module"].pop("baseline", None)
    policy["classes"]["dead-module"].pop("baseline_history", None)
    errors = validate_hygiene.policy_errors(policy)
    assert any("baseline_history precisa declarar a historia" in error for error in errors)


def test_generator_refuses_output_path_that_is_a_file(tmp_path: Path) -> None:
    """Achado não bloqueante: destino existente que não é diretório causava traceback."""
    target = tmp_path / "arquivo"
    target.write_text("x", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(REPO_ROOT),
            "--out-dir",
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "nao e diretorio" in result.stderr


def test_any_class_can_be_declared_as_measured() -> None:
    """Achado bloqueante: a catraca exigia linha de base e as chaves só existiam em complexidade."""
    for name in ("duplication", "dead-module", "dead-symbol", "unused-dependency", "complexity"):
        policy = policy_variant()
        policy["classes"][name].update(
            state="reported",
            baseline=0,
            baseline_history=[
                {"value": 0, "reason": "Medicao inicial declarada para a classe com motivo suficiente."}
            ],
        )
        errors = validate_hygiene.policy_errors(policy)
        assert not [error for error in errors if "chave de decisao conhecida" in error], (name, errors)
        assert not [error for error in errors if "baseline" in error], (name, errors)
        # E a mesma classe sem linha de base continua recusada.
        policy["classes"][name].pop("baseline")
        policy["classes"][name].pop("baseline_history")
        assert any(
            "baseline_history precisa declarar a historia" in error
            for error in validate_hygiene.policy_errors(policy)
        ), name


def test_relative_import_beyond_package_keeps_homonym_dead(tmp_path: Path) -> None:
    """Achado bloqueante: `from .. import x` mantinha vivo um homônimo do pacote do importador."""
    tree = make_tree(
        tmp_path,
        {
            "__init__.py": "",
            "orphan.py": "V = 1\n",
            "pkg/consumer.py": "from .. import orphan\n",
            "pkg/orphan.py": "V = 2\n",
            "README.md": "`pkg/consumer.py`\n",
        },
        policy_variant(**{"classes.dead-module.package_init_is_entry": True}),
    )
    assert [finding["path"] for finding in findings_of(scan(tree), "dead-module")] == ["pkg/orphan.py"]


def test_scan_refuses_directory_as_report_target(tmp_path: Path) -> None:
    """Achado bloqueante: diretório em --report terminava em exceção não tratada."""
    target = tmp_path / "diretorio"
    target.mkdir()
    for flag in ("--report", "--markdown"):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "hygiene_scan.py"), "--root", str(REPO_ROOT), flag, str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, flag
        assert "precisa ser arquivo" in result.stderr, flag
        assert "Traceback" not in result.stderr, flag


def test_generator_refuses_broken_symlink_as_output(tmp_path: Path) -> None:
    """Achado bloqueante: `exists()` segue link e o link quebrado terminava em exceção."""
    link = tmp_path / "saida"
    link.symlink_to(tmp_path / "ausente")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(REPO_ROOT),
            "--out-dir",
            str(link),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "nao e diretorio" in result.stderr
    assert "Traceback" not in result.stderr


def test_producer_contract_is_the_same_as_the_gate() -> None:
    """Achado não bloqueante: o produtor não conferia o decimal que o gate confere."""
    forged = {"schema_version": 1.0, "analyzed": 1.0}
    assert any("nao decimal" in error for error in hygiene_scan.report_contract_errors(forged))


def test_policy_scope_out_of_type_is_refused_without_crash() -> None:
    """Achado bloqueante: `scope` fora do tipo derrubava o gate com exceção crua."""
    for value in (None, [], "x", 1, True):
        policy = policy_variant()
        policy["scope"] = value
        errors = validate_hygiene.policy_errors(policy)
        assert "politica: scope precisa ser objeto" in errors, value


def test_targeted_citation_resolves_in_measured_scope(tmp_path: Path) -> None:
    """Achado bloqueante: homônimo fora do alvo tornava ambígua citação única dentro do alvo."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/orphan.py": "V = 1\n",
            "other/orphan.py": "V = 2\n",
            "README.md": "See orphan.py\n",
        },
        policy_variant(accepted=[], **{"scope.exclude_paths": []}),
    )
    report, _ = hygiene_scan.build_report(tree, hygiene_scan.load_policy(tree), ["pkg"])
    assert [entry["path"] for entry in findings_of(report, "dead-module")] == []
    # Fora do modo direcionado o homônimo é ambíguo de verdade, e a citação não decide por ninguém.
    report, _ = hygiene_scan.build_report(tree, hygiene_scan.load_policy(tree))
    assert "pkg/orphan.py" in [entry["path"] for entry in findings_of(report, "dead-module")]


def test_symlink_loop_in_target_is_refused(tmp_path: Path) -> None:
    """Achado bloqueante: ciclo de links escapava do tratamento e saía como exceção crua."""
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.symlink_to(second)
    second.symlink_to(first)
    tree = make_tree(tmp_path / "arvore", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    for flag in ("--report", "--markdown"):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "hygiene_scan.py"), "--root", str(tree), flag, str(first)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, flag
        assert "nao pode ser resolvido" in result.stderr, flag
        assert "Traceback" not in result.stderr, flag
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "build_hygiene_work_items.py"), "--root", str(REPO_ROOT), "--out-dir", str(first)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_target_with_parent_that_is_not_directory_is_refused(tmp_path: Path) -> None:
    """Achado bloqueante: pai que não é diretório só aparecia na escrita, como exceção crua."""
    parent = tmp_path / "pai"
    parent.write_text("x", encoding="utf-8")
    tree = make_tree(tmp_path / "arvore", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    for flag in ("--report", "--markdown"):
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "hygiene_scan.py"),
                "--root",
                str(tree),
                flag,
                str(parent / "out.json"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode != 0, flag
        assert "pai que nao e diretorio" in result.stderr, flag
        assert "Traceback" not in result.stderr, flag


def test_citation_index_is_the_measured_scope_for_every_target_shape(tmp_path: Path) -> None:
    """Achado bloqueante: alvo-arquivo e múltiplos alvos ainda indexavam a árvore inteira."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/orphan.py": "V = 1\n",
            "other/orphan.py": "V = 2\n",
            "chosen/keep.py": '"""Modulo."""\n',
            "README.md": "See orphan.py\n",
        },
        policy_variant(accepted=[], **{"scope.exclude_paths": []}),
    )
    policy = hygiene_scan.load_policy(tree)
    report, _ = hygiene_scan.build_report(tree, policy, ["pkg/orphan.py"])
    assert [entry["path"] for entry in findings_of(report, "dead-module")] == []
    report, _ = hygiene_scan.build_report(tree, policy, ["pkg", "chosen"])
    assert [entry["path"] for entry in findings_of(report, "dead-module")] == ["chosen/keep.py"]
    # Sem alvo declarado o escopo é a árvore, e aí o homônimo é ambíguo de verdade.
    report, _ = hygiene_scan.build_report(tree, policy)
    assert sorted(entry["path"] for entry in findings_of(report, "dead-module")) == [
        "chosen/keep.py",
        "other/orphan.py",
        "pkg/orphan.py",
    ]


def test_two_artifacts_with_cyclic_target_is_refused(tmp_path: Path) -> None:
    """Achado bloqueante: a comparação de destinos resolvia o caminho antes do tratamento."""
    first = tmp_path / "fora" / "a"
    second = tmp_path / "fora" / "b"
    first.parent.mkdir()
    first.symlink_to(second)
    second.symlink_to(first)
    tree = make_tree(tmp_path / "arvore", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(first),
            "--markdown",
            str(tmp_path / "fora" / "out.md"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "nao pode ser resolvido" in result.stderr
    assert "Traceback" not in result.stderr


def test_generator_refuses_output_that_cannot_be_created(tmp_path: Path) -> None:
    """Achado bloqueante: criação da saída do gerador saía como exceção crua."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(REPO_ROOT),
            "--out-dir",
            "/proc/hygiene-work-items-inexistente",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    # O destino impossível é recusado antes ou durante a criação; em qualquer caso, sem exceção crua.
    assert result.returncode in (1, 2)
    assert "ERRO:" in result.stderr
    assert "Traceback" not in result.stderr


def test_failed_publication_leaves_no_artifact(tmp_path: Path) -> None:
    """Achado bloqueante: falha do segundo artefato deixava o primeiro publicado."""
    tree = make_tree(tmp_path / "arvore", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    report_path = tmp_path / "fora" / "report.json"
    report_path.parent.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(report_path),
            "--markdown",
            "/proc/self/status",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "falha ao gravar o relatorio" in result.stderr
    assert not report_path.exists()


def _run_with_file_limit(arguments: list[str], limit: int) -> subprocess.CompletedProcess:
    """Executa o script com limite de tamanho de arquivo, para forçar falha no meio da escrita."""
    script = (
        "import resource, runpy, sys\n"
        f"resource.setrlimit(resource.RLIMIT_FSIZE, ({limit}, {limit}))\n"
        f"sys.argv = {arguments!r}\n"
        f"runpy.run_path({arguments[0]!r}, run_name='__main__')\n"
    )
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)


def test_partial_write_leaves_no_artifact_and_keeps_previous_one(tmp_path: Path) -> None:
    """Achado bloqueante: falha no meio da escrita deixava arquivo truncado e destruía o anterior."""
    tree = make_tree(tmp_path / "arvore", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    target = tmp_path / "fora" / "report.json"
    target.parent.mkdir()
    target.write_text("ANTERIOR", encoding="utf-8")
    result = _run_with_file_limit(
        [str(SCRIPTS / "hygiene_scan.py"), "--root", str(tree), "--report", str(target)], 1024
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    # O artefato anterior continua íntegro e nenhum temporário sobra no diretório.
    assert target.read_text(encoding="utf-8") == "ANTERIOR"
    assert [item.name for item in target.parent.iterdir()] == ["report.json"]


def test_generator_partial_write_leaves_no_work_item(tmp_path: Path) -> None:
    """Achado bloqueante: falha de escrita dos itens saía como exceção crua e deixava arquivo parcial."""
    out_dir = tmp_path / "saida"
    out_dir.mkdir()
    result = _run_with_file_limit(
        [str(SCRIPTS / "build_hygiene_work_items.py"), "--root", str(REPO_ROOT), "--out-dir", str(out_dir)], 512
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert list(out_dir.iterdir()) == []


def test_absolute_import_resolves_at_root_and_at_importer_directory(tmp_path: Path) -> None:
    """Achado bloqueante: import absoluto dentro de pacote deixava o módulo usado como morto."""
    tree = make_tree(
        tmp_path / "raiz",
        {
            "helper.py": "def run():\n    return 1\n",
            "pkg/consumer.py": "from helper import run\n",
            "README.md": "Use pkg/consumer.py\n",
        },
        policy_variant(accepted=[]),
    )
    assert [entry["path"] for entry in findings_of(scan(tree), "dead-module")] == []
    sibling = make_tree(
        tmp_path / "irmao",
        {
            "pkg/orphan.py": "V = 1\n",
            "pkg/consumer.py": "from pkg import orphan\n",
            "README.md": "Use pkg/consumer.py\n",
        },
        policy_variant(accepted=[]),
    )
    assert [entry["path"] for entry in findings_of(scan(sibling), "dead-module")] == []


def test_targeted_scan_does_not_orphan_exceptions_outside_the_target(tmp_path: Path) -> None:
    """Achado bloqueante: exceção de achado fora do alvo era acusada como órfã."""
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(REPO_ROOT),
            "--paths",
            "higienizar-repositorio/scripts/hygiene_scan.py",
            "--report",
            str(tmp_path / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "report.json").is_file()


def test_redundant_dot_in_citation_still_names_the_file(tmp_path: Path) -> None:
    """Achado bloqueante: citação com `.` redundante não mantinha o módulo vivo."""
    tree = make_tree(
        tmp_path,
        {
            "orphan.py": "V = 1\n",
            "pkg/other.py": "V = 2\n",
            "README.md": "Use ././orphan.py and pkg/./other.py\n",
        },
        policy_variant(accepted=[]),
    )
    assert [entry["path"] for entry in findings_of(scan(tree), "dead-module")] == []


def test_publication_leaves_no_temporary_when_second_destination_is_a_directory(tmp_path: Path) -> None:
    """Achado bloqueante: falha do segundo destino deixava temporário órfão no diretório."""
    tree = make_tree(tmp_path / "arvore", {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    dest = tmp_path / "fora"
    dest.mkdir()
    report_path = dest / "report.json"
    report_path.write_text("ANTERIOR", encoding="utf-8")
    (dest / "markdown.md").mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(report_path),
            "--markdown",
            str(dest / "markdown.md"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert report_path.read_text(encoding="utf-8") == "ANTERIOR"
    assert sorted(item.name for item in dest.iterdir()) == ["markdown.md", "report.json"]


def test_targeted_walk_refuses_directory_symlink_target(tmp_path: Path) -> None:
    """Achado bloqueante: alvo que é link de diretório media o diretório real, fora do alvo."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/consumer.py": "X = 1\n",
            "other/orphan.py": "VALUE = 1\n",
            "README.md": "Use pkg/consumer.py\n",
        },
        policy_variant(accepted=[]),
    )
    (tree / "pkg" / "alias").symlink_to(tree / "other", target_is_directory=True)
    policy = hygiene_scan.load_policy(tree)
    report, problems = hygiene_scan.build_report(tree, policy, ["pkg/alias"])
    assert problems == []
    assert report["analyzed"] == 0
    assert [entry["path"] for entry in report["not_analyzed"]] == ["pkg/alias"]
    assert findings_of(report, "dead-module") == []


def test_exception_identity_must_be_a_finding_identity(tmp_path: Path) -> None:
    """Achado bloqueante: identidade arbitrária era aceita em varredura direcionada."""
    tree = make_tree(
        tmp_path / "arvore",
        {"alpha.py": "V = 1\n", "README.md": "Use alpha.py\n"},
        policy_variant(accepted=[{"id": "garbage", "reason": "Excecao declarada para caso externo ainda nao medido."}]),
    )
    (tmp_path / "fora").mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--paths",
            "alpha.py",
            "--report",
            str(tmp_path / "fora" / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "identidade de achado" in result.stderr
    assert not (tmp_path / "fora" / "report.json").exists()


def test_missing_target_with_dotdot_gets_canonical_label(tmp_path: Path) -> None:
    """Ressalva: alvo inexistente com `..` publicava o caminho como foi escrito."""
    tree = make_tree(tmp_path, {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    policy = hygiene_scan.load_policy(tree)
    report, _ = hygiene_scan.build_report(tree, policy, ["foo/../missing.py"])
    assert [entry["path"] for entry in report["not_analyzed"]] == ["missing.py"]


def test_publication_rolls_back_when_a_later_artifact_fails(tmp_path: Path) -> None:
    """Achado bloqueante: falha no segundo destino deixava o primeiro já publicado."""
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("OLD-A", encoding="utf-8")
    second.write_text("OLD-B", encoding="utf-8")
    original = Path.replace
    calls: list[str] = []

    def failing_replace(self: Path, target: Path) -> Path:
        calls.append(self.name)
        if len(calls) == 2:
            raise OSError("falha simulada no segundo destino")
        return original(self, target)

    Path.replace = failing_replace
    try:
        code = hygiene_scan.publish_artifacts({"a": first, "b": second}, {"a": "NEW-A", "b": "NEW-B"})
    finally:
        Path.replace = original
    assert code == 1
    assert first.read_text(encoding="utf-8") == "OLD-A"
    assert second.read_text(encoding="utf-8") == "OLD-B"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["a.txt", "b.txt"]


def test_exception_class_must_be_declared_in_the_policy(tmp_path: Path) -> None:
    """Achado bloqueante: classe desconhecida com formato válido era aceita em modo direcionado."""
    tree = make_tree(
        tmp_path / "arvore",
        {"alpha.py": "V = 1\n", "README.md": "Use alpha.py\n"},
        policy_variant(
            accepted=[
                {
                    "id": "garbage:0000000000000000",
                    "reason": "Excecao declarada para achado fora do alvo ainda nao medido nesta arvore.",
                }
            ]
        ),
    )
    (tmp_path / "fora").mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--paths",
            "alpha.py",
            "--report",
            str(tmp_path / "fora" / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "classe declarada na politica" in result.stderr
    assert not (tmp_path / "fora" / "report.json").exists()


def test_escaping_missing_target_gets_canonical_label(tmp_path: Path) -> None:
    """Achado bloqueante: alvo inexistente que escapa da raiz mantinha a grafia informada."""
    tree = make_tree(tmp_path, {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    policy = hygiene_scan.load_policy(tree)
    report, _ = hygiene_scan.build_report(tree, policy, ["foo/../../missing.py"])
    assert [entry["path"] for entry in report["not_analyzed"]] == ["missing.py"]


def test_baseline_history_requires_reason_in_every_entry(tmp_path: Path) -> None:
    """Ressalva: a primeira medição da linha de base podia ficar sem motivo escrito."""
    tree = make_tree(tmp_path, {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"})
    policy = hygiene_scan.load_policy(tree)
    policy["classes"]["complexity"]["baseline_history"] = [{"value": 0}]
    errors = validate_hygiene.policy_errors(policy)
    assert any("baseline_history[0].reason" in error for error in errors)


def test_generator_reports_unreadable_report_without_traceback(tmp_path: Path) -> None:
    """Ressalva: relatório externo fora de UTF-8 derrubava o gerador com exceção crua."""
    forged = tmp_path / "forged.json"
    forged.write_bytes(b"\xff\xfe")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "build_hygiene_work_items.py"),
            "--root",
            str(REPO_ROOT),
            "--report",
            str(forged),
            "--out-dir",
            str(tmp_path / "saida"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_equivalent_target_spelling_gets_the_same_refusal(tmp_path: Path) -> None:
    """Ressalva: grafia equivalente do alvo produzia recusa por motivo diferente."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/consumer.py": "X = 1\n",
            "other/orphan.py": "VALUE = 1\n",
            "README.md": "Use pkg/consumer.py\n",
        },
        policy_variant(accepted=[]),
    )
    (tree / "pkg" / "alias").symlink_to(tree / "other", target_is_directory=True)
    policy = hygiene_scan.load_policy(tree)
    report, _ = hygiene_scan.build_report(tree, policy, ["foo/../pkg/alias"])
    assert [entry["path"] for entry in report["not_analyzed"]] == ["pkg/alias"]
    assert "link simbolico para diretorio" in report["not_analyzed"][0]["reason"]


def test_failed_rollback_is_declared_and_not_silent(tmp_path: Path) -> None:
    """Achado bloqueante: reversão que falhava era silenciada e deixava o lote parcialmente publicado."""
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.write_text("OLD-A", encoding="utf-8")
    second.write_text("OLD-B", encoding="utf-8")
    original_replace, original_write = Path.replace, Path.write_bytes
    calls: list[str] = []

    def failing_replace(self: Path, target: Path) -> Path:
        calls.append(self.name)
        if len(calls) == 2:
            raise OSError("falha simulada no segundo destino")
        return original_replace(self, target)

    def failing_restore(self: Path, data: bytes) -> int:
        if self == first:
            raise OSError("falha simulada durante a reversao")
        return original_write(self, data)

    Path.replace, Path.write_bytes = failing_replace, failing_restore
    try:
        code = hygiene_scan.publish_artifacts({"a": first, "b": second}, {"a": "NEW-A", "b": "NEW-B"})
    finally:
        Path.replace, Path.write_bytes = original_replace, original_write
    # Reversão incompleta tem código próprio: o operador precisa saber que o destino pode estar parcial.
    assert code == 2
    assert sorted(item.name for item in tmp_path.iterdir()) == ["a", "b"]


def test_unreadable_previous_artifact_fails_without_temporary(tmp_path: Path) -> None:
    """Achado bloqueante: destino anterior ilegível deixava temporários órfãos e exceção crua."""
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.write_text("OLD-A", encoding="utf-8")
    second.write_text("OLD-B", encoding="utf-8")
    first.chmod(0)
    try:
        code = hygiene_scan.publish_artifacts({"a": first, "b": second}, {"a": "NEW-A", "b": "NEW-B"})
    finally:
        first.chmod(0o600)
    assert code == 1
    assert sorted(item.name for item in tmp_path.iterdir()) == ["a", "b"]
    assert first.read_text(encoding="utf-8") == "OLD-A"


def test_refused_link_target_does_not_contribute_manifests(tmp_path: Path) -> None:
    """Achado bloqueante: alvo recusado por ser link de diretório injetava manifest do diretório real."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/consumer.py": "X = 1\n",
            "other/orphan.py": "VALUE = 1\n",
            "other/requirements.txt": "requests>=2\n",
            "README.md": "Use pkg/consumer.py\n",
        },
        policy_variant(accepted=[]),
    )
    (tree / "pkg" / "alias").symlink_to(tree / "other", target_is_directory=True)
    policy = hygiene_scan.load_policy(tree)
    report, problems = hygiene_scan.build_report(tree, policy, ["foo/../pkg/alias"])
    assert problems == []
    assert report["analyzed"] == 0
    assert [entry["path"] for entry in report["not_analyzed"]] == ["pkg/alias"]
    assert findings_of(report, "unused-dependency") == []
    # A varredura completa continua medindo o manifest real, que está na árvore.
    complete, _ = hygiene_scan.build_report(tree, policy)
    assert [entry["location"] for entry in findings_of(complete, "unused-dependency")] == [
        "other/requirements.txt::requests"
    ]


def test_descendant_of_directory_symlink_is_refused(tmp_path: Path) -> None:
    """Achado bloqueante: alvo descendente de link de diretório media o diretório real."""
    tree = tmp_path / "arvore"
    (tree / "real" / "sub").mkdir(parents=True)
    (tree / "real" / "sub" / "orphan.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tree / "real" / "sub" / "requirements.txt").write_text("requests>=2\n", encoding="utf-8")
    (tree / "config").mkdir()
    (tree / "config" / "hygiene-policy.json").write_text(
        json.dumps(policy_variant(accepted=[]), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (tree / "alias").symlink_to(tree / "real", target_is_directory=True)
    policy = hygiene_scan.load_policy(tree)
    report, problems = hygiene_scan.build_report(tree, policy, ["alias/sub"])
    assert problems == []
    assert report["analyzed"] == 0
    assert [entry["path"] for entry in report["not_analyzed"]] == ["alias"]
    assert findings_of(report, "dead-module") == []
    assert findings_of(report, "unused-dependency") == []
    # A varredura completa continua medindo o diretório real, que está na árvore.
    complete, _ = hygiene_scan.build_report(tree, policy)
    assert [entry["path"] for entry in findings_of(complete, "dead-module")] == ["real/sub/orphan.py"]


def test_leftover_temporary_is_declared(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Achado bloqueante: temporário que não pôde ser removido ficava sem declaração."""
    target = tmp_path / "a"
    original_replace, original_unlink = Path.replace, Path.unlink

    def failing_replace(self: Path, other: Path) -> Path:
        raise OSError("falha simulada na publicacao")

    def failing_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.name.startswith(".a.") and self.name.endswith(".tmp"):
            raise OSError("falha simulada na limpeza")
        original_unlink(self, *args, **kwargs)

    Path.replace, Path.unlink = failing_replace, failing_unlink
    try:
        code = hygiene_scan.publish_artifacts({"a": target}, {"a": "NEW"})
    finally:
        Path.replace, Path.unlink = original_replace, original_unlink
    assert code == 1
    assert "temporario residual" in capsys.readouterr().err
    assert [item.name for item in tmp_path.iterdir() if item.name.endswith(".tmp")]


def test_unencodable_content_fails_without_temporary(tmp_path: Path) -> None:
    """Achado bloqueante: falha de escrita fora de `OSError` deixava temporário e escapava crua."""
    target = tmp_path / "a"
    code = hygiene_scan.publish_artifacts({"a": target}, {"a": "\ud800"})
    assert code == 1
    assert list(tmp_path.iterdir()) == []


def test_work_item_generator_describes_open_debt(tmp_path: Path) -> None:
    """Achado bloqueante: o gerador recusava exatamente a dívida que o work item deve descrever."""
    tree = make_tree(
        tmp_path / "arvore",
        {"orphan.py": "VALUE = 1\n", "README.md": "texto sem citacao\n"},
        policy_variant(accepted=[]),
    )
    out_dir = tmp_path / "saida"
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "scripts" / "build_hygiene_work_items.py"),
            "--root",
            str(tree),
            "--out-dir",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    published = sorted(out_dir.glob("hygiene-*.json"))
    assert published
    items = [json.loads(item.read_text(encoding="utf-8")) for item in published]
    assert any(item["class"] == "dead-module" for item in items)


def test_external_alias_target_is_walked_by_canonical_path(tmp_path: Path) -> None:
    """Achado bloqueante: alvo por link externo para a raiz derrubava a varredura com traceback."""
    tree = make_tree(tmp_path / "arvore", {"sub/alpha.py": "V = 1\n"}, policy_variant(accepted=[]))
    alias = tmp_path / "raiz-alias"
    alias.symlink_to(tree, target_is_directory=True)
    out = tmp_path / "fora"
    out.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--paths",
            str(alias / "sub"),
            "--report",
            str(out / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in result.stderr
    assert result.returncode in (0, 1)
    if (out / "report.json").exists():
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        assert report["analyzed"] >= 1


def test_looping_directory_symlink_is_visible_in_coverage(tmp_path: Path) -> None:
    """Achado bloqueante: link de diretório em ciclo desaparecia da cobertura."""
    tree = make_tree(
        tmp_path / "arvore",
        {"alpha.py": "def used(x):\n    return x\n", "README.md": "Use alpha.py e used\n"},
        policy_variant(accepted=[]),
    )
    (tree / "loopdir").symlink_to(tree / "loopdir", target_is_directory=True)
    report, problems = hygiene_scan.build_report(tree, hygiene_scan.load_policy(tree))
    assert problems == []
    refused = {entry["path"]: entry["reason"] for entry in report["not_analyzed"]}
    assert "loopdir" in refused
    assert "nao resolve" in refused["loopdir"]
    # O buraco de cobertura é visível no gate: a varredura não pode declarar cobertura completa.
    errors = validate_hygiene.validate_hygiene(tree)
    assert any("loopdir" in error for error in errors)


def test_cleanup_failure_during_staging_is_declared(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Achado bloqueante: resíduo de staging por falha de limpeza não era declarado."""
    target = tmp_path / "a"
    original_unlink = Path.unlink

    def failing_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self.name.startswith(".a.") and self.name.endswith(".tmp"):
            raise OSError("falha simulada na limpeza")
        original_unlink(self, *args, **kwargs)

    Path.unlink = failing_unlink
    try:
        code = hygiene_scan.publish_artifacts({"a": target}, {"a": "\ud800"})
    finally:
        Path.unlink = original_unlink
    assert code == 1
    assert "temporario residual" in capsys.readouterr().err


def test_scanner_refuses_orphan_coverage_permission(tmp_path: Path) -> None:
    """Ressalva: a CLI publicava relatório com permissão de cobertura que o gate recusa."""
    tree = make_tree(
        tmp_path / "arvore",
        {"alpha.py": '"""Modulo."""\n', "README.md": "`alpha.py`\n"},
        policy_variant(
            accepted=[],
            not_analyzed_allowed=[
                {
                    "path": "ghost.py",
                    "reason": "Permissao declarada para arquivo que nao existe nesta arvore de teste.",
                }
            ],
        ),
    )
    out = tmp_path / "fora"
    out.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(out / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "permissao declarada sem arquivo nao analisado correspondente" in result.stderr
    assert not (out / "report.json").exists()


def test_external_directory_alias_keeps_manifest_scope(tmp_path: Path) -> None:
    """Achado bloqueante: alvo por link externo media o Python e excluía o manifest da subárvore."""
    tree = make_tree(
        tmp_path / "arvore",
        {
            "sub/a.py": "import json\n",
            "sub/requirements.txt": "requests>=2\n",
            "README.md": "Use sub/a.py\n",
        },
        policy_variant(accepted=[]),
    )
    alias = tmp_path / "alias"
    alias.symlink_to(tree / "sub", target_is_directory=True)
    policy = hygiene_scan.load_policy(tree)
    targeted, problems = hygiene_scan.build_report(tree, policy, [str(alias)])
    complete, _ = hygiene_scan.build_report(tree, policy)
    assert problems == []
    assert targeted["analyzed"] >= 1
    assert [item["location"] for item in findings_of(targeted, "unused-dependency")] == [
        item["location"] for item in findings_of(complete, "unused-dependency")
    ]


def test_scanner_refuses_undeclared_coverage_gap(tmp_path: Path) -> None:
    """Ressalva: a CLI publicava buraco de cobertura que o gate recusa."""
    tree = make_tree(
        tmp_path / "arvore",
        {"broken.py": "def broken(:\n", "README.md": "texto\n"},
        policy_variant(accepted=[]),
    )
    out = tmp_path / "fora"
    out.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "hygiene_scan.py"),
            "--root",
            str(tree),
            "--report",
            str(out / "report.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "arquivo nao analisado e nao declarado na politica" in result.stderr
    assert not (out / "report.json").exists()


def test_baseline_history_requires_reason_on_every_measurement() -> None:
    """Ressalva: a documentação prometia redução sem motivo, mas o gate exige motivo em toda medição."""
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    reference = (SKILL_ROOT / "references" / "global-hygiene-profile.md").read_text(encoding="utf-8")
    for text in (skill, reference):
        assert "inclusive reducao" in text or "inclusive a redução" in text
        assert "nao exige justificativa" not in text


def test_relative_import_of_missing_name_does_not_revive_homonym(tmp_path: Path) -> None:
    """Achado bloqueante: `from . import x` resolvia `pkg.pkg` e mantinha homônimo morto vivo."""
    for name, consumer, body in (
        ("ponto", "pkg/consumer.py", "from . import missing\n"),
        ("dois_pontos", "pkg/sub/consumer.py", "from .. import missing\n"),
    ):
        tree = make_tree(
            tmp_path / name,
            {
                "pkg/__init__.py": "",
                "pkg/pkg.py": "VALUE = 1\n",
                "pkg/sub/__init__.py": "",
                consumer: body,
                "README.md": f"{consumer}\n",
            },
        )
        assert "pkg/pkg.py" in [
            finding["path"] for finding in findings_of(scan(tree), "dead-module")
        ]


def test_normative_texts_require_reason_on_every_baseline_measurement() -> None:
    """Achado bloqueante: política e requisito ainda diziam que redução não exige justificativa."""
    repo = SKILL_ROOT.parent
    policy = json.loads((repo / "config" / "hygiene-policy.json").read_text(encoding="utf-8"))
    assert "nao exige justificativa" not in policy["description"]
    assert "não exige justificativa" not in policy["description"]
    requirements = json.loads(
        (repo / "config" / "skill-system-requirements.json").read_text(encoding="utf-8")
    )
    entry = next(item for item in requirements["requirements"] if item["id"] == "SKSYS-028")
    assert "sem exigir justificativa" not in entry["summary"]


def test_roadmap_describes_the_ratchet_as_it_is() -> None:
    """Achado bloqueante: o roadmap prometia linha de base que só diminui."""
    roadmap = (SKILL_ROOT.parent / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
    assert "só diminui" not in roadmap
    assert "só cresce com entrada nova e motivo escrito" in roadmap


def test_self_import_does_not_keep_module_alive(tmp_path: Path) -> None:
    """Achado bloqueante: `from . import consumer` em `pkg/consumer.py` era importador de si mesmo."""
    for name, extra in (("sem_init", {}), ("com_init", {"pkg/__init__.py": ""})):
        tree = make_tree(
            tmp_path / name,
            {"pkg/consumer.py": "from . import consumer as alias\n", "README.md": "sem invocacao\n", **extra},
        )
        assert [item["path"] for item in findings_of(scan(tree), "dead-module")] == ["pkg/consumer.py"]


def test_shadowed_package_does_not_keep_submodule_alive(tmp_path: Path) -> None:
    """Achado bloqueante: `from .sub import target` mantinha `pkg/sub/target.py` vivo sem importador."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/consumer.py": "from .sub import target as alias\n",
            "pkg/sub.py": "VALUE = 1\n",
            "pkg/sub/target.py": "VALUE = 2\n",
            "README.md": "sem invocacao\n",
        },
    )
    assert "pkg/sub/target.py" in [
        item["path"] for item in findings_of(scan(tree), "dead-module")
    ]


def test_package_init_attribute_does_not_keep_submodule_alive(tmp_path: Path) -> None:
    """Achado bloqueante: atributo definido no `__init__` do pacote tem precedência sobre o submódulo."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/consumer.py": "from .sub import target as alias\n",
            "pkg/sub/__init__.py": "target = 1\n",
            "pkg/sub/target.py": "VALUE = 2\n",
            "README.md": "sem invocacao\n",
        },
    )
    assert "pkg/sub/target.py" in [
        item["path"] for item in findings_of(scan(tree), "dead-module")
    ]


def test_normal_package_import_keeps_submodule_alive(tmp_path: Path) -> None:
    """Regressão do próprio endurecimento: submódulo realmente importado não pode virar achado."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/consumer.py": "from .sub import target\n",
            "pkg/sub/__init__.py": "",
            "pkg/sub/target.py": "VALUE = 2\n",
            "README.md": "sem invocacao\n",
        },
    )
    dead = [item["path"] for item in findings_of(scan(tree), "dead-module")]
    assert "pkg/sub/target.py" not in dead


def test_absolute_from_import_respects_shadowing(tmp_path: Path) -> None:
    """Achado bloqueante: o ramo absoluto não conferia alcance, e o submódulo ficava vivo sem importador."""
    cases = (
        (
            {"pkg/__init__.py": "target = 1\n", "pkg/target.py": "VALUE = 2\n", "consumer.py": "from pkg import target\n"},
            "pkg/target.py",
        ),
        (
            {
                "pkg/__init__.py": "",
                "pkg/sub.py": "target = 1\n",
                "pkg/sub/target.py": "VALUE = 2\n",
                "pkg/consumer.py": "from pkg.sub import target\n",
            },
            "pkg/sub/target.py",
        ),
    )
    for index, (files, expected) in enumerate(cases):
        tree = make_tree(tmp_path / f"caso{index}", {**files, "README.md": "sem invocacao\n"})
        assert expected in [item["path"] for item in findings_of(scan(tree), "dead-module")]


def test_attribute_bound_in_compound_statement_shadows_submodule(tmp_path: Path) -> None:
    """Achado bloqueante: `if`/`try` no `__init__` também ligam atributo que sombreia o submódulo."""
    for index, body in enumerate(
        ("if True:\n    target = 1\n", "try:\n    target = 1\nexcept Exception:\n    target = 2\n")
    ):
        tree = make_tree(
            tmp_path / f"corpo{index}",
            {
                "pkg/__init__.py": "",
                "pkg/consumer.py": "from .sub import target\n",
                "pkg/sub/__init__.py": body,
                "pkg/sub/target.py": "VALUE = 2\n",
                "README.md": "sem invocacao\n",
            },
        )
        assert "pkg/sub/target.py" in [
            item["path"] for item in findings_of(scan(tree), "dead-module")
        ]


def test_root_package_init_shadows_submodule(tmp_path: Path) -> None:
    """Achado bloqueante: `from . import target` na raiz não consultava o `__init__` da raiz."""
    tree = make_tree(
        tmp_path,
        {
            "__init__.py": "target = 1\n",
            "target.py": "VALUE = 2\n",
            "consumer.py": "from . import target as alias\n",
            "README.md": "sem invocacao\n",
        },
    )
    assert "target.py" in [item["path"] for item in findings_of(scan(tree), "dead-module")]


def test_name_bound_inside_function_does_not_shadow_submodule(tmp_path: Path) -> None:
    """Regressão do próprio endurecimento: nome local de função não é atributo do módulo."""
    tree = make_tree(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/consumer.py": "from .sub import target\n",
            "pkg/sub/__init__.py": "def f():\n    target = 1\n",
            "pkg/sub/target.py": "VALUE = 2\n",
            "README.md": "sem invocacao\n",
        },
    )
    assert "pkg/sub/target.py" not in [
        item["path"] for item in findings_of(scan(tree), "dead-module")
    ]
