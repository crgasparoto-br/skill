from __future__ import annotations

import ast
import json
from pathlib import Path

from scripts.build_catalog_docs import render_catalog, validate_readme_catalog
from scripts.catalog import load_catalog, validate_catalog
from scripts.select_skill import rank_skills
from scripts.validate_contract_sync import validate_contract_sync, validate_shared_files
from scripts.validate_docs import local_link_errors, skill_reference_errors

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_is_valid_and_matches_skill_metadata() -> None:
    assert validate_catalog(ROOT) == []
    catalog = load_catalog(ROOT)
    assert {item["id"] for item in catalog["skills"]} == {
        "auditar-issue",
        "corrigir-ci",
        "design-interface",
        "documentacao-repositorio",
        "entregar-issue",
        "fluxos-conversacionais",
        "revisar-issue",
    }


def test_contract_sync_covers_all_declared_generated_copies() -> None:
    assert validate_contract_sync(ROOT) == []


def test_catalog_documentation_is_generated_and_current() -> None:
    assert validate_readme_catalog(ROOT) == []
    assert render_catalog(load_catalog(ROOT)) in (ROOT / "README.md").read_text(encoding="utf-8")


def test_documentation_references_are_current() -> None:
    assert local_link_errors(ROOT) == []
    assert skill_reference_errors(ROOT) == []


def test_router_explains_delivery_selection() -> None:
    result = rank_skills("implementar uma issue e entregar a PR", load_catalog(ROOT))
    assert result["decision"] == "entregar-issue"
    assert result["candidates"][0]["matched_positive"]


def test_router_blocks_delivery_without_write_capability() -> None:
    result = rank_skills(
        "implementar uma issue e entregar a PR",
        load_catalog(ROOT),
        {"repository-read", "test-execution"},
    )
    assert result["decision"] == "BLOCKED"
    assert "repository-write" in result["candidates"][0]["missing_capabilities"]


def test_router_fails_closed_on_ambiguous_or_unknown_request() -> None:
    unknown = rank_skills("fazer algo no repositório", load_catalog(ROOT))
    assert unknown["decision"] == "UNKNOWN"
    ambiguous = rank_skills("revisar uma issue e auditar uma PR", load_catalog(ROOT))
    assert ambiguous["decision"] == "UNKNOWN"


def test_contract_validator_detects_generated_copy_drift(tmp_path: Path) -> None:
    source = ROOT / "entregar-issue" / "contracts" / "gate-registry.json"
    target = tmp_path / "auditar-issue" / "contracts"
    target.mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "auditar-issue" / "SKILL.md").parent.mkdir(exist_ok=True)
    (tmp_path / "auditar-issue" / "SKILL.md").write_text("---\nname: auditar-issue\ndescription: audit\n---\n", encoding="utf-8")
    (tmp_path / "auditar-issue" / "contracts" / "version.json").write_text(json.dumps({
        "schema_version": 1,
        "contract_version": "2026-08-20.3",
        "canonical_owner": "entregar-issue",
        "generated_copy": True,
    }), encoding="utf-8")
    (tmp_path / "entregar-issue" / "contracts").mkdir(parents=True)
    (tmp_path / "entregar-issue" / "SKILL.md").write_text("---\nname: entregar-issue\ndescription: delivery\n---\n", encoding="utf-8")
    (tmp_path / "entregar-issue" / "contracts" / "version.json").write_text(json.dumps({
        "schema_version": 1,
        "contract_version": "2026-08-20.3",
        "canonical_owner": "entregar-issue",
        "generated_copy": False,
    }), encoding="utf-8")
    source_bytes = source.read_bytes()
    canonical_dir = tmp_path / "entregar-issue" / "contracts"
    canonical_dir.joinpath("gate-registry.json").write_bytes(source_bytes)
    manifest = {
        "schema_version": 1,
        "contract_version": "2026-08-20.3",
        "files": {"gate-registry.json": "0" * 64},
    }
    (canonical_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (target / "gate-registry.json").write_bytes(source_bytes + b"\ndrift\n")
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "config" / "skills-catalog.json").write_text(json.dumps({
        "schema_version": 1,
        "system": "skill-catalog",
        "catalog_version": "2026-09-29.1",
        "skills": [
            {"id": "auditar-issue", "path": "auditar-issue", "status": "validated", "purpose": "audit", "summary": "audit summary", "input": "audit input", "modes": ["independent"], "read_only": True, "write_owner": "auditar-issue", "contract_version": "2026-08-20.3", "positive_triggers": ["auditar issue"], "negative_triggers": ["implementar issue"], "required_capabilities": ["repository-read"]},
            {"id": "entregar-issue", "path": "entregar-issue", "status": "validated", "purpose": "delivery", "summary": "delivery summary", "input": "delivery input", "modes": ["direct"], "read_only": False, "write_owner": "controller", "contract_version": "2026-08-20.3", "positive_triggers": ["entregar issue"], "negative_triggers": ["somente auditar"], "required_capabilities": ["repository-read"]},
        ],
    }), encoding="utf-8")
    (tmp_path / "config" / "capabilities.json").write_text(json.dumps({
        "schema_version": 1,
        "system": "skill-capabilities",
        "capabilities": {"repository-read": {
            "description": "Read the repository.",
            "missing_state": "BLOCK",
            "fallback": "return-unknown",
        }},
    }), encoding="utf-8")
    errors = validate_contract_sync(tmp_path)
    assert any("hash mismatch" in error for error in errors)


def test_runtime_skill_allowlist_matches_catalog() -> None:
    source = (ROOT / "entregar-issue" / "scripts" / "planning_contract_runtime.py").read_text(encoding="utf-8")
    assignment = next(
        node for node in ast.parse(source).body
        if isinstance(node, ast.Assign) and any(getattr(target, "id", "") == "CATALOG_SKILLS" for target in node.targets)
    )
    runtime = set(ast.literal_eval(assignment.value.args[0]))
    catalog = {item["id"] for item in load_catalog(ROOT)["skills"]}
    schema = json.loads((ROOT / "entregar-issue" / "contracts" / "subskill-result.schema.json").read_text(encoding="utf-8"))
    assert runtime == catalog
    assert set(schema["properties"]["skill"]["enum"]) == catalog


def test_shared_files_are_byte_identical_to_canonical() -> None:
    assert validate_shared_files(ROOT) == []


def test_shared_file_drift_is_detected(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "tool.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b" / "tool.py").write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "config" / "shared-files.json").write_text(json.dumps({
        "schema_version": 1,
        "groups": [{"canonical": "a/tool.py", "copies": ["b/tool.py"]}],
    }), encoding="utf-8")
    errors = validate_shared_files(tmp_path)
    assert any("differs from canonical" in error for error in errors)
