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


CANONICAL_NAMES = ("__all__", "__version__")


def canonical_shim_problems(tree: ast.Module) -> list[str]:
    """O modulo auditado precisa ser apenas o envelope canonico de exportacao da versao.

    A leitura e fechada por lista permitida: fora de um docstring inicial, da atribuicao de
    `__all__` e da atribuicao de `__version__`, qualquer instrucao reprova. Nao existe, portanto,
    forma aceita de religar os nomes por alias, `__dict__`, `globals`, `exec`, decorador,
    metaclasse, import dinamico, compreensao ou qualquer outro efeito.
    """
    body = list(tree.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    found: dict[str, ast.Assign] = {}
    for node in body:
        simples = (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        )
        if not simples:
            return ["evals/__init__.py contem instrucao fora do envelope canonico de versao"]
        name = node.targets[0].id
        if name not in CANONICAL_NAMES:
            return [f"evals/__init__.py atribui `{name}` fora do envelope canonico de versao"]
        if name in found:
            return [f"evals/__init__.py liga `{name}` mais de uma vez"]
        found[name] = node
    ausentes = [name for name in CANONICAL_NAMES if name not in found]
    if ausentes:
        return ["evals/__init__.py nao declara " + " nem ".join(f"`{name}`" for name in ausentes)]
    version = found["__version__"].value
    if not (isinstance(version, ast.Constant) and isinstance(version.value, str)):
        return ["evals/__init__.py atribui __version__ fora de texto literal"]
    exportado = found["__all__"].value
    if not isinstance(exportado, ast.List) or not all(
        isinstance(element, ast.Constant) and isinstance(element.value, str)
        for element in exportado.elts
    ):
        return ["evals/__init__.py declara __all__ fora de lista de textos"]
    names = [element.value for element in exportado.elts]
    if "__version__" not in names:
        return [f"evals/__init__.py exporta {names!r}, sem __version__"]
    if len(set(names)) != len(names):
        return [f"evals/__init__.py exporta {names!r}, com nome repetido"]
    if any(not name for name in names):
        return [f"evals/__init__.py exporta {names!r}, com nome vazio"]
    return []


SUMMARY_FIELDS = ("total", "passed", "failed", "invalid", "not_run")


def summary_errors(result: Any, label: str) -> list[str]:
    """Valida a forma do resumo do harness antes de indexar as contagens.

    Um harness que devolva algo diferente de um dicionario com contagens inteiras precisa
    reprovar de forma legivel, e nao provocar erro de indexacao.
    """
    summary = result.get("summary") if isinstance(result, dict) else None
    if not isinstance(summary, dict):
        return [f"{label} nao devolveu um resumo legivel"]
    faltando = [campo for campo in SUMMARY_FIELDS if type(summary.get(campo)) is not int]
    if faltando:
        return [f"{label} devolveu resumo sem contagem inteira em {', '.join(faltando)}"]
    return []


def effective_export_problems(module: Any, manifest: dict[str, Any], root: Path) -> list[str]:
    """Confere a exportacao efetiva do pacote, que um modulo irmao pode ter alterado.

    Esta conferencia e defesa em profundidade. A propriedade solida e a checagem estatica do
    envelope, que nao executa o codigo auditado; nenhuma leitura feita depois da importacao resiste
    a codigo que adultere deliberadamente o interpretador, como `builtins.getattr`, `sys.modules`
    ou a classe do modulo. O limite esta declarado em `docs/RELEASE.md`.
    """
    problems: list[str] = []
    origem = getattr(module, "__file__", None)
    try:
        dentro = origem is not None and Path(origem).resolve().is_relative_to(root)
    except (OSError, ValueError, TypeError):
        dentro = False
    if not dentro:
        problems.append(f"evals foi importado de {origem!r}, fora da raiz auditada")

    declared = getattr(module, "__version__", None)
    expected = manifest.get("harness_version")
    if type(declared) is not str or declared != expected:
        problems.append(
            f"evals exporta {declared!r} em tempo de execucao e o manifesto declara {expected!r}"
        )

    exported = getattr(module, "__all__", None)
    if type(exported) is not list or not all(type(name) is str for name in exported):
        return [*problems, f"evals exporta {exported!r} em tempo de execucao fora de lista de textos"]
    if "__version__" not in exported:
        problems.append(f"evals exporta {exported!r} em tempo de execucao, sem __version__")
    elif len(set(exported)) != len(exported) or any(not name for name in exported):
        problems.append(f"evals exporta {exported!r} em tempo de execucao, com repeticao ou nome vazio")
    return problems


def harness_version_errors(root: Path, manifest: dict[str, Any]) -> list[str]:
    """A versao exportada pelo pacote de avaliacoes precisa ser a mesma do manifesto do harness.

    A leitura e estatica, sem importar o pacote, e exige o envelope canonico de duas atribuicoes,
    de modo que o valor efetivo so possa vir do texto literal declarado.
    """
    path = root / "evals" / "__init__.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        return [f"evals/__init__.py ilegivel: {exc}"]

    problems = canonical_shim_problems(tree)
    if problems:
        return problems

    declared = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "__version__"
    )
    expected = manifest.get("harness_version")
    if declared != expected:
        return [f"evals/__init__.py declara {declared!r} e o manifesto declara {expected!r}"]
    return []


