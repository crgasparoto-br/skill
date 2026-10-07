#!/usr/bin/env python3
"""Validar lockfiles de dependência e a política de exceção, offline e deterministicamente.

O validador responde a três perguntas, todas offline e sem instalar nada:

1. o lockfile representa o manifest? Cada requisito declarado precisa aparecer com versão
   fixada que **satisfaz o especificador declarado**; um requisito cujo marcador de ambiente é
   falso no interpretador que executa o gate não é exigido, e um marcador que o gate não
   consegue avaliar reprova em vez de ser ignorado; inclusão `-r` que não resolve, não é
   manifest ou sai da raiz reprova, porque manifest que não pode ser lido não pode ser
   considerado coberto; e a cadeia `# via` de cada entrada transitiva precisa alcançar um
   pacote declarado;
2. cada entrada nomeia o artefato? O digest precisa referir-se a uma distribuição concreta, e
   por isso a entrada declara `# arquivo: <distribuição>`, cujo nome e versão precisam ser
   exatamente os fixados. Sem isso, um hash sintaticamente válido e arbitrário passaria, e o
   lockfile teria a aparência de garantia sem garantia;
3. a política de exceção aponta algo que existe? Cada exceção precisa nomear pacote e versão
   presentes em algum lockfile, e a data de revisão precisa estar na forma `YYYY-MM-DD`.

Gramática de versão, especificador, requisito, marcador e nome de distribuição é interpretada
pelo `packaging`, que é a implementação de referência das PEPs 440, 508 e 427: forma que ele
recusa reprova em vez de ser aproximada. O gate é offline e determinístico, e o `packaging` é
declarado como dependência de desenvolvimento justamente por ser a autoridade dessa gramática.

O cabeçalho registra o contexto de resolução como documentação, e não como autoridade: o
marcador é avaliado contra o interpretador que executa o gate, porque um comentário editável
como autoridade permitiria declarar contexto falso para omitir uma dependência real.

A integridade do digest não é verificável sem o artefato, e o gate offline não a afirma: ele
verifica forma, vínculo entre nome, versão, artefato e digest, e a satisfação do especificador.
A verificação do digest contra o artefato real acontece onde o artefato pode ser obtido, em
`scripts/audit_dependencies.py` e no workflow de auditoria, que reprovam quando não conseguem
verificar.

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

from packaging.markers import InvalidMarker, Marker, UndefinedEnvironmentName, default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.lock_dependencies import LOCK_SUFFIX  # noqa: E402

HASH_RE = re.compile(r"^--hash=sha256:([0-9a-f]{64})$")
ARTIFACT_RE = re.compile(r"^#\s*arquivo:\s*(\S+)$")
VIA_RE = re.compile(r"^#\s*via\s+(.+)$")
SOURCE_RE = re.compile(r"^#\s*lockfile gerado de\s+(\S+)", re.MULTILINE)
REGENERATE_RE = re.compile(r"^#\s*regenerar:\s*(\S.*)$", re.MULTILINE)
CONTEXT_RE = re.compile(r"^#\s*contexto:\s*python\s+(\S+)\s+em\s+(\S+)\s*(\S*)\s*$", re.MULTILINE)
REVIEW_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_JUSTIFICATION = 20
POLICY_RELATIVE = "config/dependency-policy.json"


# --------------------------------------------------------------------------- versões


def parse_version(text: str) -> Version:
    """Analisar a versão pela implementação de referência da PEP 440."""
    return Version(text)


def version_key(text: str) -> Version:
    """Compatibilidade com quem só precisa da ordem de versão."""
    return Version(text)


def compare(left: str, right: str) -> int:
    """Comparar duas versões e devolver -1, 0 ou 1."""
    left_version, right_version = Version(left), Version(right)
    if left_version == right_version:
        return 0
    return -1 if left_version < right_version else 1


def satisfies(version: str, specifier: str) -> bool:
    """A versão satisfaz o especificador declarado, na semântica do resolvedor.

    Especificador que o `packaging` recuse reprova, porque aproximar forma desconhecida seria
    aprovar sem verificar, e pré-lançamento não satisfaz faixa que não o mencione, que é o
    comportamento pelo qual o próprio resolvedor escolheria a versão.
    """
    try:
        return SpecifierSet(specifier).contains(version)
    except (InvalidSpecifier, InvalidVersion, ValueError):
        return False


def artifact_matches(name: str, version: str, filename: str) -> bool:
    """O artefato declarado é a distribuição fixada, pela gramática PEP 427 e da sdist.

    `parse_wheel_filename` e `parse_sdist_filename` verificam nome escapado, quantidade de
    campos e etiquetas, o que reprova `...-extra-py3-none-any.whl`, `...-fake.whl` e etiqueta
    com caractere inválido.
    """
    try:
        if filename.endswith(".whl"):
            artifact_name, artifact_version, *_ = parse_wheel_filename(filename)
        else:
            artifact_name, artifact_version = parse_sdist_filename(filename)
    except (InvalidWheelFilename, InvalidSdistFilename, ValueError):
        return False
    if canonicalize_name(artifact_name) != canonicalize_name(name):
        return False
    return str(artifact_version) == version


def exact_pin(token: str) -> tuple[str, str] | None:
    """Nome canônico e versão de uma entrada `nome==versão`, validados pelo `packaging`."""
    try:
        requirement = Requirement(token)
        if requirement.url or requirement.marker or len(requirement.specifier) != 1:
            return None
        specifier = next(iter(requirement.specifier))
        if specifier.operator != "==" or "*" in specifier.version:
            return None
    except (InvalidRequirement, InvalidSpecifier, ValueError):
        return None
    return canonicalize_name(requirement.name), specifier.version


# --------------------------------------------------------------------------- marcadores


def marker_environment() -> dict[str, str]:
    """Ambiente efetivo do gate, contra o qual o marcador é avaliado.

    A autoridade é o interpretador que executa a validação, e não o cabeçalho do lockfile: o
    cabeçalho é um comentário editável, e usá-lo como autoridade permitiria declarar um contexto
    falso para desativar um marcador verdadeiro e omitir uma dependência real.
    """
    return dict(default_environment())


def evaluate_marker(marker: str, environment: dict[str, str]) -> bool:
    """Avaliar o marcador com a gramática e a precedência da PEP 508.

    O marcador é construído por inteiro antes de qualquer avaliação, e por isso um nome que não
    existe na PEP 508 reprova mesmo quando o resultado lógico já estaria decidido.
    """
    try:
        return Marker(marker).evaluate(environment)
    except (InvalidMarker, UndefinedEnvironmentName, KeyError, ValueError) as error:
        raise ValueError(marker) from error


# --------------------------------------------------------------------------- manifests


def read_requirements(path: Path, root: Path, seen: set[Path], environment: dict[str, str],
                      errors: list[str], prefix: str) -> list[tuple[str, str, str]]:
    """Requisitos declarados: nome canônico, especificador e marcador.

    A linha é interpretada pelo `packaging`, que é a gramática PEP 508: linha que ele recusa
    reprova, porque texto que não pode ser lido não pode ser considerado coberto. Referência
    direta por URL também reprova, porque não se fixa por nome e versão. A inclusão `-r` é
    seguida recursivamente, e precisa permanecer sob a raiz do repositório.
    """
    resolved = path.resolve()
    if resolved in seen:
        errors.append(f"{prefix}: {relative(path, root)}: inclusao ciclica")
        return []
    if not path.is_file():
        errors.append(f"{prefix}: {relative(path, root)}: inclusao ausente ou ilegivel")
        return []
    seen.add(resolved)

    found: list[tuple[str, str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r") or line.startswith("--requirement"):
            target = re.sub(r"^(--requirement|-r)[=\s]+", "", line).strip()
            if not target:
                errors.append(f"{prefix}: {relative(path, root)}: inclusao sem destino")
                continue
            candidate = Path(target)
            if candidate.is_absolute():
                errors.append(f"{prefix}: {relative(path, root)}: inclusao absoluta fora da raiz: {target}")
                continue
            included = (path.parent / candidate).resolve()
            if not included.is_relative_to(root):
                errors.append(f"{prefix}: {relative(path, root)}: inclusao fora da raiz do repositorio: {target}")
                continue
            found.extend(read_requirements(included, root, seen, environment, errors, prefix))
            continue
        if line.startswith("-"):
            errors.append(f"{prefix}: {relative(path, root)}: opcao nao suportada pelo gate: {line[:40]}")
            continue
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            errors.append(f"{prefix}: {relative(path, root)}: linha de requisito nao interpretavel: {line[:60]}")
            continue
        if requirement.url:
            errors.append(f"{prefix}: {relative(path, root)}: referencia direta nao suportada pelo gate: {line[:60]}")
            continue
        marker = str(requirement.marker) if requirement.marker is not None else ""
        if marker:
            try:
                applies = evaluate_marker(marker, environment)
            except ValueError:
                errors.append(f"{prefix}: {relative(path, root)}: marcador nao avaliado pelo gate: {marker}")
                continue
            if not applies:
                continue
        found.append((canonicalize_name(requirement.name), str(requirement.specifier), marker))
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
                pending_via = {canonicalize_name(part) for part in re.split(r"[,\s]+", via.group(1)) if part}
            artifact = ARTIFACT_RE.match(stripped)
            if artifact:
                if pending_artifact is not None:
                    errors.append(f"linha {number}: anotacao '# arquivo' repetida antes da mesma entrada")
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
                # O lockfile só declara `--hash`: qualquer outra opção seria ignorada em
                # silêncio, e gramática permissiva é gramática que não verifica.
                errors.append(f"linha {number}: opcao nao suportada no lockfile: {token[:40]}")
                continue
            if seen_entry:
                errors.append(f"linha {number}: conteudo extra na entrada: {token[:40]}")
                continue
            seen_entry = True
            pinned = exact_pin(token)
            if pinned is None:
                errors.append(f"linha {number}: entrada sem versao exata: {token[:60]}")
                current = None
                continue
            name, version = pinned
            if name in entries:
                errors.append(f"linha {number}: entrada duplicada: {name}")
            entries[name] = {
                "version": version,
                "hashes": [],
                "via": set(pending_via),
                "artifact": pending_artifact,
                "line": number,
            }
            pending_via = set()
            pending_artifact = None
            current = name

    return entries, errors


def discover_lockfiles(root: Path) -> list[Path]:
    """Lockfiles esperados, inclusive symlink, para que nenhum passe despercebido."""
    return _discover(root, f"requirements*{LOCK_SUFFIX}")


def _discover(root: Path, pattern: str) -> list[Path]:
    """Manifest e lockfile do ferramental na raiz e dos skills um nível abaixo.

    Pattern: a descoberta de um único nível deixaria de fora o ferramental do catálogo, cujo
    manifest vive na raiz.
    """
    found = {
        path
        for candidate in (pattern, f"*/{pattern}")
        for path in root.glob(candidate)
        if path.is_file() or path.is_symlink()
    }
    return sorted(found)


def locked_index(root: Path) -> dict[str, set[str]]:
    """Pacote -> versões fixadas em lockfile confinado à raiz."""
    index: dict[str, set[str]] = {}
    for lock in discover_lockfiles(root):
        # Lockfile que resolve para fora da raiz não pode alimentar o índice da política.
        if not confined(lock, root):
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


def confined(path: Path, root: Path) -> bool:
    """O caminho resolvido permanece sob a raiz do repositório.

    Um manifest ou lockfile que seja symlink para fora da raiz faria o conjunto coberto vir de
    arquivo que o repositório não versiona, e a reprodutibilidade depende de o artefato
    verificado ser o artefato versionado.
    """
    try:
        return path.resolve().is_relative_to(root)
    except OSError:
        return False


def relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def validate_manifest(root: Path, manifest: Path) -> list[str]:
    errors: list[str] = []
    if not confined(manifest, root):
        return [f"{relative(manifest, root)}: manifest resolve para fora da raiz do repositorio"]
    if not manifest.is_file():
        return [f"{relative(manifest, root)}: manifest ausente, pendente ou nao regular"]
    lock = manifest.with_name(manifest.stem + LOCK_SUFFIX)
    if not lock.is_file():
        return [f"{relative(manifest, root)}: falta o lockfile {relative(lock, root)}"]
    if not confined(lock, root):
        return [f"{relative(lock, root)}: lockfile resolve para fora da raiz do repositorio"]

    text = lock.read_text(encoding="utf-8")
    where = relative(lock, root)
    source = SOURCE_RE.search(text)
    if not source:
        errors.append(f"{where}: cabecalho sem o manifest de origem")
    elif source.group(1) != relative(manifest, root):
        errors.append(f"{where}: cabecalho aponta {source.group(1)}, esperado {relative(manifest, root)}")
    if not REGENERATE_RE.search(text):
        errors.append(f"{where}: cabecalho sem o comando de regeneracao")
    if not CONTEXT_RE.search(text):
        errors.append(f"{where}: cabecalho sem o contexto de resolucao")

    entries, parse_errors = parse_lock(text)
    errors.extend(f"{where}: {error}" for error in parse_errors)

    requirements = read_requirements(manifest, root, set(), marker_environment(), errors, where)
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
    if not confined(path, root):
        return [f"{POLICY_RELATIVE}: resolve para fora da raiz do repositorio"], warnings

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

        package = canonicalize_name(str(item.get("package", "")))
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
    """Manifests de dependência: `requirements*.txt`, excluindo os próprios lockfiles.

    Symlink pendente e symlink para diretório continuam sendo manifest esperado: omiti-los faria
    uma mudança de manifest deixar de ser verificada sem erro.
    """
    return [
        path
        for path in _discover(root, "requirements*.txt")
        if not path.name.endswith(LOCK_SUFFIX)
    ]


def validate_dependency_locks(root: Path) -> list[str]:
    """Todos os erros de lockfile e de política, para o validador agregador."""
    errors: list[str] = []
    manifests = discover_manifests(root)
    # O pareamento é nominal, e não por caminho resolvido: um segundo lockfile que seja symlink
    # para o par existente continuaria sendo um lockfile sem manifest correspondente.
    paired = {manifest.with_name(manifest.stem + LOCK_SUFFIX) for manifest in manifests}
    for manifest in manifests:
        errors.extend(validate_manifest(root, manifest))
    for lock in discover_lockfiles(root):
        if not confined(lock, root):
            errors.append(f"{relative(lock, root)}: lockfile resolve para fora da raiz do repositorio")
        elif lock not in paired:
            errors.append(f"{relative(lock, root)}: lockfile sem manifest correspondente")
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