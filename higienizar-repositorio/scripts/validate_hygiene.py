#!/usr/bin/env python3
"""Valida a política de higiene global, a varredura e o contrato do relatório.

O validador é a parte obrigatória da sequência: ele não julga a dívida do repositório, ele garante
que a política não pode mentir. Quatro regras fazem esse trabalho:

1. a política é conferida campo a campo, com reprovação controlada, sem exceção e sem aprovação
   silenciosa quando falta a biblioteca de schema;
2. a varredura roda de verdade, offline, e a mesma árvore precisa produzir o mesmo relatório;
3. classe `gated` não pode ter achado aberto, e classe `reported` precisa ter contagem igual à
   linha de base declarada — nem acima, porque isso é dívida nova, nem abaixo, porque linha de base
   folgada esconde o que já foi corrigido e deixa de medir;
4. arquivo não analisado precisa estar declarado na política, porque cobertura que encolhe em
   silêncio é indistinguível de aprovação.

A classe `reported` existe para dívida estrutural pré-existente, como complexidade, que não se
resolve declarando item a item: ela é medida, a linha de base é explícita e visível, e a única
direção permitida é diminuir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    from .hygiene_scan import CLASSES, DEFAULT_POLICY, HygieneError, build_report, load_policy
    from .validate_versioning import validate_json_schema
except ImportError:  # pragma: no cover - execucao direta do script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from hygiene_scan import CLASSES, DEFAULT_POLICY, HygieneError, build_report, load_policy
    from validate_versioning import validate_json_schema

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = SKILL_ROOT / "schemas" / "hygiene-report.schema.json"
MIN_REASON_CHARS = 40
CLASS_STATES = ("gated", "reported")
REQUIRED_CLASS_KEYS = ("state", "limits")
INT_KEYS = ("min_body_lines", "max_complexity", "baseline")
BOOL_KEYS = ("exclude_declared_copies", "exclude_tests")
LIST_KEYS = ("entry_points", "ignore_names", "tool_dependencies")
DICT_KEYS = ("import_name_map",)


def _matches(value: object, expected: type) -> bool:
    """Tipo esperado: inteiro não aceita booleano, lista e mapa exigem conteúdo de texto."""
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is list:
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    if expected is dict:
        return isinstance(value, dict) and all(isinstance(item, str) for item in value.values())
    return isinstance(value, expected)


def _typed_errors(entries: dict, name: str, keys: tuple[str, ...], expected: type, label: str) -> list[str]:
    """Confere tipo de campo opcional, sem confundir booleano com inteiro em Python."""
    return [
        f"politica: classes.{name}.{key} precisa ser {label}"
        for key in keys
        if key in entries and not _matches(entries[key], expected)
    ]


def _class_threshold_errors(name: str, entry: dict) -> list[str]:
    """Limiar específico: duplicação precisa de dois corpos, complexidade de duas rotas."""
    errors: list[str] = []
    minimum = entry.get("min_body_lines")
    if name == "duplication" and isinstance(minimum, int) and minimum < 2:
        errors.append("politica: classes.duplication.min_body_lines precisa ser >= 2")
    ceiling = entry.get("max_complexity")
    if name == "complexity":
        if isinstance(ceiling, int) and ceiling < 2:
            errors.append("politica: classes.complexity.max_complexity precisa ser >= 2")
        if entry.get("state") == "reported" and "baseline" not in entry:
            errors.append("politica: classe reportada precisa declarar baseline")
        if entry.get("state") == "gated" and entry.get("baseline"):
            errors.append("politica: classe gated nao pode declarar baseline")
    return errors


def _class_errors(name: str, entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return [f"politica: classes.{name} precisa ser objeto"]
    errors = [
        f"politica: classes.{name}.{key} ausente" for key in REQUIRED_CLASS_KEYS if key not in entry
    ]
    if entry.get("state") not in CLASS_STATES:
        errors.append(f"politica: classes.{name}.state precisa estar em {list(CLASS_STATES)}")
    limits = entry.get("limits")
    if not isinstance(limits, str) or len(limits.strip()) < MIN_REASON_CHARS:
        errors.append(f"politica: classes.{name}.limits precisa declarar o que a classe nao ve")
    errors.extend(_typed_errors(entry, name, INT_KEYS, int, "inteiro"))
    errors.extend(_typed_errors(entry, name, BOOL_KEYS, bool, "booleano"))
    errors.extend(_typed_errors(entry, name, LIST_KEYS, list, "lista de texto"))
    errors.extend(_typed_errors(entry, name, DICT_KEYS, dict, "mapeamento de texto para texto"))
    errors.extend(_class_threshold_errors(name, entry))
    return errors


def _scope_errors(scope: object) -> list[str]:
    if not isinstance(scope, dict):
        return ["politica: scope precisa ser objeto"]
    errors: list[str] = []
    for key in ("include_suffixes", "exclude_dirs", "exclude_paths"):
        value = scope.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"politica: scope.{key} precisa ser lista de texto")
    if isinstance(scope.get("include_suffixes"), list) and not scope["include_suffixes"]:
        errors.append("politica: scope.include_suffixes nao pode ser vazio")
    return errors


def _identity_errors(policy: dict) -> list[str]:
    errors: list[str] = []
    if policy.get("schema_version") != 1:
        errors.append("politica: schema_version precisa ser o inteiro 1")
    if policy.get("system") != "hygiene-policy":
        errors.append("politica: system precisa ser 'hygiene-policy'")
    description = policy.get("description")
    if not isinstance(description, str) or len(description.strip()) < MIN_REASON_CHARS:
        errors.append("politica: description precisa de texto suficiente")
    return errors


def _justified_error(index: int, entry: object, label: str) -> list[str]:
    """Exceção e cobertura declarada precisam de justificativa escrita, nunca texto vazio."""
    if not isinstance(entry, dict):
        return [f"politica: {label}[{index}] precisa ser objeto"]
    field = "id" if label == "accepted" else "path"
    value = entry.get(field)
    if not isinstance(value, str) or not value:
        return [f"politica: {label}[{index}].{field} precisa ser texto"]
    reason = entry.get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < MIN_REASON_CHARS:
        return [f"politica: {label}[{index}].reason precisa de justificativa escrita"]
    return []


def _declared_errors(policy: dict) -> list[str]:
    errors: list[str] = []
    for label in ("accepted", "not_analyzed_allowed"):
        entries = policy.get(label)
        if not isinstance(entries, list):
            errors.append(f"politica: {label} precisa ser lista")
            continue
        for index, entry in enumerate(entries):
            errors.extend(_justified_error(index, entry, label))
        if label == "accepted":
            identities = [
                entry.get("id")
                for entry in entries
                if isinstance(entry, dict) and isinstance(entry.get("id"), str)
            ]
            if len(identities) != len(set(identities)):
                errors.append("politica: accepted tem identidade repetida")
    return errors


def policy_errors(policy: object) -> list[str]:
    """Forma da política: cada campo conferido, nenhuma reprovação por exceção."""
    if not isinstance(policy, dict):
        return ["politica precisa ser objeto"]
    errors = _identity_errors(policy)
    errors.extend(_scope_errors(policy.get("scope")))
    classes = policy.get("classes")
    if not isinstance(classes, dict):
        return [*errors, "politica: classes precisa ser objeto"]
    declared = set(classes)
    errors.extend(f"politica: classe ausente: {name}" for name in sorted(set(CLASSES) - declared))
    errors.extend(f"politica: classe desconhecida: {name}" for name in sorted(declared - set(CLASSES)))
    for name in sorted(declared & set(CLASSES)):
        errors.extend(_class_errors(name, classes[name]))
    errors.extend(_declared_errors(policy))
    return errors


def coverage_errors(report: dict, policy: dict) -> list[str]:
    """Estado de cada classe contra a política e cobertura dos arquivos não analisados."""
    errors: list[str] = []
    allowed = {
        entry["path"]
        for entry in policy.get("not_analyzed_allowed", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    for entry in report.get("not_analyzed", []):
        if entry.get("path") not in allowed:
            errors.append(
                f"cobertura: arquivo nao analisado e nao declarado na politica: {entry.get('path')}"
            )
    for entry in report.get("classes", []):
        name = entry.get("name")
        config = policy["classes"].get(name, {})
        state = config.get("state")
        opened = entry.get("open")
        if state == "gated" and opened:
            errors.append(f"{name}: {opened} achado(s) aberto(s) sem excecao declarada")
        if state == "reported":
            baseline = config.get("baseline")
            if opened != baseline:
                direction = "acima" if (opened or 0) > (baseline or 0) else "abaixo"
                errors.append(
                    f"{name}: contagem aberta {opened} {direction} da linha de base {baseline}; "
                    "a linha de base precisa refletir a contagem real"
                )
        if entry.get("accepted") and not config.get("state"):
            errors.append(f"{name}: classe sem estado declarado")
    return errors


def determinism_errors(root: Path, policy: dict, first: dict) -> list[str]:
    """A mesma árvore e a mesma política precisam produzir o mesmo relatório."""
    again, problems = build_report(root, policy)
    if problems:
        return [f"varredura: {problem}" for problem in problems]
    if json.dumps(again, sort_keys=True) != json.dumps(first, sort_keys=True):
        return ["varredura: duas execucoes produziram relatorios diferentes"]
    return []


def validate_hygiene(root: Path) -> list[str]:
    """Validação completa do perfil: política, varredura, determinismo e contrato."""
    try:
        policy = load_policy(root)
    except HygieneError as error:
        return [str(error)]
    errors = policy_errors(policy)
    if errors:
        return errors
    try:
        report, problems = build_report(root, policy)
    except HygieneError as error:
        return [str(error)]
    errors = [f"varredura: {problem}" for problem in problems]
    errors.extend(coverage_errors(report, policy))
    errors.extend(determinism_errors(root, policy, report))
    if not SCHEMA.is_file():
        errors.append("contrato: schema do relatorio ausente")
    else:
        payload = root / ".hygiene-report-check.json"
        payload.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            errors.extend(validate_json_schema(SCHEMA, payload, "relatorio"))
        finally:
            payload.unlink(missing_ok=True)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida a politica e a varredura de higiene global")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)
    root = (args.root or Path()).resolve()
    errors = validate_hygiene(root)
    if errors:
        print("Higiene reprovada:")
        for error in sorted(set(errors)):
            print(f"- {error}")
        return 1
    try:
        policy = load_policy(root)
        report, _ = build_report(root, policy)
    except HygieneError as error:  # pragma: no cover - ja validado acima
        print(f"ERRO: {error}", file=sys.stderr)
        return 2
    digest = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    print(
        f"Higiene OK: {report['analyzed']} arquivo(s) analisado(s), "
        f"{report['summary']['accepted']} achado(s) aceito(s) por excecao declarada, "
        f"relatorio {digest}, politica {DEFAULT_POLICY.as_posix()}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
