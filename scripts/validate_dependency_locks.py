#!/usr/bin/env python3
"""Validar lockfiles de dependência e a política de exceção, offline e deterministicamente.

O validador responde a três perguntas, todas offline e sem instalar nada:

1. o lockfile representa o manifest? Cada requisito declarado precisa aparecer com versão
   fixada que **satisfaz o especificador declarado**; um requisito cujo marcador de ambiente é
   falso no contexto registrado não é exigido, e um marcador que o gate não consegue avaliar
   reprova em vez de ser ignorado; inclusão `-r` que não resolve reprova, porque um manifest
   que não pode ser lido não pode ser considerado coberto; e a cadeia `# via` de cada entrada
   transitiva precisa alcançar um pacote declarado;
2. cada entrada nomeia o artefato? O digest precisa referir-se a uma distribuição concreta, e
   por isso a entrada declara `# arquivo: <distribuição>`, cujo prefixo normalizado precisa
   corresponder ao nome, cujo texto precisa conter a versão e cujo sufixo precisa ser de
   distribuição. Sem isso, um hash sintaticamente válido e arbitrário passaria, e o lockfile
   teria a aparência de garantia sem garantia;
3. a política de exceção aponta algo que existe? Cada exceção precisa nomear pacote e versão
   presentes em algum lockfile, e a data de revisão precisa estar na forma `YYYY-MM-DD`.

Versão e especificador são analisados por completo: forma que o gate não entende levanta erro e
reprova, em vez de ser aproximada. O contexto registrado no cabeçalho é o ambiente em que o
lockfile foi resolvido, e é contra ele que os marcadores são avaliados.

A integridade do digest não é verificável sem o artefato, e o gate offline não a afirma: ele
verifica forma, vínculo entre nome, versão, artefato e digest, e a satisfação do
especificador. A verificação do digest contra o artefato real acontece onde o artefato pode ser
obtido, em `scripts/audit_dependencies.py` e no workflow de auditoria, que reprovam quando não
conseguem verificar.

É aviso, e não reprovação, a exceção cuja data de revisão venceu: data vencida é decisão de
pessoa e não defeito de arquivo.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
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
CONTEXT_RE = re.compile(r"^#\s*contexto:\s*python\s+(\S+)\s+em\s+(\S+)\s*(\S*)\s*$", re.MULTILINE)
REVIEW_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SPECIFIER_TOKEN_RE = re.compile(r"^(===|==|!=|~=|<=|>=|<|>)\s*([^\s,]+)")
VERSION_TOKEN_RE = re.compile(r"\.?(a|b|c|rc|alpha|beta|pre|preview|post|dev)([0-9]*)")
LOCAL_RE = re.compile(r"^[0-9a-z]+(?:[._-][0-9a-z]+)*$")
REQUIREMENT_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*([^;\s].*?)?\s*$")
MARKER_ATOM_RE = re.compile(
    r'^(python_version|python_full_version|sys_platform|platform_system|os_name|platform_machine|implementation_name)'
    r'\s*(==|!=|<=|>=|<|>|in|not in)\s*"([^"]*)"$'
)
UNSUPPORTED_OPERATORS = {"==="}
MIN_JUSTIFICATION = 20
POLICY_RELATIVE = "config/dependency-policy.json"
ARTIFACT_SUFFIXES = (".whl", ".tar.gz", ".zip", ".tar.bz2", ".tgz")
VERSION_NAMES = {"python_version", "python_full_version"}


# --------------------------------------------------------------------------- versões


def parse_version(text: str) -> tuple:
    """Analisar a versão por completo; forma não reconhecida levanta `ValueError`.

    Devolve época, release, fase de pré/pós/dev e o segmento local, que precisa ser preservado
    porque `1.0+abc` e `1.0+def` não são a mesma versão.
    """
    value = text.strip().lower()
    if not value:
        raise ValueError(text)
    epoch = 0
    if "!" in value:
        head, value = value.split("!", 1)
        if not head.isdigit():
            raise ValueError(text)
        epoch = int(head)
    local: tuple[str, ...] = ()
    if "+" in value:
        value, local_text = value.split("+", 1)
        if not LOCAL_RE.match(local_text):
            raise ValueError(text)
        local = tuple(re.split(r"[._-]", local_text))
    match = re.match(r"^([0-9]+(?:\.[0-9]+)*)(.*)$", value)
    if not match:
        raise ValueError(text)
    release = tuple(int(part) for part in match.group(1).split("."))
    suffix = match.group(2)
    pre: tuple[int, int] | None = None
    post: int | None = None
    dev: int | None = None
    position = 0
    rank = 0
    kinds: set[str] = set()
    while position < len(suffix):
        token = VERSION_TOKEN_RE.match(suffix, position)
        if not token:
            raise ValueError(text)
        label, number = token.group(1), token.group(2)
        count = int(number) if number else 0
        if label in {"a", "alpha"}:
            kind, value = "pre", (0, count)
        elif label in {"b", "beta"}:
            kind, value = "pre", (1, count)
        elif label in {"c", "rc", "pre", "preview"}:
            kind, value = "pre", (2, count)
        elif label == "post":
            kind, value = "post", count
        else:
            kind, value = "dev", count
        # A PEP 440 admite no máximo um sufixo de cada tipo, na ordem pré, pós e dev:
        # `50.0.2post1a1` não é versão válida e não pode passar como se fosse.
        order = {"pre": 1, "post": 2, "dev": 3}[kind]
        if order < rank or kind in kinds:
            raise ValueError(text)
        rank = order
        kinds.add(kind)
        if kind == "pre":
            pre = value
        elif kind == "post":
            post = value
        else:
            dev = value
        position = token.end()
    if dev is not None and pre is None and post is None:
        phase = (0, dev, 0)
    elif pre is not None:
        phase = (1, pre[0], pre[1])
    elif post is None:
        phase = (2, 0, 0)
    else:
        phase = (3, 0, post)
    return (epoch, release, phase, local)


def version_key(text: str) -> tuple:
    """Compatibilidade com quem só precisa da ordem de release."""
    epoch, release, phase, _ = parse_version(text)
    return (epoch, release, phase)


def compare_local(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    """Comparar segmentos locais: segmento numérico é maior que segmento alfabético."""
    for index in range(max(len(left), len(right))):
        current = left[index] if index < len(left) else None
        other = right[index] if index < len(right) else None
        if current == other:
            continue
        if current is None:
            return -1
        if other is None:
            return 1
        current_numeric, other_numeric = current.isdigit(), other.isdigit()
        if current_numeric and other_numeric:
            return -1 if int(current) < int(other) else 1
        if current_numeric != other_numeric:
            return 1 if current_numeric else -1
        return -1 if current < other else 1
    return 0


def compare(left: str, right: str) -> int:
    """Comparar duas versões.

    O release é preenchido com zeros, como a PEP 440 exige, e o segmento local só é comparado
    quando os dois lados o declaram: `1.0+abc` e `1.0` são iguais para faixa, e `1.0+abc` e
    `1.0+def` não são iguais entre si.
    """
    left_epoch, left_release, left_phase, left_local = parse_version(left)
    right_epoch, right_release, right_phase, right_local = parse_version(right)
    if left_epoch != right_epoch:
        return -1 if left_epoch < right_epoch else 1
    width = max(len(left_release), len(right_release))
    left_padded = left_release + (0,) * (width - len(left_release))
    right_padded = right_release + (0,) * (width - len(right_release))
    if left_padded != right_padded:
        return -1 if left_padded < right_padded else 1
    if left_phase != right_phase:
        return -1 if left_phase < right_phase else 1
    if left_local and right_local:
        return compare_local(left_local, right_local)
    return 0


def parse_specifier(text: str) -> list[tuple[str, str]]:
    """Consumir o especificador por inteiro; sobra ou forma desconhecida levanta erro."""
    remaining = text.strip()
    parsed: list[tuple[str, str]] = []
    while remaining:
        match = SPECIFIER_TOKEN_RE.match(remaining)
        if not match:
            raise ValueError(text)
        parsed.append((match.group(1), match.group(2)))
        remaining = remaining[match.end():].lstrip()
        if remaining.startswith(","):
            remaining = remaining[1:].lstrip()
            if not remaining:
                raise ValueError(text)
        elif remaining:
            raise ValueError(text)
    if not parsed:
        raise ValueError(text)
    return parsed


def satisfies(version: str, specifier: str) -> bool:
    """Versão satisfaz o especificador declarado, incluindo `~=` e curinga de release.

    Qualquer forma que o gate não entenda devolve `False`, porque aproximar especificador
    desconhecido seria aprovar sem verificar.
    """
    try:
        current = version
        for operator, target in parse_specifier(specifier):
            if operator in UNSUPPORTED_OPERATORS:
                raise ValueError(f"operador nao suportado: {operator}")
            # A PEP 440 não permite versão local em comparador ordenado nem com curinga.
            if "+" in target and operator not in {"==", "!="}:
                raise ValueError(f"versao local em operador ordenado: {target}")
            if target.endswith(".*"):
                prefix = target[:-2]
                if operator not in {"==", "!="}:
                    raise ValueError(f"curinga com operador {operator}")
                if "+" in prefix:
                    raise ValueError(f"curinga com versao local: {target}")
                matches = compare(current, prefix) == 0 or (
                    current.startswith(prefix + ".") and len(current) > len(prefix)
                )
                if (operator == "==") != matches:
                    return False
                continue
            outcome = compare(current, target)
            target_local = parse_version(target)[3]
            current_local = parse_version(current)[3]
            # A PEP 440 só ignora o segmento local quando o alvo não declara um: com alvo
            # local, `==` exige o mesmo local e `!=` exige local diferente.
            if operator == "==" and (outcome != 0 or (target_local and current_local != target_local)):
                return False
            if operator == "!=" and outcome == 0 and (not target_local or current_local == target_local):
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
    """O artefato declarado é uma distribuição do pacote fixado, na versão fixada."""
    if not filename.endswith(ARTIFACT_SUFFIXES):
        return False
    stem = filename
    for suffix in ARTIFACT_SUFFIXES:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    # Sufixo repetido (`pacote-1.0.0-py3-none-any.whl.whl`) não é uma distribuição publicada.
    if any(stem.endswith(suffix) for suffix in ARTIFACT_SUFFIXES):
        return False
    # A distribuição nomeia o pacote e a versão em campos separados: comparar por substring
    # aceitaria `cryptography-50.0.20` para a versão 50.0.2.
    parts = stem.split("-")
    if len(parts) < 2:
        return False
    if normalize(parts[0]) != name:
        return False
    return parts[1] == version


# --------------------------------------------------------------------------- marcadores


def marker_environment() -> dict[str, str]:
    """Ambiente efetivo do gate, contra o qual o marcador é avaliado.

    A autoridade é o interpretador que executa a validação, e não o cabeçalho do lockfile: o
    cabeçalho é um comentário editável, e usá-lo como autoridade permitiria declarar um
    contexto falso para desativar um marcador verdadeiro e omitir uma dependência.
    """
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        "python_full_version": version,
        "sys_platform": sys.platform,
        "platform_system": platform.system(),
        "os_name": os.name,
        "platform_machine": platform.machine(),
        "implementation_name": sys.implementation.name,
    }


def evaluate_marker(marker: str, environment: dict[str, str]) -> bool:
    """Avaliar marcador simples de `and`/`or`; o que não é avaliável levanta `ValueError`."""
    text = marker.strip()
    if not text:
        return True
    # `and` liga mais forte que `or`: avaliar da esquerda para a direita inverteria o
    # resultado de expressões mistas e faria o gate exigir ou dispensar o pacote errado.
    groups: list[list[str]] = []
    for group in re.split(r"\s+or\s+", text):
        atoms = [atom.strip() for atom in re.split(r"\s+and\s+", group)]
        # A gramática é validada por inteiro antes de qualquer atalho lógico: um átomo que o
        # gate não entende precisa reprovar mesmo quando o resultado já estaria decidido, senão
        # uma dependência poderia ser escondida atrás de expressão que o gate não avalia.
        for atom in atoms:
            match = MARKER_ATOM_RE.match(atom)
            if not match or match.group(1) not in environment:
                raise ValueError(atom)
        groups.append(atoms)
    for atoms in groups:
        if all(evaluate_marker_atom(atom, environment) for atom in atoms):
            return True
    return False


def evaluate_marker_atom(atom: str, environment: dict[str, str]) -> bool:
    match = MARKER_ATOM_RE.match(atom.strip())
    if not match:
        raise ValueError(atom)
    name, operator, expected = match.groups()
    actual = environment.get(name)
    if actual is None:
        raise ValueError(name)
    if operator == "in":
        return actual in expected
    if operator == "not in":
        return actual not in expected
    if name in VERSION_NAMES:
        outcome = compare(actual, expected)
        equal = outcome == 0
    else:
        outcome = -1 if actual < expected else (0 if actual == expected else 1)
        equal = outcome == 0
    if operator == "==":
        return equal
    if operator == "!=":
        return not equal
    return {"<": outcome < 0, "<=": outcome <= 0, ">": outcome > 0, ">=": outcome >= 0}[operator]


# --------------------------------------------------------------------------- manifests


def read_requirements(path: Path, root: Path, seen: set[Path], environment: dict[str, str] | None,
                      errors: list[str], prefix: str) -> list[tuple[str, str, str]]:
    """Requisitos declarados: nome normalizado, especificador e marcador.

    Segue `-r` recursivamente, porque o lock de desenvolvimento precisa cobrir a união, e uma
    inclusão que não resolve é erro: um manifest que não pode ser lido não pode ser considerado
    coberto.
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
            resolved = (path.parent / candidate).resolve()
            if not resolved.is_relative_to(root):
                errors.append(f"{prefix}: {relative(path, root)}: inclusao fora da raiz do repositorio: {target}")
                continue
            found.extend(read_requirements(resolved, root, seen, environment, errors, prefix))
            continue
        if line.startswith("-"):
            errors.append(f"{prefix}: {relative(path, root)}: opcao nao suportada pelo gate: {line[:40]}")
            continue
        requirement, _, marker = line.partition(";")
        name_match = REQUIREMENT_RE.match(requirement.strip())
        if not name_match:
            errors.append(f"{prefix}: {relative(path, root)}: linha de requisito nao interpretavel: {line[:60]}")
            continue
        if marker.strip():
            try:
                applies = evaluate_marker(marker, environment)
            except ValueError:
                errors.append(f"{prefix}: {relative(path, root)}: marcador nao avaliado pelo gate: {marker.strip()}")
                continue
            if not applies:
                continue
        found.append((normalize(name_match.group(1)), (name_match.group(3) or "").strip(), marker.strip()))
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
            match = ENTRY_RE.match(token)
            if not match:
                errors.append(f"linha {number}: entrada sem versao exata: {token[:60]}")
                current = None
                continue
            name = normalize(match.group(1))
            if not VERSION_RE.match(match.group(2)):
                errors.append(f"linha {number}: versao nao exata: {match.group(2)}")
            else:
                try:
                    parse_version(match.group(2))
                except ValueError:
                    errors.append(f"linha {number}: versao fora da forma PEP 440: {match.group(2)}")
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
    environment = marker_environment()

    entries, parse_errors = parse_lock(text)
    errors.extend(f"{where}: {error}" for error in parse_errors)

    requirements = read_requirements(manifest, root, set(), environment, errors, where)
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
