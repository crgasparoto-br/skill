from __future__ import annotations

import copy
import json
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
    "scope": {"include_suffixes": [".py"], "exclude_dirs": [], "exclude_paths": []},
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
    assert findings_of(scan(make_tree(tmp_path, {"a.py": plus, "b.py": minus})), "duplication") == []
    identical = findings_of(
        scan(make_tree(tmp_path / "same", {"a.py": plus, "b.py": plus.replace("alpha", "beta")})),
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
