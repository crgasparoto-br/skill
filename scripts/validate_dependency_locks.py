#!/usr/bin/env python3
"""Validar lockfiles de dependência e a política de exceção, offline e deterministicamente.

O validador responde a três perguntas, todas offline e sem instalar nada:

1. o lockfile representa o manifest? Cada requisito declarado precisa aparecer com versão
   fixada que **satisfaz o especificador declarado**, e a cadeia `# via` de cada entrada
   transitiva precisa alcançar um pacote declarado;
2. cada entrada nomeia o artefato? O digest precisa referir-se a uma distribuição concreta,
   e por isso a entrada declara `# arquivo: <nome do artefato>`, cujo prefixo normalizado
   precisa corresponder ao nome e cujo texto precisa conter a versão. Sem isso, um hash
   sintaticamente válido e arbitrário passaria, e o lockfile teria a aparência de garantia
   sem garantia;
3. a política de exceção aponta algo que existe? Cada exceção precisa nomear pacote e versão
   presentes em algum lockfile, e a data de revisão precisa estar na forma `YYYY-MM-DD`.

A integridade do digest não é verificável sem o artefato, e o gate offline não a afirma: ele
verifica forma, vínculo entre nome, versão, artefato e digest, e a satisfação do
especificador. A verificação do digest contra o artefato real acontece onde o artefato pode
ser obtido, em `scripts/audit_dependencies.py` e no workflow de auditoria, que reprovam quando
não conseguem verificar.

É aviso, e não reprovação, a exceção cuja data de revisão venceu: data vencida é decisão de
pessoa e não defeito de arquivo.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.lock_dependencies import LOCK_SUFFIX, normalize  # noqa: E402

HASH_RE = re.compile(r"^--hash=sha256:([0-9a-f]{64})$")
ARTIFACT_RE = re.compile(r"^#\s*arquivo:\s*(\S+)$")
ENTRY_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._+!-]*)==([^\s\\,]+)$")
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.!+_-]*$")
VIA_RE = re.compile(r"^#\s*via\s+(.+)$")
SOURCE_RE = re.compile(r"^#\s*lockfile gerado de\s+(\S+)", re.MULTILINE)
REGENERATE_RE = re.compile(r"^#\s*regenerar:\s*(\S.*)$", re.MULTILINE)
REVIEW_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SPECIFIER_RE = re.compile(r"(===|==|!=|~=|<=|>=|<|>)\s*([0-9][0-9A-Za-z.!+*_-]*)")
OPERATORS = {"===", "==", "!=", "~=", "<=", ">=", "<", ">"}
UNSUPPORTED_OPERATORS = {"==="}
MIN_JUSTIFICATION = 20
POLICY_RELATIVE = "config/dependency-policy.json"
ARTIFACT_SUFFIXES = (".whl", ".tar.gz", ".zip", ".tar.bz2", ".tgz")


# --------------------------------------------------------------------------- versões


def version_key(text: str) -> tuple:
    """Chave de comparação PEP 440 suficiente para faixa declarada em manifest.

    Forma não reconhecida levanta `ValueError`, e quem chama reprova: um especificador que o
    gate não entende não pode virar aprovação silenciosa.
    """
    value = text.strip().lower()
    epoch = 0
    if "!" in value:
        head, value = value.split("!", 1)
        epoch = int(head)
    if "+" in value:
        value = value.split("+", 1)[0]
    match = re.match(r"^([0-9]+(?:\.[0-9]+)*)(.*)$", value)
    if not match:
        raise ValueError(text)
    release = tuple(int(part) for part in match.group(1).split("."))
    suffix = match.group(2)
    pre: tuple[int, int] | None = None
    post: int | None = None
    dev: int | None = None
    for label, number in re.findall(r"(a|b|c|rc|alpha|beta|pre|preview|\.post|\.dev|post|dev)([0-9]*)", suffix):
        count = int(number) if number else 0
        if label in {"a", "alpha"}:
            pre = (0, count)
        elif label in {"b", "beta"}:
            pre = (1, count)
        elif label in {"c", "rc", "pre", "preview"}:
            pre = (2, count)
        elif label in {".post", "post"}:
            post = count
        else:
            dev = count
    if dev is not None and pre is None and post is None:
        phase = (0, dev, 0)
    elif pre is not None:
        phase = (1, pre[0], pre[1])
    elif post is None:
        phase = (2, 0, 0)
    else:
        phase = (3, 0, post)
    return (epoch, release, phase)


def compare(left: str, right: str) -> int:
    """Comparar duas versões, preenchendo o release com zeros como a PEP 440 exige."""
    left_epoch, left_release, left_phase = version_key(left)
    right_epoch, right_release, right_phase = version_key(right)
    if left_epoch != right_epoch:
        return -1 if left_epoch < right_epoch else 1
    width = max(len(left_release), len(right_release))
    left_padded = left_release + (0,) * (width - len(left_release))
    right_padded = right_release + (0,) * (width - len(right_release))
    if left_padded != right_padded:
        return -1 if left_padded < right_padded else 1
    if left_phase == right_phase:
        return 0
    return -1 if left_phase < right_phase else 1


def satisfies(version: str, specifier: str) -> bool:
    """Versão satisfaz o especificador declarado, incluindo `~=` e curinga de release."""
    try:
        current = version
        for operator, target in SPECIFIER_RE.findall(specifier):
            if operator in UNSUPPORTED_OPERATORS:
                raise ValueError(f"operador nao suportado: {operator}")
            if target.endswith(".*"):
                prefix = target[:-2]
                if operator in {"==", "!="}:
                    match = compare(current, prefix) == 0 or (
                        current.startswith(prefix + ".") and len(current) > len(prefix)
                    )
                    if (operator == "==") != match:
                        return False
                    continue
                raise ValueError(f"curinga com operador {operator}")
            outcome = compare(current, target)
            if operator == "==" and outcome != 0:
                return False
            if operator == "!=" and outcome == 0:
                return False
            if operator == ">" and outcome <= 0:
                return False
            if operator == ">=" and outcome < 0:
                return False
            if operator == "<" and outcome >= 0:
                return False
            if operator == "<=" and outcome > 0:
                return False
            if operator == "~=":
                if outcome < 0:
                    return False
                release = version_key(target)[1]
                if len(release) < 2:
                    return False
                ceiling = list(release[:-1])
                ceiling[-1] += 1
                if compare(current, ".".join(str(part) for part in ceiling)) >= 0:
                    return False
        return True
    except ValueError:
        return False


def artifact_matches(name: str, version: str, filename: str) -> bool:
    """O artefato declarado corresponde ao nome fixado e contém a versão fixada."""
    stem = filename
    for suffix in ARTIFACT_SUFFIXES:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    head = re.split(r"-\d", stem, maxsplit=1)[0]
    if normalize(head) != name:
        return False
    return version in stem


# --------------------------------------------------------------------------- manifests


def read_requirements(path: Path, root: Path, seen: set[Path]) -> list[tuple[str, str, str]]:
    """Requisitos declarados: nome normalizado, especificador e marcador.

    Segue `-r` recursivamente, porque o lock de desenvolvimento precisa cobrir a união.
    """
    resolved = path.resolve()
    if resolved in seen or not path.is_file():
        return []
    seen.add(resolved)
    found: list[tuple[str, str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r"):
            target = line[2:].strip()
            if target:
                found.extend(read_requirements((path.parent / target).resolve(), root, seen))
            continue
        if line.startswith("-"):
            continue
        requirement, _, marker = line.partition(";")
        name_match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", requirement.strip())
        if not name_match:
            continue
        remainder = requirement.strip()[name_match.end():]
        remainder = re.sub(r"^\[[^\]]*\]", "", remainder)
        found.append((normalize(name_match.group(1)), remainder.strip(), marker.strip()))
    return found


# --------------------------------------------------------------------------- lockfile


def parse_lock(text: str) -> tuple[dict[str, dict], list[str]]:
    """Ler o lockfile e devolver as entradas e os erros de sintaxe."""
    entries: dict[str, dict] = {}
    errors: list[str] = []
    pending_via: set[str] = set()
    pending_artifact: str | None = None
    current: str | None = None

    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            via = VIA_RE.match(stripped)
            if via:
                pending_via = {normalize(part) for part in re.split(r"[,\s]+", via.group(1)) if part}
            artifact = ARTIFACT_RE.match(stripped)
            if artifact:
                pending_artifact = artifact.group(1)
            continue
        if not stripped:
            continue

        seen_entry = False
        for token in stripped.rstrip("\\").split():
            if token.startswith("--hash="):
                match = HASH_RE.match(token)
                if not match:
                    errors.append(f"linha {number}: hash fora do formato sha256: {token[:40]}")
                elif current is None:
                    errors.append(f"linha {number}: hash sem entrada")
                else:
                    entries[current]["hashes"].append(match.group(1))
                continue
            if token.startswith("--"):
                continue
            if seen_entry:
                errors.append(f"linha {number}: conteudo extra na entrada: {token[:40]}")
                continue
            seen_entry = True
            match = ENTRY_RE.match(token)
            if not match:
                errors.append(f"linha {number}: entrada sem versao exata: {token[:60]}")
                current = None
                continue
            name = normalize(match.group(1))
            if not VERSION_RE.match(match.group(2)):
                errors.append(f"linha {number}: versao nao exata: {match.group(2)}")
            if name in entries:
                errors.append(f"linha {number}: entrada duplicada: {name}")
            entries[name] = {
                "version": match.group(2),
                "hashes": [],
                "via": set(pending_via),
                "artifact": pending_artifact,
                "line": number,
            }
            pending_via = set()
            pending_artifact = None
            current = name

    return entries, errors


def locked_index(root: Path) -> dict[str, set[str]]:
    """Pacote -> versões fixadas em algum lockfile do repositório."""
    index: dict[str, set[str]] = {}
    for lock in root.glob(f"*/requirements*{LOCK_SUFFIX}"):
        if not lock.is_file():
            continue
        entries, _ = parse_lock(lock.read_text(encoding="utf-8"))
        for name, entry in entries.items():
            index.setdefault(name, set()).add(entry["version"])
    return index


def reaches_declared(name: str, entries: dict[str, dict], declared: set[str]) -> bool:
    """A entrada não declarada precisa ser alcançável a partir de um pacote declarado."""
    seen: set[str] = set()
    queue = [name]
    while queue:
        current = queue.pop()
        if current in declared:
            return True
        if current in seen:
            continue
        seen.add(current)
        queue.extend(entries.get(current, {}).get("via", ()))
    return False


def relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def validate_manifest(root: Path, manifest: Path) -> list[str]:
    errors: list[str] = []
    lock = manifest.with_name(manifest.stem + LOCK_SUFFIX)
    if not lock.is_file():
        return [f"{relative(manifest, root)}: falta o lockfile {relative(lock, root)}"]

    text = lock.read_text(encoding="utf-8")
    where = relative(lock, root)
    source = SOURCE_RE.search(text)
    if not source:
        errors.append(f"{where}: cabecalho sem o manifest de origem")
    elif source.group(1) != relative(manifest, root):
        errors.append(f"{where}: cabecalho aponta {source.group(1)}, esperado {relative(manifest, root)}")
    if not REGENERATE_RE.search(text):
        errors.append(f"{where}: cabecalho sem o comando de regeneracao")

    entries, parse_errors = parse_lock(text)
    errors.extend(f"{where}: {error}" for error in parse_errors)

    requirements = read_requirements(manifest, root, set())
    declared = {name for name, _, _ in requirements}
    for name in sorted(declared - set(entries)):
        errors.append(f"{where}: declarado em {relative(manifest, root)} e ausente do lockfile: {name}")

    for name, specifier, _ in requirements:
        entry = entries.get(name)
        if entry is None or not specifier:
            continue
        if not satisfies(entry["version"], specifier):
            errors.append(
                f"{where}: {name}=={entry['version']} nao satisfaz o especificador declarado "
                f"em {relative(manifest, root)}: {specifier}"
            )

    for name, entry in sorted(entries.items()):
        if not entry["hashes"]:
            errors.append(f"{where}: {name} sem hash sha256")
        if not entry["artifact"]:
            errors.append(f"{where}: {name} sem '# arquivo' declarando a distribuicao do hash")
        elif not artifact_matches(name, entry["version"], entry["artifact"]):
            errors.append(
                f"{where}: {name}=={entry['version']} declara artefato incompativel: {entry['artifact']}"
            )
        if name in declared:
            continue
        if not entry["via"]:
            errors.append(f"{where}: {name} nao declarado e sem anotacao '# via'")
            continue
        unknown = sorted(parent for parent in entry["via"] if parent not in entries)
        if unknown:
            errors.append(f"{where}: {name} anotado via pacote ausente do lockfile: {', '.join(unknown)}")
        if not reaches_declared(name, entries, declared):
            errors.append(f"{where}: {name} nao alcanca pacote declarado pela cadeia '# via'")

    return errors


def validate_policy(root: Path, locked: dict[str, set[str]]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    path = root / POLICY_RELATIVE
    if not path.is_file():
        return [f"{POLICY_RELATIVE}: ausente"], warnings

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{POLICY_RELATIVE}: JSON invalido: {error}"], warnings

    if data.get("schema_version") != 1:
        errors.append(f"{POLICY_RELATIVE}: schema_version esperado 1, encontrado {data.get('schema_version')!r}")
    exceptions = data.get("exceptions")
    if not isinstance(exceptions, list):
        return errors + [f"{POLICY_RELATIVE}: exceptions precisa ser lista"], warnings

    today = date.today().isoformat()
    seen: set[str] = set()
    for index, item in enumerate(exceptions):
        where = f"{POLICY_RELATIVE} excecao {index}"
        if not isinstance(item, dict):
            errors.append(f"{where}: precisa ser objeto")
            continue
        identifier = str(item.get("id", "")).strip()
        if not identifier:
            errors.append(f"{where}: sem id")
        elif identifier in seen:
            errors.append(f"{where}: id repetido: {identifier}")
        else:
            seen.add(identifier)

        if len(str(item.get("justification", "")).strip()) < MIN_JUSTIFICATION:
            errors.append(f"{where}: justificativa com menos de {MIN_JUSTIFICATION} caracteres")

        package = normalize(str(item.get("package", "")))
        version = str(item.get("version", "")).strip()
        if not package:
            errors.append(f"{where}: sem pacote")
        elif not version:
            errors.append(f"{where}: sem versao, e a tolerancia precisa nomear a versao fixada")
        elif package not in locked:
            errors.append(f"{where}: pacote {package} ausente dos lockfiles")
        elif version not in locked[package]:
            errors.append(
                f"{where}: versao {version} de {package} nao esta fixada em nenhum lockfile, "
                f"e a excecao precisa referenciar uma resolucao existente"
            )

        review = str(item.get("review_by", "")).strip()
        if not REVIEW_DATE_RE.match(review):
            errors.append(f"{where}: review_by precisa ser data YYYY-MM-DD, encontrado {review!r}")
        else:
            try:
                date.fromisoformat(review)
            except ValueError:
                errors.append(f"{where}: review_by nao e data valida: {review!r}")
            else:
                if review < today:
                    warnings.append(f"{where}: revisao vencida em {review}")

    return errors, warnings


def discover_manifests(root: Path) -> list[Path]:
    """Manifests de dependência: `requirements*.txt`, excluindo os próprios lockfiles."""
    return sorted(
        path
        for path in root.glob("*/requirements*.txt")
        if path.is_file() and not path.name.endswith(LOCK_SUFFIX)
    )


def validate_dependency_locks(root: Path) -> list[str]:
    """Todos os erros de lockfile e de política, para o validador agregador."""
    errors: list[str] = []
    for manifest in discover_manifests(root):
        errors.extend(validate_manifest(root, manifest))
    policy_errors, _ = validate_policy(root, locked_index(root))
    return errors + policy_errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validar lockfiles de dependencia e a politica de excecao.")
    parser.add_argument("--root", default=".", help="raiz do repositorio")
    parser.add_argument("--quiet", action="store_true", help="nao imprimir avisos")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    manifests = discover_manifests(root)
    errors = validate_dependency_locks(root)
    _, warnings = validate_policy(root, locked_index(root))

    for warning in warnings:
        if not args.quiet:
            print(f"AVISO: {warning}")
    for error in errors:
        print(f"ERRO: {error}", file=sys.stderr)

    if errors:
        print(f"validacao falhou: {len(errors)} erro(s)", file=sys.stderr)
        return 1

    suffix = f", {len(warnings)} aviso(s)" if warnings and not args.quiet else ""
    print(f"Validacao OK: {len(manifests)} manifest(s) com lockfile em sincronia, politica de excecao consistente{suffix}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
