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
    assert any("limits precisa declarar" in error for error in errors)
    errors = validate_hygiene.policy_errors(
        policy_variant(**{"classes.complexity.state": "gated", "classes.complexity.baseline": 2})
    )
    assert "politica: classe gated nao pode declarar baseline" in errors
    errors = validate_hygiene.policy_errors(policy_variant(**{"classes.duplication.min_body_lines": True}))
    assert any("min_body_lines precisa ser inteiro" in error for error in errors)


def test_policy_rejects_short_and_duplicated_justification() -> None:
    document = copy.deepcopy(BASE_POLICY)
    document["accepted"] = [{"id": "duplication:0" * 1, "reason": "curto"}]
    errors = validate_hygiene.policy_errors(document)
    assert any("reason precisa de justificativa escrita" in error for error in errors)
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
    document = policy_variant(**{"classes.complexity.baseline": 3})
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
    document["accepted"] = [{"id": "dead-symbol:" + "b" * 16, "reason": "r" * 60}]
    (tree / "config" / "hygiene-policy.json").write_text(json.dumps(document), encoding="utf-8")
    errors = validate_hygiene.validate_hygiene(tree)
    assert any("excecao declarada sem achado correspondente" in error for error in errors)


def test_gate_passes_on_declared_state(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"orphan.py": "VALUE = 1\n"})
    report = scan(tree)
    identity = findings_of(report, "dead-module")[0]["id"]
    document = copy.deepcopy(BASE_POLICY)
    document["accepted"] = [{"id": identity, "reason": "Modulo consumido por carga dinamica fora da arvore."}]
    (tree / "config" / "hygiene-policy.json").write_text(json.dumps(document), encoding="utf-8")
    assert validate_hygiene.validate_hygiene(tree) == []


def test_work_items_follow_the_canonical_form(tmp_path: Path) -> None:
    tree = make_tree(tmp_path, {"orphan.py": "VALUE = 1\n"})
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
