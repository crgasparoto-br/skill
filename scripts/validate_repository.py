#!/usr/bin/env python3
"""Validate repository-wide invariants of the skills catalog."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    from catalog import catalog_skill_ids, load_catalog, validate_catalog
    from validate_contract_sync import validate_contract_sync
    from validate_docs import validate_docs
    from validate_versioning import validate_versioning
    from validate_adapters import validate_adapters
    from validate_evals import validate_evals
    from validate_reachability import validate_reachability
    from validate_issue_templates import validate_issue_templates
    from validate_context_budget import validate_context_budget
    from validate_reference_indexes import validate_reference_indexes
    from validate_dependency_locks import validate_dependency_locks
except ImportError:  # pragma: no cover - package import fallback
    from .catalog import catalog_skill_ids, load_catalog, validate_catalog
    from .validate_contract_sync import validate_contract_sync
    from .validate_docs import validate_docs
    from .validate_versioning import validate_versioning
    from .validate_adapters import validate_adapters
    from .validate_evals import validate_evals
    from .validate_reachability import validate_reachability
    from .validate_issue_templates import validate_issue_templates
    from .validate_context_budget import validate_context_budget
    from .validate_reference_indexes import validate_reference_indexes
    from .validate_dependency_locks import validate_dependency_locks

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_VERSION = "2026-09-29.5"
GLOBAL_FILES = {
    "docs/SKILL_SYSTEM_SPEC.md",
    "docs/SECURITY.md",
    "config/skill-system-requirements.json",
    "config/skills-catalog.json",
    "config/capabilities.json",
    "schemas/skill-catalog.schema.json",
    "schemas/capabilities.schema.json",
    "config/compatibility.json",
    "schemas/compatibility.schema.json",
    "VERSION",
    "CHANGELOG.md",
    "docs/RELEASE.md",
    "docs/ROADMAP.md",
    "config/platform-adapters.json",
    "config/shared-files.json",
    "schemas/platform-adapters.schema.json",
    "docs/PLATFORM_ADAPTERS.md",
    "evals/README.md",
    "evals/manifest.json",
    "evals/run_evals.py",
    "evals/schemas/eval-manifest.schema.json",
    "evals/schemas/eval-case.schema.json",
    "evals/schemas/eval-result.schema.json",
    "evals/schemas/eval-report.schema.json",
    "evals/schemas/eval-fixture-manifest.schema.json",
    "evals/fixtures/manifest.json",
    "scripts/validate_evals.py",
    ".github/skill-system-capabilities.json",
    "AGENTS.md",
    "config/issue-templates.json",
    "scripts/validate_issue_templates.py",
    "config/dependency-policy.json",
    "scripts/validate_dependency_locks.py",
    "scripts/lock_dependencies.py",
    "scripts/audit_dependencies.py",
    "requirements.txt",
    "requirements.lock.txt",
    ".github/ISSUE_TEMPLATE/feature.md",
    ".github/ISSUE_TEMPLATE/bug.md",
    ".github/ISSUE_TEMPLATE/epic.md",
    ".github/ISSUE_TEMPLATE/config.yml",
    "config/context-budget.json",
    "config/reference-index.json",
    "scripts/validate_context_budget.py",
    "scripts/validate_reference_indexes.py",
    "config/dependency-policy.json",
    "scripts/validate_dependency_locks.py",
    "scripts/lock_dependencies.py",
    "scripts/audit_dependencies.py",
    ".github/workflows/dependency-audit.yml",
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
    "catalog_manifest": "enabled",
    "capability_contract": "enabled",
    "versioned_releases": "enabled",
    "platform_adapters": "enabled",
    "contract_sync_validation": "enabled",
    "documentation_link_validation": "enabled",
    "behavioral_evaluation_harness": "enabled",
}


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def load_json(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    if not path.is_file():
        fail(f"{label} ausente", errors)
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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

    catalog_errors = validate_catalog(ROOT)
    errors.extend(f"catálogo: {error}" for error in catalog_errors)

    spec = ROOT / "docs" / "SKILL_SYSTEM_SPEC.md"
    if spec.is_file():
        text = spec.read_text(encoding="utf-8")
        required_terms = (
            "Hierarquia de fontes",
            "Fail closed",
            "Sem autoridade implícita de merge",
            "Contexto suficiente",
            "Observabilidade sem fabricação",
            "Catálogo machine-readable",
            "capacidades exigidas",
            "SemVer",
            "compatibilidade",
            "Adaptadores de plataforma",
            "Avaliações comportamentais",
            "cópias geradas",
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
            "skills_catalog": "config/skills-catalog.json",
            "skills_catalog_schema": "schemas/skill-catalog.schema.json",
            "capability_registry": "config/capabilities.json",
            "capability_registry_schema": "schemas/capabilities.schema.json",
            "compatibility_manifest": "config/compatibility.json",
            "compatibility_manifest_schema": "schemas/compatibility.schema.json",
            "platform_adapters_manifest": "config/platform-adapters.json",
            "platform_adapters_schema": "schemas/platform-adapters.schema.json",
            "evaluation_harness": "evals/run_evals.py",
            "evaluation_manifest": "evals/manifest.json",
            "evaluation_manifest_schema": "evals/schemas/eval-manifest.schema.json",
            "evaluation_case_schema": "evals/schemas/eval-case.schema.json",
            "evaluation_result_schema": "evals/schemas/eval-result.schema.json",
            "evaluation_report_schema": "evals/schemas/eval-report.schema.json",
            "evaluation_validator": "scripts/validate_evals.py",
            "evaluation_fixture_manifest": "evals/fixtures/manifest.json",
            "evaluation_fixture_manifest_schema": "evals/schemas/eval-fixture-manifest.schema.json",
        }
        for key, expected in expected_paths.items():
            if requirements.get(key) != expected:
                fail(f"requirements: {key} deve apontar para {expected}", errors)

        status_model = requirements.get("status_model")
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
                if item.get("status") not in {"planned", "implemented", "validated"}:
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
    elif name_match.group(1).strip().strip('"\'') != skill_dir.name:
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
        except (OSError, json.JSONDecodeError) as exc:
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
    if not manifest.is_file():
        fail(f"{skill_dir.name}: contracts/manifest.json ausente", errors)
    else:
        try:
            json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"{skill_dir.name}: contracts/manifest.json inválido: {exc}", errors)


def main() -> int:
    errors: list[str] = []
    validate_global_governance(errors)
    try:
        catalog = load_catalog(ROOT)
        expected_skills = catalog_skill_ids(catalog)
    except (OSError, json.JSONDecodeError, ValueError):
        expected_skills = set()

    actual = {
        path.name
        for path in ROOT.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and path.name not in {"adapters", "config", "docs", "evals", "scripts", "schemas", "tests"}
    }
    missing = expected_skills - actual
    unexpected = actual - expected_skills
    for name in sorted(missing):
        fail(f"skill declarada ausente: {name}", errors)
    for name in sorted(unexpected):
        fail(f"diretório de skill fora do catálogo: {name}", errors)
    for name in sorted(expected_skills & actual):
        validate_skill(ROOT / name, errors)

    canonical = ROOT / "entregar-issue" / "contracts" / "manifest.json"
    if not canonical.is_file():
        fail("manifesto canônico de entregar-issue ausente", errors)

    errors.extend(f"contratos: {error}" for error in validate_contract_sync(ROOT))
    errors.extend(f"documentação: {error}" for error in validate_docs(ROOT))
    errors.extend(f"versionamento: {error}" for error in validate_versioning(ROOT))
    errors.extend(f"adapters: {error}" for error in validate_adapters(ROOT))
    errors.extend(f"avaliações: {error}" for error in validate_evals(ROOT))
    errors.extend(f"alcançabilidade: {error}" for error in validate_reachability(ROOT))
    errors.extend(f"formato de issue: {error}" for error in validate_issue_templates(ROOT))
    errors.extend(f"orçamento de contexto: {error}" for error in validate_context_budget(ROOT))
    errors.extend(f"índice de referência: {error}" for error in validate_reference_indexes(ROOT))
    errors.extend(f"dependências: {error}" for error in validate_dependency_locks(ROOT))

    if errors:
        print("Validação falhou:")
        print("\n".join(f"- {error}" for error in sorted(set(errors))))
        return 1

    print(
        f"Validação OK: {len(expected_skills)} skills, catálogo, contratos e documentação "
        f"consistentes em {SYSTEM_VERSION}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
