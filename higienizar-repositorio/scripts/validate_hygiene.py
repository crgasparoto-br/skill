#!/usr/bin/env python3
"""Valida a política de higiene global, a varredura e o contrato do relatório.

O validador é a parte obrigatória da sequência: ele não julga a dívida do repositório, ele garante
que a política não pode mentir. As regras que fazem esse trabalho:

1. a política é conferida campo a campo, com reprovação controlada, sem exceção e sem aprovação
   silenciosa quando falta a biblioteca de schema;
2. limiar exigido pela classe precisa estar declarado: campo ausente não cai em default escondido no
   código, porque limiar que não está na política não está sob revisão;
3. exclusão de caminho é declaração com motivo escrito e aparece no relatório, porque escopo que
   encolhe em silêncio é indistinguível de aprovação;
4. a varredura roda de verdade, offline, e a mesma árvore precisa produzir o mesmo relatório;
5. classe `gated` não pode ter achado aberto, e classe `reported` precisa ter contagem igual à linha
   de base declarada — nem acima, porque isso é dívida nova, nem abaixo, porque linha de base folgada
   esconde o que já foi corrigido e deixa de medir;
6. classe `reported` não aceita exceção item a item: a dívida dela é agregada, e a catraca é a
   história de linha de base declarada na política, onde crescer exige entrada nova com motivo;
7. arquivo não analisado e exceção órfã reprovam, nos dois sentidos: permissão sem arquivo e arquivo
   sem permissão;
8. o relatório é conferido contra o schema em memória, sem escrever nada na árvore varrida.

A validação é somente leitura: ela não cria, não altera e não remove arquivo na raiz analisada.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

try:
    from .hygiene_scan import (
        CLASSES,
        DEFAULT_POLICY,
        HygieneError,
        build_report,
        declared_exclusions,
        load_policy,
        missing_class_keys,
        report_contract_errors,
    )
except ImportError:  # pragma: no cover - execucao direta do script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    from hygiene_scan import (
        CLASSES,
        DEFAULT_POLICY,
        HygieneError,
        build_report,
        declared_exclusions,
        load_policy,
        missing_class_keys,
        report_contract_errors,
    )

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = SKILL_ROOT / "schemas" / "hygiene-report.schema.json"
MIN_REASON_CHARS = 40
MIN_REASON_WORDS = 6
MIN_DISTINCT_CHARS = 12
CLASS_STATES = ("gated", "reported")
COMMON_CLASS_KEYS = ("state", "limits")
EXTRA_CLASS_KEYS = {"duplication": ("min_body_lines",), "complexity": ("max_complexity",)}
INT_KEYS = ("min_body_lines", "max_complexity", "baseline")
BOOL_KEYS = ("exclude_declared_copies", "exclude_tests")
LIST_KEYS = ("tool_dependencies",)
DICT_KEYS = ("import_name_map",)


def reason_problem(reason: object) -> str | None:
    """Justificativa escrita: extensão, palavras e variedade.

    O gate confere forma, não veracidade — quem julga o mérito é a revisão. Ainda assim, texto curto,
    palavra única repetida e preenchimento de baixa variedade são recusados, porque nenhum deles é
    justificativa escrita, e aceitá-los esvaziaria a exigência.
    """
    if not isinstance(reason, str):
        return "precisa ser texto"
    stripped = reason.strip()
    if len(stripped) < MIN_REASON_CHARS:
        return f"precisa de pelo menos {MIN_REASON_CHARS} caracteres"
    words = [word for word in stripped.split() if any(character.isalpha() for character in word)]
    if len(words) < MIN_REASON_WORDS:
        return f"precisa de pelo menos {MIN_REASON_WORDS} palavras"
    if len({character.lower() for character in stripped if not character.isspace()}) < MIN_DISTINCT_CHARS:
        return "precisa de texto com variedade, e nao de preenchimento repetido"
    return None


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


def _history_errors(name: str, entry: dict) -> list[str]:
    """Catraca declarada: a linha de base precisa ser o último valor da história registrada.

    Crescer exige entrada nova com motivo escrito, e diminuir é sempre permitido. A história é a
    única forma de crescimento verificável sem depender do histórico do Git, que o clone raso do CI
    não garante.
    """
    history = entry.get("baseline_history")
    if not isinstance(history, list) or not history:
        return [f"politica: classes.{name}.baseline_history precisa declarar a historia da linha de base"]
    errors: list[str] = []
    values: list[int] = []
    previous: int | None = None
    for index, item in enumerate(history):
        if not isinstance(item, dict):
            errors.append(f"politica: classes.{name}.baseline_history[{index}] precisa ser objeto")
            continue
        value = item.get("value")
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"politica: classes.{name}.baseline_history[{index}].value precisa ser inteiro")
            continue
        # Crescer divida exige motivo escrito; reduzir e progresso e pode ser declarado sem justificar,
        # mas motivo presente precisa ter forma, para que o campo nao vire lugar de preenchimento.
        if value > (previous if previous is not None else value) or item.get("reason") is not None:
            problem = reason_problem(item.get("reason"))
            if problem is not None:
                errors.append(
                    f"politica: classes.{name}.baseline_history[{index}].reason {problem}"
                )
        values.append(value)
        previous = value
    if values and entry.get("baseline") != values[-1]:
        errors.append(
            f"politica: classes.{name}.baseline precisa ser o ultimo valor da historia declarada"
        )
    return errors


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
        if entry.get("state") == "reported":
            errors.extend(_history_errors(name, entry))
        elif entry.get("baseline"):
            errors.append("politica: classe gated nao pode declarar baseline")
    return errors


SUPPRESSOR_KEYS = ("entry_points", "ignore_names")


def _suppressor_errors(name: str, entry: dict) -> list[str]:
    """Supressor declarativo precisa dizer o que silencia e por quê.

    Lista de texto solto esconde nome ou caminho arbitrário sem motivo: a decisão continua explícita na
    política, mas sem auditabilidade. Cada entrada declara `name` e `reason` escritos.
    """
    errors: list[str] = []
    for key in SUPPRESSOR_KEYS:
        entries = entry.get(key)
        if not isinstance(entries, list):
            continue
        for index, item in enumerate(entries):
            label = f"classes.{name}.{key}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"politica: {label} precisa ser objeto com name e reason")
                continue
            declared = item.get("name")
            if not isinstance(declared, str) or not declared:
                errors.append(f"politica: {label}.name precisa ser texto")
            problem = reason_problem(item.get("reason"))
            if problem is not None:
                errors.append(f"politica: {label}.reason {problem}")
    return errors


def _class_errors(name: str, entry: object) -> list[str]:
    if not isinstance(entry, dict):
        return [f"politica: classes.{name} precisa ser objeto"]
    required = COMMON_CLASS_KEYS + EXTRA_CLASS_KEYS.get(name, ())
    errors = [f"politica: classes.{name}.{key} ausente" for key in required if key not in entry]
    if entry.get("state") not in CLASS_STATES:
        errors.append(f"politica: classes.{name}.state precisa estar em {list(CLASS_STATES)}")
    problem = reason_problem(entry.get("limits"))
    if problem is not None:
        errors.append(f"politica: classes.{name}.limits {problem}: precisa declarar o que a classe nao ve")
    errors.extend(_typed_errors(entry, name, INT_KEYS, int, "inteiro"))
    errors.extend(_typed_errors(entry, name, BOOL_KEYS, bool, "booleano"))
    errors.extend(_typed_errors(entry, name, LIST_KEYS, list, "lista de texto"))
    errors.extend(_typed_errors(entry, name, DICT_KEYS, dict, "mapeamento de texto para texto"))
    errors.extend(_class_threshold_errors(name, entry))
    errors.extend(_suppressor_errors(name, entry))
    return errors


def _scope_errors(scope: object) -> list[str]:
    if not isinstance(scope, dict):
        return ["politica: scope precisa ser objeto"]
    errors: list[str] = []
    for key in ("include_suffixes", "exclude_dirs"):
        value = scope.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"politica: scope.{key} precisa ser lista de texto")
    if isinstance(scope.get("include_suffixes"), list) and not scope["include_suffixes"]:
        errors.append("politica: scope.include_suffixes nao pode ser vazio")
    corpus = scope.get("corpus_suffixes")
    if not isinstance(corpus, list) or not corpus:
        errors.append("politica: scope.corpus_suffixes nao pode ser vazio")
    elif any(not isinstance(suffix, str) or not suffix.startswith(".") for suffix in corpus):
        errors.append("politica: scope.corpus_suffixes precisa ser lista de sufixos iniciados por ponto")
    exclusions = scope.get("exclude_paths")
    if not isinstance(exclusions, list):
        return [*errors, "politica: scope.exclude_paths precisa ser lista"]
    for index, entry in enumerate(exclusions):
        if not isinstance(entry, dict):
            errors.append(f"politica: scope.exclude_paths[{index}] precisa ser objeto com path e reason")
            continue
        declared_path = entry.get("path")
        if not isinstance(declared_path, str) or not declared_path:
            errors.append(f"politica: scope.exclude_paths[{index}].path precisa ser texto")
        elif Path(declared_path).is_absolute() or ".." in Path(declared_path).parts:
            # Exclusao que sai da raiz nao exclusao de caminho da arvore auditada: ela aparentaria
            # excluir algo do repositorio sem sair dele.
            errors.append(
                f"politica: scope.exclude_paths[{index}].path precisa ser caminho relativo dentro da raiz"
            )
        elif PurePosixPath(declared_path).as_posix() != declared_path:
            # `./x.py` e `a//b.py` apontam para o mesmo arquivo, mas nao casam com a comparacao do
            # escopo: o relatorio declararia uma exclusao que nao aconteceu.
            errors.append(
                f"politica: scope.exclude_paths[{index}].path precisa ser caminho canonico, sem prefixo nem repeticao"
            )
        problem = reason_problem(entry.get("reason"))
        if problem is not None:
            errors.append(f"politica: scope.exclude_paths[{index}].reason {problem}")
    return errors


def _declaration_errors(policy: dict) -> list[str]:
    """Decisão de escopo e de exceção é declarada, nunca assumida por default no código.

    Campo ausente vira default silencioso na varredura, e a política deixaria de ser a única fonte de
    escopo e de exceção: excluir cópia declarada ou diretório de teste sem dizer isso na política é
    cobertura falsa sem erro.
    """
    errors: list[str] = []
    classes = policy.get("classes") if isinstance(policy.get("classes"), dict) else {}
    for name in sorted(CLASSES):
        if not isinstance(classes.get(name), dict):
            errors.append(f"politica: classes.{name} precisa ser objeto")
    missing = missing_class_keys(policy)
    if missing:
        errors.append("politica: classes sem chave de decisao declarada: " + ", ".join(missing))
    return errors


def _identity_errors(policy: dict) -> list[str]:
    errors: list[str] = []
    if policy.get("schema_version") != 1:
        errors.append("politica: schema_version precisa ser o inteiro 1")
    if policy.get("system") != "hygiene-policy":
        errors.append("politica: system precisa ser 'hygiene-policy'")
    problem = reason_problem(policy.get("description"))
    if problem is not None:
        errors.append(f"politica: description {problem}")
    return errors


def _justified_error(index: int, entry: object, label: str) -> list[str]:
    """Exceção e cobertura declarada precisam de justificativa escrita, nunca texto vazio."""
    if not isinstance(entry, dict):
        return [f"politica: {label}[{index}] precisa ser objeto"]
    field = "id" if label == "accepted" else "path"
    value = entry.get(field)
    if not isinstance(value, str) or not value:
        return [f"politica: {label}[{index}].{field} precisa ser texto"]
    errors: list[str] = []
    if field == "path":
        declared_path = Path(value)
        if declared_path.is_absolute() or ".." in declared_path.parts:
            # Caminho absoluto aqui permitiria declarar cobertura de fora da arvore, e o relatorio deixaria
            # de ser comparavel entre raizes equivalentes.
            errors.append(
                f"politica: {label}[{index}].path precisa ser caminho relativo dentro da raiz"
            )
        elif PurePosixPath(value).as_posix() != value:
            errors.append(
                f"politica: {label}[{index}].path precisa ser caminho canonico, sem prefixo nem repeticao"
            )
    problem = reason_problem(entry.get("reason"))
    if problem is not None:
        errors.append(f"politica: {label}[{index}].reason {problem}")
    return errors


def _declared_errors(policy: dict) -> list[str]:
    errors: list[str] = []
    measured = {
        name
        for name, config in (policy.get("classes") or {}).items()
        if isinstance(config, dict) and config.get("state") == "reported"
    }
    for label in ("accepted", "not_analyzed_allowed"):
        entries = policy.get(label)
        if not isinstance(entries, list):
            errors.append(f"politica: {label} precisa ser lista")
            continue
        for index, entry in enumerate(entries):
            errors.extend(_justified_error(index, entry, label))
            if label == "accepted" and isinstance(entry, dict):
                identity = str(entry.get("id") or "")
                class_name = identity.split(":", 1)[0]
                if class_name in measured:
                    errors.append(
                        f"politica: accepted[{index}] pertence a classe medida contra linha de base "
                        f"({class_name}); a divida agregada se ajusta pela linha de base, nao por excecao"
                    )
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
    errors.extend(_declaration_errors(policy))
    errors.extend(_declared_errors(policy))
    return errors


def _class_coverage_errors(entry: dict, config: dict) -> list[str]:
    name = entry.get("name")
    members = entry.get("findings") if isinstance(entry.get("findings"), list) else []
    opened = sum(1 for finding in members if finding.get("state") == "open")
    accepted = sum(1 for finding in members if finding.get("state") == "accepted")
    errors: list[str] = []
    if entry.get("open") != opened or entry.get("accepted") != accepted:
        errors.append(f"{name}: contagem por estado nao corresponde aos achados da classe")
    state = config.get("state")
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
        if accepted:
            errors.append(f"{name}: classe medida contra linha de base nao aceita excecao item a item")
    if not state:
        errors.append(f"{name}: classe sem estado declarado")
    return errors


def coverage_errors(root: Path, report: dict, policy: dict) -> list[str]:
    """Estado de cada classe, exclusões declaradas e cobertura do que não foi analisado."""
    errors: list[str] = []
    if not report.get("analyzed"):
        errors.append("cobertura: nenhum arquivo analisado; escopo vazio nao e arvore limpa")
    declared = declared_exclusions(policy)
    for path in sorted(declared):
        candidate = (root / path).resolve()
        if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
            errors.append(f"cobertura: exclusao declarada sem arquivo correspondente: {path}")
    reported_excluded = {
        entry.get("path") for entry in report.get("excluded", []) if isinstance(entry, dict)
    }
    for path in sorted(set(declared) - reported_excluded):
        errors.append(f"cobertura: exclusao declarada ausente do relatorio: {path}")
    allowed = {
        entry["path"]
        for entry in policy.get("not_analyzed_allowed", [])
        if isinstance(entry, dict) and isinstance(entry.get("path"), str)
    }
    missing = {entry.get("path") for entry in report.get("not_analyzed", [])}
    for path in sorted(missing - allowed):
        errors.append(f"cobertura: arquivo nao analisado e nao declarado na politica: {path}")
    for path in sorted(allowed - missing):
        errors.append(f"cobertura: permissao declarada sem arquivo nao analisado correspondente: {path}")
    classes = report.get("classes") if isinstance(report.get("classes"), list) else []
    names = sorted(entry.get("name") for entry in classes if isinstance(entry, dict))
    if names != sorted(CLASSES):
        errors.append("cobertura: relatorio precisa de exatamente uma entrada por classe")
    for entry in classes:
        if isinstance(entry, dict):
            errors.extend(_class_coverage_errors(entry, policy["classes"].get(entry.get("name"), {})))
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    totals = {
        state: sum(
            1
            for entry in classes
            for finding in entry.get("findings", [])
            if finding.get("state") == state
        )
        for state in ("open", "accepted")
    }
    for state, total in totals.items():
        if summary.get(state) != total:
            errors.append(f"cobertura: resumo de {state} nao corresponde aos achados do relatorio")
    if summary.get("not_analyzed") != len(report.get("not_analyzed", [])):
        errors.append("cobertura: resumo de nao analisados nao corresponde ao relatorio")
    return errors


def determinism_errors(root: Path, policy: dict, first: dict) -> list[str]:
    """A mesma árvore e a mesma política precisam produzir o mesmo relatório."""
    again, problems = build_report(root, policy)
    if problems:
        return [f"varredura: {problem}" for problem in problems]
    if json.dumps(again, sort_keys=True) != json.dumps(first, sort_keys=True):
        return ["varredura: duas execucoes produziram relatorios diferentes"]
    return []


def schema_errors(report: dict) -> list[str]:
    """Contrato do relatório conferido pela mesma função que o produtor usa antes de gravar."""
    return report_contract_errors(report)


def validate_hygiene(root: Path) -> list[str]:
    """Validação completa do perfil: política, varredura, cobertura, determinismo e contrato."""
    try:
        policy = load_policy(root)
    except HygieneError as error:
        return [str(error)]
    errors = policy_errors(policy)
    if errors:
        # Política quebrada reprova por si só: rodar a varredura sobre ela seria medir outra coisa.
        return errors
    try:
        report, problems = build_report(root, policy)
    except HygieneError as error:
        return [str(error)]
    errors = [f"varredura: {problem}" for problem in problems]
    errors.extend(coverage_errors(root, report, policy))
    errors.extend(determinism_errors(root, policy, report))
    errors.extend(schema_errors(report))
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
        f"{len(report['excluded'])} exclusao(oes) declarada(s), "
        f"relatorio {digest}, politica {DEFAULT_POLICY.as_posix()}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
