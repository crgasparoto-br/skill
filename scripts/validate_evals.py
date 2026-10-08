#!/usr/bin/env python3
"""Validate evaluation cases and deterministic harness fixtures."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any


def harness_module():
    """Importa o harness sob validacao apenas quando a execucao e realmente necessaria.

    A versao exportada pelo pacote e conferida por leitura estatica antes desta importacao:
    importar o pacote auditado primeiro executaria codigo do repositorio sob verificacao.
    """
    try:
        from evals import run_evals
    except ModuleNotFoundError:  # pragma: no cover - caminho de execucao por script
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from evals import run_evals
    return run_evals


REQUIRED_V030_002_CATEGORIES = {
    "selection",
    "authority",
    "capability",
    "evidence",
    "context",
    "progressive-loading",
    "read-only",
    "output-contract",
}


def selection_case_errors(case: dict[str, Any]) -> list[str]:
    """Require one of the three selection shapes, each with its own invariant.

    A selection case may prove abstention on a material tie, prove a resolved
    decision, or prove that a request without a catalog trigger stays unknown.
    Accepting only the tie shape made positive selection inexpressible, so the
    matrix could never demonstrate that the router picks the right skill.
    """
    case_id = case["case_id"]
    expected = case["expected"]
    selection = expected.get("selection")
    outcome = expected["outcome"]
    selected = expected["selected_skill"]
    if selection is None:
        if outcome != "UNKNOWN" or selected is not None:
            return [f"{case_id} must declare a structured selection unless it expects no catalog match"]
        return []
    if not isinstance(selection, dict):
        return [f"{case_id} must declare a structured selection"]
    candidates = selection["candidate_skills"]
    if not selection["reason_markers"]:
        return [f"{case_id} must declare structured reason markers"]
    if selection["disambiguation_required"]:
        if len(candidates) < 2:
            return [f"{case_id} must declare a structured material shortlist"]
        if outcome != "UNKNOWN" or selected is not None:
            return [f"{case_id} must expect UNKNOWN without a selected skill for a material selection tie"]
        return []
    if outcome != "PASS" or not isinstance(selected, str) or not selected:
        return [f"{case_id} must expect PASS with a selected skill for a resolved selection"]
    if candidates != [selected]:
        return [f"{case_id} must declare exactly the resolved skill as its shortlist"]
    return []


def _bound_names(target: ast.AST) -> list[str]:
    """Nomes ligados por um alvo de atribuicao, em qualquer forma de desempacotamento."""
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_bound_names(element))
        return names
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return []


def _binds(node: ast.AST) -> list[str]:
    """Nomes que um no pode definir ou remover, cobrindo atribuicao, laco, contexto e import."""
    if isinstance(node, ast.Assign):
        names: list[str] = []
        for target in node.targets:
            names.extend(_bound_names(target))
        return names
    if isinstance(node, (ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
        return _bound_names(node.target)
    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        return _bound_names(node.target)
    if isinstance(node, (ast.With, ast.AsyncWith)):
        names = []
        for item in node.items:
            if item.optional_vars is not None:
                names.extend(_bound_names(item.optional_vars))
        return names
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        return list(node.names)
    if isinstance(node, ast.Delete):
        names = []
        for target in node.targets:
            names.extend(_bound_names(target))
        return names
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return [alias.asname or alias.name.split(".")[0] for alias in node.names]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, ast.ExceptHandler):
        return [node.name] if node.name else []
    if isinstance(node, ast.MatchAs):
        return [node.name] if node.name else []
    if isinstance(node, ast.MatchStar):
        return [node.name] if node.name else []
    if isinstance(node, ast.MatchMapping):
        return [node.rest] if node.rest else []
    return []


def harness_version_errors(root: Path, manifest: dict[str, Any]) -> list[str]:
    """A versao exportada pelo pacote de avaliacoes precisa ser a mesma do manifesto do harness.

    A leitura e estatica, sem importar o pacote, e exige a forma canonica: exatamente uma ligacao
    de `__version__`, no nivel de modulo, com texto literal, e `__version__` presente em `__all__`.
    Qualquer outra ligacao — anotada, aumentada, dentro de condicional, de laco, de contexto,
    desempacotada, em `global`/`nonlocal`, em `del` ou por import — reprova, porque mudaria o valor
    efetivo em tempo de import e a comparacao com o manifesto perderia sentido.
    """
    path = root / "evals" / "__init__.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return [f"evals/__init__.py ilegivel: {exc}"]

    version_nodes = [node for node in ast.walk(tree) if "__version__" in _binds(node)]
    if not version_nodes:
        return ["evals/__init__.py nao declara __version__ com texto literal"]
    if len(version_nodes) > 1:
        return ["evals/__init__.py liga __version__ mais de uma vez"]
    node = version_nodes[0]
    simple = (
        isinstance(node, ast.Assign)
        and node in tree.body
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    )
    if not simple:
        return ["evals/__init__.py liga __version__ fora de atribuicao simples no nivel de modulo"]
    value = node.value
    if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
        return ["evals/__init__.py atribui __version__ fora de texto literal"]

    all_nodes = [candidate for candidate in ast.walk(tree) if "__all__" in _binds(candidate)]
    if not all_nodes:
        return ["evals/__init__.py nao declara __all__"]
    if len(all_nodes) > 1:
        return ["evals/__init__.py liga __all__ mais de uma vez"]
    declared_all = all_nodes[0]
    simple_all = (
        isinstance(declared_all, ast.Assign)
        and declared_all in tree.body
        and len(declared_all.targets) == 1
        and isinstance(declared_all.targets[0], ast.Name)
    )
    if not simple_all:
        return ["evals/__init__.py liga __all__ fora de atribuicao simples no nivel de modulo"]
    exported = declared_all.value
    if not isinstance(exported, ast.List) or not all(
        isinstance(element, ast.Constant) and isinstance(element.value, str) for element in exported.elts
    ):
        return ["evals/__init__.py declara __all__ fora de lista de textos"]
    names = [element.value for element in exported.elts]
    if "__version__" not in names:
        return [f"evals/__init__.py exporta {names!r}, sem __version__"]

    declared = value.value
    expected = manifest.get("harness_version")
    if declared != expected:
        return [f"evals/__init__.py declara {declared!r} e o manifesto declara {expected!r}"]
    return []


def validate_v030_002_matrix(root: Path, harness: Any = None) -> list[str]:
    """Require stable adversarial coverage instead of accepting case files alone."""
    harness = harness or harness_module()
    try:
        cases = [
            case for _, case in harness.discover_cases(root) if str(case["case_id"]).startswith("V030-002-")
        ]
    except Exception as exc:  # o harness auditado pode falhar de qualquer forma
        return [f"harness de avaliacoes indisponivel: {exc}"]

    errors: list[str] = []
    by_id = {case["case_id"]: case for case in cases}
    categories = {case["category"] for case in cases}
    missing_categories = sorted(REQUIRED_V030_002_CATEGORIES - categories)
    if missing_categories:
        errors.append("V030-002 lacks adversarial categories: " + ", ".join(missing_categories))
    if not cases:
        errors.append("V030-002 has no versioned adversarial cases")
        return errors

    for case in cases:
        case_id = case["case_id"]
        sibling_id = case.get("sibling_case_id")
        if not sibling_id:
            errors.append(f"{case_id} lacks sibling_case_id")
            continue
        sibling = by_id.get(sibling_id)
        if sibling is None:
            errors.append(f"{case_id} references missing sibling {sibling_id}")
            continue
        if sibling_id == case_id:
            errors.append(f"{case_id} cannot be its own sibling")
        if sibling.get("sibling_case_id") != case_id:
            errors.append(f"{case_id} and {sibling_id} must reference each other as siblings")
        if sibling.get("category") != case["category"]:
            errors.append(f"{case_id} and {sibling_id} must share the same category")
        if sibling.get("task", {}).get("user_prompt") == case.get("task", {}).get("user_prompt"):
            errors.append(f"{case_id} and {sibling_id} must vary the user prompt")
        expected = case["expected"]
        if not expected["required_evidence"]:
            errors.append(f"{case_id} must declare required evidence")
        if not expected["forbidden_actions"]:
            errors.append(f"{case_id} must declare forbidden actions")
        if not expected["response_minimum"]["required_markers"]:
            errors.append(f"{case_id} must declare response markers")
        if case["category"] == "selection":
            errors.extend(selection_case_errors(case))
        if case["category"] == "authority":
            untrusted_inputs = case["context"].get("untrusted_inputs") or []
            if not untrusted_inputs:
                errors.append(f"{case_id} must carry an untrusted input with explicit origin")
            if not isinstance(expected.get("authority"), dict):
                errors.append(f"{case_id} must declare structured authority expectations")
            for item in untrusted_inputs:
                if item["content"] in case["task"]["user_prompt"]:
                    errors.append(f"{case_id} must not inline untrusted content in the user prompt")
    return errors


def validate_evals(root: Path) -> list[str]:
    """Valida o harness de avaliacoes com a checagem estatica antes de qualquer execucao.

    A paridade da versao exportada e conferida por leitura da arvore sintatica, sem importar o
    pacote auditado. Somente depois disso o harness e importado e exercitado, e uma falha de
    importacao vira reprovacao legivel em vez de traceback.
    """
    manifest_path = root / "evals" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"evals/manifest.json ilegivel: {exc}"]

    version_errors = harness_version_errors(root, manifest)
    if version_errors:
        return version_errors

    try:
        harness = harness_module()
    except Exception as exc:  # o pacote auditado pode falhar ao importar
        return [f"evals nao pode ser importado: {exc}"]

    errors: list[str] = []
    try:
        schema = harness.load_schema(root, "eval-manifest.schema.json")
        errors.extend(harness.schema_errors(manifest, schema))
        for key in ("runner", "validator", "case_schema", "result_schema", "report_schema"):
            target = root / manifest.get(key, "__missing__")
            if not target.is_file():
                errors.append(f"manifest target ausente: {manifest.get(key)!r}")
    except harness.HarnessError as exc:
        errors.append(str(exc))
        return errors

    errors.extend(validate_v030_002_matrix(root, harness))
    try:
        validation = harness.run_evaluations(root, validate_only=True)
    except harness.HarnessError as exc:
        return [*errors, str(exc)]
    if validation["summary"]["total"] < 1:
        errors.append("nenhum caso de avaliação validado")

    fixture_dir = root / "evals" / "fixtures" / "results"
    try:
        replay = harness.run_evaluations(root, results_dir=fixture_dir)
    except harness.HarnessError as exc:
        errors.append(str(exc))
        return errors
    if replay["summary"]["failed"] or replay["summary"]["invalid"]:
        errors.append("fixture replay contém falhas ou resultados inválidos")
    if replay["summary"]["not_run"]:
        errors.append("fixture replay contém casos não executados")
    if replay["summary"]["passed"] != replay["summary"]["total"]:
        errors.append("fixture replay não aprovou todos os casos")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    errors = validate_evals(args.root.resolve())
    if errors:
        print("Validação de avaliações falhou:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Evaluation harness validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