def validate_v030_002_matrix(root: Path, harness: Any = None) -> list[str]:
    """Require stable adversarial coverage instead of accepting case files alone."""
    harness = harness or harness_module()
    try:
        cases = [
            case
            for _, case in harness.discover_cases(root)
            if isinstance(case, dict) and str(case.get("case_id", "")).startswith("V030-002-")
        ]
    except BaseException as exc:  # o harness auditado pode falhar de qualquer forma
        return [f"harness de avaliacoes indisponivel: {exc}"]

    errors: list[str] = []
    sem_categoria = sorted(
        str(case.get("case_id", "<sem id>")) for case in cases if not isinstance(case.get("category"), str)
    )
    if sem_categoria:
        return [f"casos V030-002 sem categoria legivel: {', '.join(sem_categoria)}"]
    by_id = {str(case["case_id"]): case for case in cases}
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
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"evals/manifest.json ilegivel: {exc}"]

    if not isinstance(manifest, dict):
        return ["evals/manifest.json precisa ser um objeto JSON"]
    version_errors = harness_version_errors(root, manifest)
    if version_errors:
        return version_errors

    try:
        # `harness_module` garante a raiz auditada no caminho de importacao antes de carregar o
        # pacote, e o modulo de avaliacoes e recuperado em seguida para a conferencia efetiva.
        harness = harness_module()
        import evals
    except BaseException as exc:  # o pacote auditado pode falhar de qualquer forma
        return [f"evals nao pode ser importado: {exc}"]

    try:
        runtime = effective_export_problems(evals, manifest, root)
    except BaseException as exc:  # o pacote auditado pode falhar de qualquer forma
        return [f"evals nao pode ser conferido em tempo de execucao: {exc}"]
    if runtime:
        return runtime

    errors: list[str] = []
    try:
        schema = harness.load_schema(root, "eval-manifest.schema.json")
        errors.extend(harness.schema_errors(manifest, schema))
        if type(manifest.get("schema_version")) is not int:
            errors.append("manifest schema_version precisa ser inteiro exato")
        for key in ("runner", "validator", "case_schema", "result_schema", "report_schema"):
            target = root / manifest.get(key, "__missing__")
            if not target.is_file():
                errors.append(f"manifest target ausente: {manifest.get(key)!r}")
    except BaseException as exc:  # o harness auditado pode falhar de qualquer forma
        errors.append(str(exc))
        return errors

    errors.extend(validate_v030_002_matrix(root, harness))
    try:
        validation = harness.run_evaluations(root, validate_only=True)
    except BaseException as exc:  # o harness auditado pode falhar de qualquer forma
        return [*errors, str(exc)]
    problemas = summary_errors(validation, "a validacao dos casos")
    if problemas:
        return [*errors, *problemas]
    if validation["summary"]["total"] < 1:
        errors.append("nenhum caso de avaliação validado")

    fixture_dir = root / "evals" / "fixtures" / "results"
    try:
        replay = harness.run_evaluations(root, results_dir=fixture_dir)
    except BaseException as exc:  # o harness auditado pode falhar de qualquer forma
        errors.append(str(exc))
        return errors
    problemas = summary_errors(replay, "o replay das fixtures")
    if problemas:
        return [*errors, *problemas]
    if replay["summary"]["failed"] or replay["summary"]["invalid"]:
        errors.append("fixture replay contém falhas ou resultados inválidos")
    if replay["summary"]["not_run"]:
        errors.append("fixture replay contém casos não executados")
    if replay["summary"]["passed"] != replay["summary"]["total"]:
        errors.append("fixture replay não aprovou todos os casos")

    # O envelope estatico nao basta: um modulo irmao pode alterar os valores efetivos durante a
    # importacao ou a execucao, entao a exportacao real e reconferida no fim.
    try:
        errors.extend(effective_export_problems(evals, manifest, root))
    except BaseException as exc:  # o pacote auditado pode falhar de qualquer forma
        errors.append(f"evals nao pode ser conferido em tempo de execucao: {exc}")
    return errors


class ParserError(Exception):
    """Erro de linha de comando que precisa reprovar com status 1, e nao encerrar com status 2."""


class Parser(argparse.ArgumentParser):
    """Interpretador de argumentos que reporta erro pela via legivel do gate."""

    def error(self, message: str) -> None:
        raise ParserError(message)


def root_errors(value: str | None) -> list[str]:
    """Resolve a raiz auditada recusando valor vazio, inacessivel ou em ciclo de links."""
    if value is not None and not value.strip():
        return ["argumento --root vazio"]
    raiz = Path(value) if value is not None else Path(__file__).resolve().parents[1]
    try:
        raiz.resolve()
    except (OSError, RuntimeError, UnicodeEncodeError, ValueError) as exc:
        return [f"raiz inacessivel: {exc}"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = Parser(description=__doc__)
    parser.add_argument("--root", default=None)
    try:
        args = parser.parse_args(argv)
    except ParserError as exc:
        print(f"Validação de avaliações falhou:\n- {exc}")
        return 1
    problems = root_errors(args.root)
    if problems:
        print("Validação de avaliações falhou:")
        print("\n".join(f"- {problem}" for problem in problems))
        return 1
    raiz = Path(args.root) if args.root is not None else Path(__file__).resolve().parents[1]
    errors = validate_evals(raiz.resolve())
    if errors:
        print("Validação de avaliações falhou:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Evaluation harness validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
