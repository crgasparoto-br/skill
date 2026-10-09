#!/usr/bin/env python3
"""Validate public release versioning and skill compatibility declarations."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .catalog import ROOT, catalog_skill_ids, load_catalog
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT, catalog_skill_ids, load_catalog

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
VERSION_FILE_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\n$")
LINEAGE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$")
RELEASE_LINE = "main"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def parse_semver(value: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.fullmatch(value)
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.groups())
    except ValueError:
        # SemVer nao fixa teto, mas a conversao de inteiros tem limite e precisa de recusa controlada.
        return None


def parse_lineage(value: str) -> tuple[date, int] | None:
    if not isinstance(value, str) or not LINEAGE_RE.fullmatch(value):
        return None
    try:
        parsed_date = date.fromisoformat(value[:10])
    except ValueError:
        return None
    suffix = int(value[11:])
    if suffix <= 0:
        return None
    return parsed_date, suffix


def validate_json_schema(schema_path: Path, document_path: Path, label: str) -> list[str]:
    if not schema_path.is_file():
        return [f"{label}: schema is missing: {schema_path}"]
    if not document_path.is_file():
        return [f"{label}: document is missing: {document_path}"]
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import SchemaError
    except ImportError:
        return [f"{label}: jsonschema dependency unavailable; schema validation cannot be skipped"]
    try:
        schema = load_json(schema_path)
        document = load_json(document_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"{label}: cannot load schema or document: {exc}"]
    try:
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
    except SchemaError as exc:
        return [f"{label}: schema is invalid: {exc.message}"]
    try:
        schema_errors = sorted(validator.iter_errors(document), key=lambda item: list(item.path))
    except (SchemaError, TypeError, ValueError) as exc:
        return [f"{label}: schema is invalid or cannot be evaluated: {exc}"]
    return [
        f"{label}: {'/'.join(str(part) for part in error.path) or '$'}: {error.message}"
        for error in schema_errors
    ]


def _git_bytes(root: Path, *arguments: str) -> tuple[int, bytes]:
    """Executa git na raiz auditada e devolve codigo e saida crua, sem levantar excecao."""
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        return 127, str(exc).encode("utf-8", "backslashreplace")
    return completed.returncode, completed.stdout


def _git_output(root: Path, *arguments: str) -> tuple[int, str]:
    """Executa git e decodifica a saida; conteudo nao decodificavel vira erro controlado."""
    code, raw = _git_bytes(root, *arguments)
    try:
        return code, raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return 127, "saida do git nao e UTF-8 valido"


def _effective_ref(root: Path, ref: str | None) -> str | None:
    """Determina a referencia sob validacao: parametro explicito, ambiente de CI ou branch atual."""
    if ref is not None:
        return ref
    from_ci = os.environ.get("GITHUB_REF_NAME")
    if from_ci:
        return from_ci
    code, output = _git_output(root, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0 or not output or output == "HEAD":
        return None
    return output


RELEASE_REF_FORMS = frozenset({
    "main",
    "refs/heads/main",
    "origin/main",
    "refs/remotes/origin/main",
})


def _release_line(value: str) -> str | None:
    """Reconhece somente formas inequivocas da linha de release.

    Formas genericas como `feature/main` ou `release/main` nao podem ser tratadas como a linha de
    release: isso reprovaria promocao legitima de uma branch comum cujo ultimo componente e `main`.
    """
    return RELEASE_LINE if value.strip() in RELEASE_REF_FORMS else None


README_LABEL = "Release do catálogo:"
ROADMAP_LABEL = "Release atual:"
README_CANONICAL_RE = re.compile(
    r"^\*\*Release do catálogo:\*\* \[[`*]*([0-9]+\.[0-9]+\.[0-9]+)[`*]*\]\(\./VERSION\)"
)
ROADMAP_CANONICAL_RE = re.compile(
    r"^> \*\*Release atual:\*\* [`]?v([0-9]+\.[0-9]+\.[0-9]+)[`]?\s*$"
)
VERSION_DECLARATION_RE = re.compile(
    r"\bVERSION\b\s*(?:\||=)\s*`?([0-9]+\.[0-9]+\.[0-9]+)`?\s*(?:\||$)"
)
CANONICAL_DOC_ROW_RE = re.compile(
    r"^\| `VERSION` \| `([0-9]+\.[0-9]+\.[0-9]+)` \|", re.MULTILINE
)
CHANGELOG_HEADING_RE = re.compile(
    r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - ([0-9]{4}-[0-9]{2}-[0-9]{2})$",
    re.MULTILINE,
)


RELEASE_TAG_RE = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def _masked_text(text: str) -> str:
    """Remove blocos de codigo e comentarios HTML, preservando a numeracao de linha."""
    sem_comentarios = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    linhas = sem_comentarios.splitlines()
    saida: list[str] = []
    dentro = ""
    for linha in linhas:
        marca = linha.strip()[:3]
        if not dentro and marca in {"```", "~~~"}:
            dentro = marca
            saida.append("")
            continue
        if dentro:
            if linha.strip().startswith(dentro):
                dentro = ""
            saida.append("")
            continue
        saida.append(linha)
    return "\n".join(saida)


def _visible_lines(text: str) -> list[tuple[int, str]]:
    """Devolve as linhas efetivamente renderizadas, com o numero da linha."""
    return [
        (numero, linha)
        for numero, linha in enumerate(_masked_text(text).splitlines(), start=1)
        if linha.strip()
    ]


def _label_surface_errors(
    caminho: Path, rotulo_arquivo: str, rotulo: str, canonico: re.Pattern[str], release_version: str
) -> list[str]:
    """Toda linha com o rotulo precisa ser a declaracao canonica da versao publicada."""
    if not caminho.is_file():
        return [f"{rotulo_arquivo} is missing"]
    erros: list[str] = []
    declaracoes: list[str] = []
    for numero, linha in _visible_lines(caminho.read_text(encoding="utf-8")):
        if rotulo not in linha:
            continue
        achado = canonico.match(linha)
        if achado is None:
            erros.append(
                f"{rotulo_arquivo}:{numero}: declares {rotulo} in a non canonical form: "
                f"{linha.strip()}"
            )
            continue
        outras = [
            token
            for token in re.findall(r"v?([0-9]+\.[0-9]+\.[0-9]+)", linha)
            if token not in {achado.group(1), release_version}
        ]
        if outras:
            erros.append(
                f"{rotulo_arquivo}:{numero}: declares {rotulo} with a conflicting version "
                f"{sorted(set(outras))}"
            )
            continue
        declaracoes.append(achado.group(1))
    if erros:
        return erros
    if not declaracoes:
        return [
            f"{rotulo_arquivo} is stale: it does not declare the current release {release_version}"
        ]
    if len(declaracoes) > 1:
        return [f"{rotulo_arquivo} declares the release more than once: {sorted(declaracoes)}"]
    if declaracoes[0] != release_version:
        return [
            f"{rotulo_arquivo} is stale: it declares {declaracoes[0]} instead of {release_version}"
        ]
    return []


def _release_doc_version_errors(texto: str, release_version: str) -> list[str]:
    """Declaracoes de VERSION no documento de release precisam ser unicas e coerentes."""
    erros: list[str] = []
    declaradas: list[str] = []
    for numero, linha in _visible_lines(texto):
        if not re.search(r"\bVERSION\b\s*(?:\||=)", linha):
            continue
        achado = VERSION_DECLARATION_RE.search(linha)
        if achado is None:
            erros.append(
                "docs/RELEASE.md declares VERSION without a complete version at line "
                f"{numero}: {linha.strip()}"
            )
            continue
        declaradas.append(achado.group(1))
        if achado.group(1) != release_version:
            erros.append(
                f"docs/RELEASE.md declares VERSION {achado.group(1)} at line {numero} "
                f"instead of {release_version}"
            )
    if len(declaradas) > 1:
        erros.append(f"docs/RELEASE.md declares VERSION more than once: {sorted(declaradas)}")
    return erros


def _highest_release_tag(root: Path, target: str) -> str:
    """Escolhe a maior tag de release alcancavel, para nao depender da ordem do `git describe`."""
    code, output = _git_output(root, "tag", "--merged", target, "--list", "v*")
    if code != 0 or not output:
        return ""
    candidatas: list[tuple[tuple[int, int, int], str]] = []
    for linha in output.splitlines():
        nome = linha.strip()
        if not RELEASE_TAG_RE.fullmatch(nome):
            continue
        parsed = parse_semver(nome[1:])
        if parsed is not None:
            candidatas.append((parsed, nome))
    if not candidatas:
        return ""
    return max(candidatas)[1]


def _resolve_release_tag(
    root: Path, target: str, informed: str | None
) -> tuple[str, list[str]]:
    """Resolve e valida a tag de release: existente, anotada e no formato vMAJOR.MINOR.PATCH."""
    tag = _highest_release_tag(root, target) if informed is None else informed
    if not tag:
        return "", [
            f"release alignment: nenhuma tag de release vMAJOR.MINOR.PATCH alcancavel a partir de "
            f"{target}; busque as tags do repositorio antes de validar a linha de release"
        ]
    if ":" in tag or tag.strip() != tag:
        return "", [
            f"release alignment: a tag informada {tag!r} nao e um nome lexical valido de tag"
        ]
    if not RELEASE_TAG_RE.fullmatch(tag):
        return "", [
            f"release alignment: a tag {tag} precisa seguir o formato vMAJOR.MINOR.PATCH"
        ]
    object_code, object_type = _git_output(root, "cat-file", "-t", f"refs/tags/{tag}")
    if object_code != 0:
        return "", [
            f"release alignment: a tag {tag} nao existe em refs/tags; "
            "a versao publicada nao pode ser conferida"
        ]
    if object_type != "tag":
        return "", [
            f"release alignment: a tag {tag} precisa ser anotada; "
            "uma tag leve nao registra a versao publicada"
        ]
    tagged_code, tagged_raw = _git_bytes(root, "show", f"{tag}:VERSION")
    esperado = f"{tag[1:]}\n".encode()
    if tagged_code != 0 or tagged_raw != esperado:
        return "", [
            f"release alignment: a tag {tag} aponta para um commit cujo VERSION nao e "
            f"{tag[1:]}; a tag publicada nao identifica a versao declarada"
        ]
    ancestor_code, _ = _git_output(root, "merge-base", "--is-ancestor", tag, target)
    if ancestor_code != 0:
        return "", [
            f"release alignment: a tag {tag} nao e ancestral de {target}; "
            "a tag foi movida ou o historico diverge da versao publicada"
        ]
    return tag, []


def _target_release_version(root: Path, target: str) -> tuple[str, list[str]]:
    """Le a versao publicada da propria revisao alvo e confere a forma canonica do arquivo."""
    version_code, version_raw = _git_bytes(root, "show", f"{target}:VERSION")
    if version_code != 0:
        return "", [
            f"release alignment: VERSION da revisao {target} nao pode ser lido; "
            "a versao publicada nao pode ser conferida"
        ]
    try:
        version_text = version_raw.decode("utf-8")
    except UnicodeDecodeError:
        return "", [
            f"release alignment: VERSION da revisao {target} nao e UTF-8 valido; "
            "a versao publicada nao pode ser conferida"
        ]
    if not VERSION_FILE_RE.fullmatch(version_text):
        return "", [
            f"release alignment: VERSION da revisao {target} deve conter apenas a versao "
            "e uma quebra de linha final"
        ]
    head_code, head_sha = _git_output(root, "rev-parse", "HEAD")
    target_code, target_sha = _git_output(root, "rev-parse", target)
    if head_code == 0 and target_code == 0 and head_sha == target_sha:
        try:
            tree_bytes = (root / "VERSION").read_bytes()
        except OSError as exc:
            return "", [f"release alignment: VERSION da arvore nao pode ser lido: {exc}"]
        if tree_bytes != version_raw:
            return "", [
                "release alignment: a arvore de trabalho e a revisao alvo declaram VERSION "
                "diferentes; valide a mesma revisao em todas as superficies"
            ]
    return version_text[:-1], []


def _version_comparison_problems(
    target: str, tag: str, release_version: str, commits: int
) -> list[str]:
    """Compara a versao declarada com a tag publicada, conforme existam commits novos."""
    published = parse_semver(tag[1:])
    if published is None:
        return [f"release alignment: a tag {tag} precisa seguir o formato vMAJOR.MINOR.PATCH"]
    current = parse_semver(release_version)
    if current is None:
        return []
    if commits == 0:
        if current != published:
            return [
                f"release alignment: a versao publicada {release_version} diverge da tag {tag} "
                "sem commits novos na linha de release"
            ]
        return []
    if current <= published:
        return [
            f"release alignment: {target} avancou {commits} commit(s) alem de {tag} "
            f"sem incremento da versao publicada (VERSION={release_version}); "
            "publique uma versao que identifique o conteudo promovido"
        ]
    return []


def release_alignment_errors(
    root: Path = ROOT,
    ref: str | None = None,
    release_version: str | None = None,
    tag: str | None = None,
) -> list[str]:
    """Confere que o conteudo publicado na linha de release e identificavel por uma versao.

    A checagem vale apenas para a linha de release, ou seja, a branch `main`. A promocao de
    `develop` para `main` que avanca commits sem incrementar a versao publicada deixaria a linha
    principal sem identificacao de versao, porque a tag continuaria apontando para o conteudo
    anterior; esse cenario e recusado. A verificacao e fail-closed: sem repositorio git, sem tag
    alcancavel, em clone raso, sem ancestralidade ou, no CI, sem referencia determinavel, a
    conformidade nao e presumida.

    `tag` permite informar a tag publicada em vez de deixa-la para a descoberta automatica, que so
    devolve tag alcancavel; o valor informado tambem precisa ser tag anotada existente no formato
    canonico. A costura existe para conferir o caminho de divergencia de ancestralidade.
    """
    target = _effective_ref(root, ref)
    if target is None:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            return [
                "release alignment: a linha de release nao pode ser determinada no CI; "
                "informe a referencia ou faca checkout da linha de release"
            ]
        return []
    if ref is None and os.environ.get("GITHUB_REF_NAME"):
        branch_code, branch = _git_output(root, "rev-parse", "--abbrev-ref", "HEAD")
        if (
            branch_code == 0
            and branch
            and branch != "HEAD"
            and _release_line(branch) != _release_line(target)
        ):
            return [
                "release alignment: a referencia do CI "
                f"{target} diverge da revisao checada {branch}; "
                "a linha de release nao pode ser validada nesse contexto"
            ]
    if _release_line(target) is None:
        return []
    inside_code, _ = _git_output(root, "rev-parse", "--is-inside-work-tree")
    if inside_code != 0:
        return [
            "release alignment: a linha de release nao esta em repositorio git; "
            "a tag publicada e o historico nao podem ser conferidos"
        ]
    shallow_code, shallow_output = _git_output(root, "rev-parse", "--is-shallow-repository")
    if shallow_code != 0:
        return [
            "release alignment: nao foi possivel determinar se o clone e raso; "
            "a tag publicada nao pode ser conferida com seguranca"
        ]
    if shallow_output == "true":
        return [
            "release alignment: clone raso nao permite conferir a tag publicada; "
            "use fetch-depth: 0 antes de validar a linha de release"
        ]
    tag, problemas = _resolve_release_tag(root, target, tag)
    if problemas:
        return problemas
    count_code, count_output = _git_output(root, "rev-list", "--count", f"{tag}..{target}")
    if count_code != 0 or not count_output.isdigit():
        return [f"release alignment: nao foi possivel contar os commits de {tag} ate {target}"]
    versao_alvo, problemas = _target_release_version(root, target)
    if problemas:
        return problemas
    if release_version is not None and release_version != versao_alvo:
        return [
            "release alignment: a versao informada "
            f"{release_version} diverge da revisao alvo {target}, que declara {versao_alvo}"
        ]
    release_version = versao_alvo
    return _version_comparison_problems(target, tag, release_version, int(count_output))



def validate_versioning(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    version_path = root / "VERSION"
    compatibility_path = root / "config" / "compatibility.json"
    changelog_path = root / "CHANGELOG.md"
    release_doc = root / "docs" / "RELEASE.md"
    if not version_path.is_file():
        return ["VERSION is missing"]
    try:
        raw_bytes = version_path.read_bytes()
    except OSError as exc:
        return [f"VERSION cannot be read: {exc}"]
    try:
        raw_version = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return ["VERSION must be valid UTF-8"]
    if not VERSION_FILE_RE.fullmatch(raw_version):
        errors.append(
            "VERSION must contain only MAJOR.MINOR.PATCH and a single trailing newline"
        )
    release_version = raw_version[:-1] if raw_version.endswith("\n") else raw_version.strip()
    release_semver = parse_semver(release_version)
    if release_semver is None:
        errors.append("VERSION must use MAJOR.MINOR.PATCH SemVer")
    if not compatibility_path.is_file():
        errors.append("config/compatibility.json is missing")
        return errors
    try:
        compatibility = load_json(compatibility_path)
        catalog = load_catalog(root)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [*errors, f"versioning manifest is invalid: {exc}"]

    if compatibility.get("release_version") != release_version:
        errors.append("compatibility release_version differs from VERSION")
    errors.extend(validate_json_schema(
        root / "schemas" / "compatibility.schema.json",
        compatibility_path,
        "compatibility schema",
    ))
    errors.extend(release_alignment_errors(root))
    if compatibility.get("system") != "skill-compatibility" or compatibility.get("schema_version") != 1:
        errors.append("compatibility manifest identity is invalid")
    release_date = compatibility.get("release_date")
    try:
        date.fromisoformat(str(release_date))
    except (TypeError, ValueError):
        errors.append("compatibility release_date must be ISO-8601")
    catalog_version = compatibility.get("catalog_version")
    if compatibility.get("catalog_version") != catalog.get("catalog_version"):
        errors.append("compatibility catalog_version differs from skills catalog")
    if parse_lineage(str(catalog_version)) is None:
        errors.append("compatibility catalog_version must use a valid YYYY-MM-DD.N date")
    compatibility_system_version = compatibility.get("system_version")
    if parse_lineage(str(compatibility_system_version)) is None:
        errors.append("compatibility system_version must use a valid YYYY-MM-DD.N date")
    for relative, label in (
        ("config/skill-system-requirements.json", "requirements"),
        (".github/skill-system-capabilities.json", "capabilities"),
    ):
        path = root / relative
        if not path.is_file():
            errors.append(f"{label}: manifest is missing")
            continue
        try:
            source_version = load_json(path).get("system_version")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{label}: manifest is invalid: {exc}")
            continue
        if source_version != compatibility_system_version:
            errors.append(f"compatibility system_version differs from {label} manifest")
    policy = compatibility.get("contract_policy")
    if not isinstance(policy, dict):
        errors.append("contract_policy is missing")
        policy = {}
    if policy.get("scheme") != "semver":
        errors.append("contract_policy scheme must be semver")
    public_contract = policy.get("public_contract_version")
    if not isinstance(public_contract, str) or parse_semver(public_contract) is None:
        errors.append("public_contract_version must use SemVer")
    internal_lineage = policy.get("internal_lineage_version")
    if parse_lineage(str(internal_lineage)) is None:
        errors.append("internal_lineage_version must use a valid YYYY-MM-DD.N date")
    mappings = policy.get("mappings")
    if not isinstance(mappings, list) or not mappings:
        errors.append("contract_policy mappings must be non-empty")
    else:
        if not any(
            isinstance(mapping, dict)
            and mapping.get("public_contract_version") == public_contract
            and mapping.get("internal_lineage_version") == internal_lineage
            and mapping.get("status") == "supported"
            for mapping in mappings
        ):
            errors.append("contract_policy lacks a supported current mapping")

    skills = compatibility.get("skills")
    expected_ids = catalog_skill_ids(catalog)
    actual_ids = {
        item.get("id") for item in skills if isinstance(item, dict)
    } if isinstance(skills, list) else set()
    if actual_ids != expected_ids:
        errors.append(f"compatibility skills differ from catalog: expected={sorted(expected_ids)} actual={sorted(actual_ids)}")
    if isinstance(skills, list):
        for item in skills:
            if not isinstance(item, dict):
                errors.append("compatibility skills contains a non-object")
                continue
            skill_id = item.get("id")
            if skill_id not in expected_ids:
                continue
            if item.get("public_contract_version") != public_contract:
                errors.append(f"{skill_id}: public contract version differs from policy")
            if item.get("internal_lineage_version") != internal_lineage:
                errors.append(f"{skill_id}: internal lineage differs from policy")
            if parse_lineage(str(item.get("internal_lineage_version"))) is None:
                errors.append(f"{skill_id}: internal lineage must use a valid YYYY-MM-DD.N date")
            min_release = parse_semver(str(item.get("min_release")))
            if min_release is None:
                errors.append(f"{skill_id}: min_release must use SemVer")
            elif release_semver is not None and min_release > release_semver:
                errors.append(f"{skill_id}: min_release cannot be newer than release")
            version_path = root / str(skill_id) / "contracts" / "version.json"
            if version_path.is_file():
                try:
                    internal = load_json(version_path).get("contract_version")
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    errors.append(f"{skill_id}: invalid contracts/version.json: {exc}")
                else:
                    if internal != item.get("internal_lineage_version"):
                        errors.append(f"{skill_id}: compatibility lineage differs from contracts/version.json")
            else:
                errors.append(f"{skill_id}: contracts/version.json is missing")

    adapters = compatibility.get("adapters")
    adapter_manifest_path = root / "config" / "platform-adapters.json"
    adapter_manifest: dict[str, Any] = {}
    if not adapter_manifest_path.is_file():
        errors.append("config/platform-adapters.json is missing while compatibility adapters are declared")
    else:
        try:
            adapter_manifest = load_json(adapter_manifest_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"platform adapter manifest is invalid: {exc}")
            adapter_manifest = {}
        expected_adapter_ids = {
            item.get("id") for item in adapter_manifest.get("adapters", [])
            if isinstance(item, dict)
        }
        actual_adapter_ids = {
            item.get("id") for item in adapters
            if isinstance(item, dict)
        } if isinstance(adapters, list) else set()
        if isinstance(adapters, list) and len(actual_adapter_ids) != len(adapters):
            errors.append("compatibility adapter IDs must be unique")
        if actual_adapter_ids != expected_adapter_ids:
            errors.append(
                f"compatibility adapters differ from platform manifest: expected={sorted(expected_adapter_ids)} actual={sorted(actual_adapter_ids)}"
            )
        if isinstance(adapters, list):
            for item in adapters:
                if not isinstance(item, dict):
                    errors.append("compatibility adapters contains a non-object")
                    continue
                adapter_id = item.get("id")
                adapter_min = parse_semver(str(item.get("min_release")))
                if adapter_min is None:
                    errors.append(f"{adapter_id}: adapter min_release must use SemVer")
                elif release_semver is not None and adapter_min > release_semver:
                    errors.append(f"{adapter_id}: adapter min_release cannot be newer than release")
                manifest_item = next(
                    (candidate for candidate in adapter_manifest.get("adapters", [])
                     if isinstance(candidate, dict) and candidate.get("id") == adapter_id),
                    None,
                )
                if not isinstance(manifest_item, dict) or manifest_item.get("introduced_in") != item.get("min_release"):
                    errors.append(f"{adapter_id}: compatibility min_release differs from platform introduced_in")

    if not changelog_path.is_file():
        errors.append("CHANGELOG.md is missing")
    else:
        changelog_text = changelog_path.read_text(encoding="utf-8")
        cabecalhos = CHANGELOG_HEADING_RE.findall(changelog_text)
        correntes = [data for versao, data in cabecalhos if versao == release_version]
        if not cabecalhos:
            errors.append(
                f"CHANGELOG.md lacks release heading ## [{release_version}] - YYYY-MM-DD"
            )
        for versao, data in cabecalhos:
            try:
                date.fromisoformat(data)
            except ValueError:
                errors.append(
                    f"CHANGELOG.md release heading has an invalid date: {versao} - {data}"
                )
        if len(correntes) > 1:
            errors.append(
                f"CHANGELOG.md declares the release [{release_version}] more than once"
            )
        if not correntes:
            errors.append(
                f"CHANGELOG.md lacks release heading ## [{release_version}] - YYYY-MM-DD"
            )
        elif len(correntes) == 1 and str(release_date) != correntes[0]:
            errors.append(
                "CHANGELOG.md release date differs from compatibility release_date: "
                f"{correntes[0]} != {release_date}"
            )
    errors.extend(
        _label_surface_errors(
            root / "README.md", "README.md", README_LABEL, README_CANONICAL_RE, release_version
        )
    )
    errors.extend(
        _label_surface_errors(
            root / "docs" / "ROADMAP.md",
            "docs/ROADMAP.md",
            ROADMAP_LABEL,
            ROADMAP_CANONICAL_RE,
            release_version,
        )
    )
    if not release_doc.is_file():
        errors.append("docs/RELEASE.md is missing")
    else:
        release_text = release_doc.read_text(encoding="utf-8")
        expected_doc_values = (
            f"| `VERSION` | `{release_version}` |",
            f"| `config/skills-catalog.json.catalog_version` | `{catalog.get('catalog_version')}` |",
            f"| `config/skill-system-requirements.json.system_version` | `{compatibility.get('system_version')}` |",
            "config/platform-adapters.json",
            release_version,
        )
        for expected in expected_doc_values:
            if expected not in release_text:
                errors.append(f"docs/RELEASE.md is stale or missing: {expected}")
        errors.extend(_release_doc_version_errors(release_text, release_version))
        compatibility_by_id = {
            item.get("id"): item for item in adapters
            if isinstance(item, dict)
        } if isinstance(adapters, list) else {}
        for manifest_item in adapter_manifest.get("adapters", []):
            if not isinstance(manifest_item, dict):
                continue
            adapter_id = manifest_item.get("id")
            compatibility_item = compatibility_by_id.get(adapter_id, {})
            expected_row = f"| `{adapter_id}` | `{manifest_item.get('introduced_in')}` | `{compatibility_item.get('status')}` |"
            if expected_row not in release_text:
                errors.append(f"docs/RELEASE.md is stale or missing adapter row: {expected_row}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--ref",
        default=None,
        help=(
            "referencia a conferir no alinhamento da versao publicada; "
            "por padrao usa GITHUB_REF_NAME ou a branch atual"
        ),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate_versioning(root)
    if args.ref is not None:
        errors.extend(release_alignment_errors(root, ref=args.ref))
    if errors:
        print("Versioning validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Versioning validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
