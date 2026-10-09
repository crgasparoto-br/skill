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
LINEAGE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$")
RELEASE_LINE = "main"


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def parse_semver(value: str) -> tuple[int, int, int] | None:
    match = SEMVER_RE.fullmatch(value)
    return tuple(int(part) for part in match.groups()) if match else None


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


def _git_output(root: Path, *arguments: str) -> tuple[int, str]:
    """Executa git na raiz auditada e devolve codigo e saida, sem levantar excecao."""
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return 127, str(exc)
    return completed.returncode, completed.stdout.strip()


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


def _release_line(value: str) -> str:
    """Normaliza a referencia para o nome da linha: main, origin/main e refs/heads/main equivalem."""
    candidate = value.strip()
    for prefix in ("refs/heads/", "refs/remotes/", "refs/tags/"):
        candidate = candidate.removeprefix(prefix)
    if "/" in candidate:
        candidate = candidate.split("/", 1)[1]
    return candidate


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
    alcancavel ou em clone raso, a conformidade nao e presumida.

    `tag` permite informar a tag publicada em vez de deixa-la para `git describe`, que so devolve
    tag alcancavel; a costura existe para conferir o caminho de divergencia de ancestralidade.
    """
    target = _effective_ref(root, ref)
    if target is None or _release_line(target) != RELEASE_LINE:
        return []
    errors: list[str] = []
    inside_code, _ = _git_output(root, "rev-parse", "--is-inside-work-tree")
    if inside_code != 0:
        return [
            "release alignment: a linha de release nao esta em repositorio git; "
            "a tag publicada e o historico nao podem ser conferidos"
        ]
    shallow_code, shallow_output = _git_output(root, "rev-parse", "--is-shallow-repository")
    if shallow_code != 0:
        errors.append(
            "release alignment: nao foi possivel determinar se o clone e raso; "
            "a tag publicada nao pode ser conferida com seguranca"
        )
        return errors
    if shallow_output == "true":
        errors.append(
            "release alignment: clone raso nao permite conferir a tag publicada; "
            "use fetch-depth: 0 antes de validar a linha de release"
        )
        return errors
    if tag is None:
        tag_code, resolved_tag = _git_output(root, "describe", "--tags", "--abbrev=0", target)
        tag = resolved_tag if tag_code == 0 else ""
    if not tag:
        errors.append(
            f"release alignment: nenhuma tag alcancavel a partir de {target}; "
            "busque as tags do repositorio antes de validar a linha de release"
        )
        return errors
    ancestor_code, _ = _git_output(root, "merge-base", "--is-ancestor", tag, target)
    if ancestor_code != 0:
        errors.append(
            f"release alignment: a tag {tag} nao e ancestral de {target}; "
            "a tag foi movida ou o historico diverge da versao publicada"
        )
        return errors
    count_code, count_output = _git_output(root, "rev-list", "--count", f"{tag}..{target}")
    if count_code != 0 or not count_output.isdigit():
        errors.append(
            f"release alignment: nao foi possivel contar os commits de {tag} ate {target}"
        )
        return errors
    if int(count_output) == 0:
        return errors
    if release_version is None:
        version_path = root / "VERSION"
        if not version_path.is_file():
            return [*errors, "release alignment: VERSION is missing"]
        try:
            release_version = version_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            return [*errors, f"release alignment: VERSION cannot be read: {exc}"]
    published = parse_semver(tag[1:]) if tag[:1] in {"v", "V"} else parse_semver(tag)
    current = parse_semver(release_version)
    if published is None:
        errors.append(f"release alignment: a tag {tag} nao identifica uma versao SemVer")
        return errors
    if current is None:
        return errors
    if current <= published:
        errors.append(
            f"release alignment: {target} avancou {count_output} commit(s) alem de {tag} "
            f"sem incremento da versao publicada (VERSION={release_version}); "
            "publique uma versao que identifique o conteudo promovido"
        )
    return errors


def validate_versioning(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    version_path = root / "VERSION"
    compatibility_path = root / "config" / "compatibility.json"
    changelog_path = root / "CHANGELOG.md"
    release_doc = root / "docs" / "RELEASE.md"
    if not version_path.is_file():
        return ["VERSION is missing"]
    try:
        release_version = version_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return [f"VERSION cannot be read: {exc}"]
    if parse_semver(release_version) is None:
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
    errors.extend(release_alignment_errors(root, release_version=release_version))
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
            if parse_semver(str(item.get("min_release"))) is None:
                errors.append(f"{skill_id}: min_release must use SemVer")
            elif parse_semver(str(item.get("min_release"))) > parse_semver(release_version):
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
                if parse_semver(str(item.get("min_release"))) is None:
                    errors.append(f"{adapter_id}: adapter min_release must use SemVer")
                elif parse_semver(str(item.get("min_release"))) > parse_semver(release_version):
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
    elif f"[{release_version}]" not in changelog_path.read_text(encoding="utf-8"):
        errors.append(f"CHANGELOG.md lacks release [{release_version}]")
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
