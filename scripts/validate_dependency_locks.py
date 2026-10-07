#!/usr/bin/env python3
"""Validar lockfiles de dependência e a política de exceção, offline e deterministicamente.

O validador responde a uma pergunta só: o lockfile ao lado do manifest representa o que o
manifest declara? Ele não consulta índice, não instala pacote e não usa rede. A checagem de
vulnerabilidade é assunto de `scripts/audit_dependencies.py`, que depende de banco externo e
por isso não participa da sequência obrigatória.

Reprovam: manifest sem lockfile, lockfile sem cabeçalho de origem, pacote declarado ausente
do lockfile, entrada sem versão exata, entrada sem hash, entrada não declarada sem anotação
`# via`, anotação apontando pacote ausente do lockfile, entrada não alcançável a partir de um
pacote declarado, entrada duplicada e exceção de política malformada.

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

from scripts.lock_dependencies import LOCK_SUFFIX, declared_names, normalize  # noqa: E402

HASH_RE = re.compile(r"^--hash=sha256:([0-9a-f]{64})$")
ENTRY_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._+!-]*)==([^\s\\,]+)$")
VERSION_RE = re.compile(r"^[0-9][0-9A-Za-z.!+_-]*$")
VIA_RE = re.compile(r"^#\s*via\s+(.+)$")
SOURCE_RE = re.compile(r"^#\s*lockfile gerado de\s+(\S+)", re.MULTILINE)
REGENERATE_RE = re.compile(r"^#\s*regenerar:\s*(\S.*)$", re.MULTILINE)
MIN_JUSTIFICATION = 20
POLICY_RELATIVE = "config/dependency-policy.json"


def parse_lock(text: str) -> tuple[dict[str, dict], list[str]]:
    """Ler o lockfile e devolver as entradas e os erros de sintaxe."""
    entries: dict[str, dict] = {}
    errors: list[str] = []
    pending_via: set[str] = set()
    current: str | None = None

    for number, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            via = VIA_RE.match(stripped)
            if via:
                pending_via = {normalize(part) for part in re.split(r"[,\s]+", via.group(1)) if part}
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
                "line": number,
            }
            pending_via = set()
            current = name

    return entries, errors


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

    declared = declared_names(manifest, root)
    for name in sorted(declared - set(entries)):
        errors.append(f"{where}: declarado em {relative(manifest, root)} e ausente do lockfile: {name}")

    for name, entry in sorted(entries.items()):
        if not entry["hashes"]:
            errors.append(f"{where}: {name} sem hash sha256")
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


def discover_manifests(root: Path) -> list[Path]:
    """Manifests de dependência: `requirements*.txt`, excluindo os próprios lockfiles."""
    return sorted(
        path
        for path in root.glob("*/requirements*.txt")
        if path.is_file() and not path.name.endswith(LOCK_SUFFIX)
    )


def locked_names(root: Path) -> set[str]:
    """Nomes fixados em algum lockfile do repositório."""
    locked: set[str] = set()
    for lock in root.glob(f"*/requirements*{LOCK_SUFFIX}"):
        if lock.is_file():
            entries, _ = parse_lock(lock.read_text(encoding="utf-8"))
            locked.update(entries)
    return locked


def validate_dependency_locks(root: Path) -> list[str]:
    """Todos os erros de lockfile e de política, para o validador agregador."""
    errors: list[str] = []
    for manifest in discover_manifests(root):
        errors.extend(validate_manifest(root, manifest))
    policy_errors, _ = validate_policy(root, locked_names(root))
    return errors + policy_errors


def validate_policy(root: Path, locked: set[str]) -> tuple[list[str], list[str]]:
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
        if not package:
            errors.append(f"{where}: sem pacote")
        elif package not in locked:
            errors.append(f"{where}: pacote {package} ausente dos lockfiles")

        review = str(item.get("review_by", "")).strip()
        try:
            date.fromisoformat(review)
        except ValueError:
            errors.append(f"{where}: review_by precisa ser data ISO YYYY-MM-DD, encontrado {review!r}")
        else:
            if review < today:
                warnings.append(f"{where}: revisao vencida em {review}")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validar lockfiles de dependencia e a politica de excecao.")
    parser.add_argument("--root", default=".", help="raiz do repositorio")
    parser.add_argument("--quiet", action="store_true", help="nao imprimir avisos")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    manifests = discover_manifests(root)
    errors = validate_dependency_locks(root)
    _, warnings = validate_policy(root, locked_names(root))

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
