#!/usr/bin/env python3
"""Validate the repository-level invariants of the skills catalog."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = {
    "auditar-issue",
    "corrigir-ci",
    "design-interface",
    "documentacao-repositorio",
    "entregar-issue",
    "fluxos-conversacionais",
    "revisar-issue",
}
SYSTEM_VERSION = "2026-09-26.1"
GLOBAL_FILES = {
    "docs/SKILL_SYSTEM_SPEC.md",
    "docs/SECURITY.md",
    "config/skill-system-requirements.json",
    ".github/skill-system-capabilities.json",
}
REQUIRED_CAPABILITIES = {
    "canonical_controller": "entregar-issue",
    "canonical_contract_owner": "entregar-issue",
    "independent_auditor": "auditar-issue",
    "ci_remediator": "corrigir-ci",
    "exact_head_evidence": "required",
    "fail_closed_on_unknown": "enabled",
    "bounded_remediation": "enabled",
    "progressive_context_loading": "enabled",
    "context_insufficient_blocking": "enabled",
    "shared_contract_sync": "enabled",
    "independent_read_only_audit": "enabled",
    "automatic_merge": "disabled",
    "destructive_actions_by_default": "disabled",
}


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def load_json(path: Path, label: str, errors: list[str]) -> dict | None:
    if not path.is_file():
        fail(f"{label} ausente", errors)
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{label} inválido: {exc}", errors)
        return None
    if not isinstance(value, dict):
        fail(f"{label} deve conter objeto JSON", errors)
        return None
    return value


def validate_file_ref(ref: str, requirement_id: str, errors: list[str]) -> None:
    if not ref.startswith("file:"):
        return
    target = ROOT / ref.removeprefix("file:")
    if not target.exists():
        fail(f"{requirement_id}: referência local inexistente: {ref}", errors)


def validate_global_governance(errors: list[str]) -> None:
    for relative in sorted(GLOBAL_FILES):
        if not (ROOT / relative).is_file():
            fail(f"artefato global ausente: {relative}", errors)

    spec = ROOT / "docs" / "SKILL_SYSTEM_SPEC.md"
    if spec.is_file():
        text = spec.read_text(encoding="utf-8")
        required_terms = (
            "Hierarquia de fontes",
            "Fail closed",
            "Sem autoridade implícita de merge",
            "Contexto suficiente",
            "Observabilidade sem fabricação",
        )
        for term in required_terms:
            if term not in text:
                fail(f"SKILL_SYSTEM_SPEC.md não declara seção obrigatória: {term}", errors)

    security = ROOT / "docs" / "SECURITY.md"
    if security.is_file():
        text = security.read_text(encoding="utf-8")
        for skill in ("entregar-issue", "corrigir-ci", "auditar-issue"):
            if skill not in text:
                fail(f"SECURITY.md não declara autoridade de {skill}", errors)
        if "UNKNOWN" not in text:
            fail("SECURITY.md não preserva semântica UNKNOWN", errors)

    capabilities = load_json(
        ROOT / ".github" / "skill-system-capabilities.json",
        ".github/skill-system-capabilities.json",
        errors,
    )
    requirements = load_json(
        ROOT / "config" / "skill-system-requirements.json",
        "config/skill-system-requirements.json",
        errors,
    )

    if capabilities is not None:
        if capabilities.get("schema_version") != 1:
            fail("capabilities: schema_version inesperada", errors)
        if capabilities.get("system_version") != SYSTEM_VERSION:
            fail("capabilities: system_version inesperada", errors)
        for key, expected in REQUIRED_CAPABILITIES.items():
            if capabilities.get(key) != expected:
                fail(f"capabilities: {key} deve ser {expected!r}", errors)
        transports = capabilities.get("audit_transports")
        if not isinstance(transports, list) or set(transports) != {
            "native-github-audit",
            "certified-handoff",
        }:
            fail("capabilities: audit_transports inválido", errors)

    if requirements is not None:
        if requirements.get("schema_version") != 1:
            fail("requirements: schema_version inesperada", errors)
        if requirements.get("system_version") != SYSTEM_VERSION:
            fail("requirements: system_version diverge do catálogo", errors)
        expected_paths = {
            "canonical_spec": "docs/SKILL_SYSTEM_SPEC.md",
            "security_model": "docs/SECURITY.md",
            "capabilities_manifest": ".github/skill-system-capabilities.json",
        }
        for key, expected in expected_paths.items():
            if requirements.get(key) != expected:
                fail(f"requirements: {key} deve apontar para {expected}", errors)

        status_model = requirements.get("status_model")
        allowed_statuses = {"planned", "implemented", "validated"}
        if status_model != ["planned", "implemented", "validated"]:
            fail("requirements: status_model inesperado", errors)

        items = requirements.get("requirements")
        if not isinstance(items, list) or not items:
            fail("requirements: lista de requisitos ausente", errors)
        else:
            ids: set[str] = set()
            for item in items:
                if not isinstance(item, dict):
                    fail("requirements: requisito não é objeto", errors)
                    continue
                requirement_id = item.get("id")
                if not isinstance(requirement_id, str) or not re.fullmatch(r"SKSYS-\d{3}", requirement_id):
                    fail(f"requirements: id inválido: {requirement_id!r}", errors)
                    continue
                if requirement_id in ids:
                    fail(f"requirements: id duplicado: {requirement_id}", errors)
                ids.add(requirement_id)
                if item.get("status") not in allowed_statuses:
                    fail(f"{requirement_id}: status inválido", errors)
                if not str(item.get("title", "")).strip():
                    fail(f"{requirement_id}: title ausente", errors)
                if not str(item.get("summary", "")).strip():
                    fail(f"{requirement_id}: summary ausente", errors)
                for field in ("implementationRefs", "validationRefs"):
                    refs = item.get(field)
                    if not isinstance(refs, list) or not refs:
                        fail(f"{requirement_id}: {field} ausente", errors)
                        continue
                    for ref in refs:
                        if not isinstance(ref, str) or not ref:
                            fail(f"{requirement_id}: {field} contém referência inválida", errors)
                            continue
                        validate_file_ref(ref, requirement_id, errors)


def validate_skill(skill_dir: Path, errors: list[str]) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        fail(f"{skill_dir.name}: SKILL.md ausente", errors)
        return

    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        fail(f"{skill_dir.name}: frontmatter YAML ausente", errors)
    if not re.search(r"^---\n.*?\n---\n", content, flags=re.DOTALL):
        fail(f"{skill_dir.name}: frontmatter YAML inválido", errors)

    name_match = re.search(r"^name:\s*([^\n]+)$", content, flags=re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)$", content, flags=re.MULTILINE)
    if not name_match:
        fail(f"{skill_dir.name}: campo name ausente", errors)
    elif name_match.group(1).strip().strip('"') != skill_dir.name:
        fail(f"{skill_dir.name}: name não corresponde ao diretório", errors)
    if not description_match or not description_match.group(1).strip():
        fail(f"{skill_dir.name}: description ausente", errors)
    if len(content.splitlines()) > 500:
        fail(f"{skill_dir.name}: SKILL.md excede 500 linhas", errors)

    version_file = skill_dir / "contracts" / "version.json"
    if not version_file.is_file():
        fail(f"{skill_dir.name}: contracts/version.json ausente", errors)
    else:
        try:
            version = json.loads(version_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"{skill_dir.name}: version.json inválido: {exc}", errors)
        else:
            if version.get("canonical_owner") != "entregar-issue":
                fail(f"{skill_dir.name}: canonical_owner inesperado", errors)
            if version.get("contract_version") != "2026-08-20.3":
                fail(f"{skill_dir.name}: contract_version inesperada", errors)

    for required_dir in ("references", "schemas", "tests"):
        if not (skill_dir / required_dir).is_dir():
            fail(f"{skill_dir.name}: diretório {required_dir}/ ausente", errors)

    manifest = skill_dir / "contracts" / "manifest.json"
    if manifest.is_file():
        try:
            json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"{skill_dir.name}: contracts/manifest.json inválido: {exc}", errors)


def main() -> int:
    errors: list[str] = []
    actual = {
        path.name
        for path in ROOT.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and path.name not in {"config", "docs", "scripts"}
    }
    missing = EXPECTED_SKILLS - actual
    unexpected = actual - EXPECTED_SKILLS
    for name in sorted(missing):
        fail(f"skill esperada ausente: {name}", errors)
    for name in sorted(unexpected):
        fail(f"diretório de skill inesperado: {name}", errors)
    for name in sorted(EXPECTED_SKILLS & actual):
        validate_skill(ROOT / name, errors)

    canonical = ROOT / "entregar-issue" / "contracts" / "manifest.json"
    if not canonical.is_file():
        fail("manifesto canônico de entregar-issue ausente", errors)

    validate_global_governance(errors)

    if errors:
        print("Validação falhou:")
        print("\n".join(f"- {error}" for error in errors))
        return 1

    print(
        f"Validação OK: {len(EXPECTED_SKILLS)} skills e governança global "
        f"{SYSTEM_VERSION} consistentes."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
