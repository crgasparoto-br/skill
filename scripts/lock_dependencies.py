#!/usr/bin/env python3
"""Gera lockfile de dependências a partir do manifest de uma skill.

O repositório declarava dependências com faixa aberta, como `cryptography>=50.0.1`, e o CI
instalava a faixa. A versão que roda na CI não era a versão que roda na máquina de quem
executa a sequência local, e nenhuma das duas era registrada. Sem registro, uma diferença
de resolução entre dois ambientes muda o resultado da auditoria sem que nada no
repositório mude.

Este utilitário resolve o manifest e escreve, ao lado dele, um lockfile com versão exata e
hash de cada distribuição do fechamento transitivo. Ele é utilitário de manutenção: usa
rede, e por isso não participa da sequência de validação obrigatória.

O lockfile é derivado, nunca fonte de verdade. Alteração de dependência começa no manifest,
e `scripts/validate_dependency_locks.py` reprova lockfile dessincronizado.

Cada entrada declara `# via` quando é transitiva e `# arquivo: <distribuição>` antes da
própria linha, para que o digest tenha um artefato nomeado a que se referir: um hash
sintaticamente válido e arbitrário não pode passar como garantia.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

LOCK_SUFFIX = ".lock.txt"
NORMALIZE_RE = re.compile(r"[-_.]+")
ENTRY_LINE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+?)\s*\\?$")
VIA_LINE_RE = re.compile(r"^#\s*via\s+(.+)$")
def normalize(name: str) -> str:
    """Nome normalizado conforme PEP 503."""
    return NORMALIZE_RE.sub("-", name.strip().lower())


def requirement_name(line: str) -> str | None:
    """Extrair o nome de uma linha de requisito, ignorando comentário, extra e marcador.

    Devolve None para linha vazia, comentário, opção e inclusão `-r`.
    """
    stripped = line.split("#", 1)[0].strip()
    if not stripped or stripped.startswith("-"):
        return None
    name = re.split(r"[<>=!~;\[\s]", stripped, maxsplit=1)[0].strip()
    return normalize(name) if name else None


def declared_names(manifest: Path, root: Path) -> set[str]:
    """Nomes declarados no manifest, seguindo `-r` recursivamente."""
    names: set[str] = set()
    seen: set[Path] = set()

    def walk(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            return
        seen.add(resolved)
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.split("#", 1)[0].strip()
            if stripped.startswith("-r"):
                target = stripped[2:].strip()
                if target:
                    walk((path.parent / target).resolve())
                continue
            name = requirement_name(line)
            if name:
                names.add(name)

    walk(manifest)
    return names


def resolve(manifest: Path) -> dict:
    """Resolver o manifest com pip e devolver o relatório de instalação."""
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        command = [
            sys.executable, "-m", "pip", "install",
            "--quiet", "--dry-run", "--ignore-installed",
            "--report", str(report), "-r", str(manifest),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0 or not report.is_file():
            raise SystemExit(
                f"falha ao resolver {manifest}:\n{completed.stderr.strip()[-2000:]}"
            )
        return json.loads(report.read_text(encoding="utf-8"))


def parents_of(report: dict) -> dict[str, set[str]]:
    """Mapa pacote -> quem o requer, a partir de `requires_dist` de cada instalação."""
    parents: dict[str, set[str]] = {}
    provides: dict[str, list[str]] = {}
    for item in report["install"]:
        name = normalize(item["metadata"]["name"])
        provides[name] = item["metadata"].get("requires_dist") or []
    for name, requires in provides.items():
        for requirement in requires:
            child = requirement_name(requirement)
            if child and child in provides and child != name:
                parents.setdefault(child, set()).add(name)
    return parents


def artifact_hash(item: dict) -> tuple[str, str]:
    """Hash e nome do arquivo da distribuição escolhida na resolução."""
    download = item.get("download_info", {})
    archive = download.get("archive_info", {})
    value = str(archive.get("hash") or "")
    if value.startswith("sha256="):
        value = "sha256:" + value[len("sha256="):]
    filename = str(download.get("url") or "").rsplit("/", 1)[-1]
    return value, filename


def build_lock(manifest: Path, root: Path, report: dict) -> str:
    declared = declared_names(manifest, root)
    parents = parents_of(report)
    entries: dict[str, tuple[str, str, str, set[str]]] = {}
    for item in report["install"]:
        metadata = item["metadata"]
        name = normalize(metadata["name"])
        version = str(metadata["version"])
        digest, filename = artifact_hash(item)
        entries[name] = (version, digest, filename, parents.get(name, set()))

    relative = manifest.relative_to(root).as_posix()
    lines = [
        f"# lockfile gerado de {relative}",
        f"# contexto: python {platform.python_version()} em {platform.system().lower()} {platform.machine()}",
        f"# regenerar: python scripts/lock_dependencies.py --manifest {relative}",
        "# nao editar a mao: alterar o manifest e regenerar",
        "",
    ]
    for name in sorted(entries):
        version, digest, filename, requirement_parents = entries[name]
        if name not in declared and requirement_parents:
            lines.append(f"# via {', '.join(sorted(requirement_parents))}")
        lines.append(f"# arquivo: {filename}")
        lines.append(f"{name}=={version} \\")
        lines.append(f"    --hash={digest}")
    return "\n".join(lines) + "\n"


def lock_path(manifest: Path) -> Path:
    return manifest.with_name(manifest.stem + LOCK_SUFFIX)


def context_line() -> str:
    """Linha de contexto do lockfile para o ambiente que executa o gerador."""
    return f"# contexto: python {platform.python_version()} em {platform.system().lower()} {platform.machine()}"


def closure_of(text: str) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    """Fechamento resolvido: nome, versão e arestas `# via`, sem o que é do ambiente.

    O contexto de resolução, o nome do artefato escolhido e o digest são do ambiente que
    resolveu, e por isso não entram nesta comparação: o que precisa ser o do manifest é o
    conjunto de pacotes, as versões e as arestas de dependência que o manifest produz.
    """
    versions: dict[str, str] = {}
    parents: dict[str, frozenset[str]] = {}
    pending: frozenset[str] = frozenset()
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            via = VIA_LINE_RE.match(stripped)
            if via:
                pending = frozenset(
                    normalize(part) for part in re.split(r"[,\s]+", via.group(1)) if part
                )
            continue
        match = ENTRY_LINE_RE.match(stripped)
        if match:
            name = normalize(match.group(1))
            versions[name] = match.group(2)
            parents[name] = pending
            pending = frozenset()
    return versions, parents


def manifests_for(root: Path, skill: str | None) -> list[Path]:
    # O ferramental do catálogo tem manifest na raiz, e os skills um nível abaixo: cobrir apenas
    # um dos dois deixaria manifest sem lockfile.
    patterns = (f"{skill}/requirements*.txt",) if skill else ("requirements*.txt", "*/requirements*.txt")
    return sorted(
        {
            path
            for pattern in patterns
            for path in root.glob(pattern)
            if path.is_file() and not path.name.endswith(LOCK_SUFFIX)
        }
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gerar lockfile de dependências de uma skill.")
    parser.add_argument("--root", default=".", help="raiz do repositório")
    parser.add_argument("--skill", help="skill específica; sem isso, todas")
    parser.add_argument("--manifest", help="manifest específico, relativo à raiz; sem isso, todos")
    parser.add_argument("--check", action="store_true", help="não escrever; falhar se o lock mudaria")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if args.manifest:
        # O cabeçalho do lockfile manda regenerar por manifest: selecionar um caminho fora da raiz
        # deixaria o gerador escrever onde não deve, então o caminho é confinado antes de tudo.
        if Path(args.manifest).is_absolute():
            print(f"manifest precisa ser caminho relativo a raiz: {args.manifest}", file=sys.stderr)
            return 1
        candidate = (root / args.manifest).resolve()
        if not candidate.is_file() or (candidate != root and root not in candidate.parents):
            print(f"manifest fora da raiz ou inexistente: {args.manifest}", file=sys.stderr)
            return 1
        manifests = [candidate]
    else:
        manifests = manifests_for(root, args.skill)
    if not manifests:
        print("nenhum manifest encontrado", file=sys.stderr)
        return 1

    drifted: list[str] = []
    notes: list[str] = []
    for manifest in manifests:
        content = build_lock(manifest, root, resolve(manifest))
        target = lock_path(manifest)
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if args.check:
            where = target.relative_to(root).as_posix()
            if closure_of(current) != closure_of(content):
                drifted.append(where)
            elif current != content:
                # O fechamento coincide e o restante difere: ou o contexto do lockfile é de outro
                # ambiente, e então o artefato e o digest são verificados por
                # `scripts/audit_dependencies.py` contra o artefato real, ou o contexto é deste
                # ambiente, e o lockfile precisa ser idêntico ao que o gerador produz.
                if context_line() in current:
                    drifted.append(where)
                else:
                    notes.append(
                        f"{where}: contexto de outro ambiente; fechamento conferido e artefato "
                        "verificado pela auditoria de dependencias"
                    )
            continue
        target.write_text(content, encoding="utf-8")
        print(f"escrito {target.relative_to(root).as_posix()}")

    if args.check:
        for note in notes:
            print(f"AVISO: {note}", file=sys.stderr)
        if drifted:
            for path in drifted:
                print(f"lockfile dessincronizado: {path}", file=sys.stderr)
            return 1
        print("Lockfiles sincronizados: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
