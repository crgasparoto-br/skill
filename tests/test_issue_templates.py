"""Regressions for the canonical issue template contract.

Two independent controls are exercised here:

- the structural validator (`scripts/validate_issue_templates.py`) keeps templates
  well formed and keeps every normative section declared;
- the shipped guidance text is proven inert against the *real* producer regexes
  from `entregar-issue/scripts/specification.py`, so a template can never inject a
  requirement candidate into the closure by accident.

The configured normative sections are also cross-checked against the independent
parser of `auditar-issue`, so `config/issue-templates.json` cannot become a second
source of truth that silently disagrees with the auditor.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

from scripts.validate_issue_templates import validate_issue_templates

ROOT = Path(__file__).resolve().parents[1]
CONFIG_RELATIVE = "config/issue-templates.json"
TEMPLATES_DIR = ".github/ISSUE_TEMPLATE"


def load_skill_module(path: Path, name: str, extra_dir: Path | None = None):
    inserted = False
    if extra_dir is not None:
        sys.path.insert(0, str(extra_dir))
        inserted = True
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted:
            sys.path.remove(str(extra_dir))


def producer():
    return load_skill_module(
        ROOT / "entregar-issue" / "scripts" / "specification.py",
        "skill_specification_producer",
    )


def auditor():
    return load_skill_module(
        ROOT / "auditar-issue" / "scripts" / "check_normative_section_coverage.py",
        "skill_normative_section_coverage",
        extra_dir=ROOT / "auditar-issue" / "scripts",
    )


def load_config() -> dict:
    return json.loads((ROOT / CONFIG_RELATIVE).read_text(encoding="utf-8"))


def template_paths():
    return sorted((ROOT / TEMPLATES_DIR).glob("*.md"))


def extracted_candidates(module, path: Path) -> list[tuple[int, str]]:
    """Mirror the producer decision using only the producer's own primitives."""
    heading = ""
    found: list[tuple[int, str]] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        match = module.HEADING_RE.match(stripped)
        if match:
            heading = module.normalize(match.group(1))
            continue
        text = module.normalize(raw)
        if not text or text.startswith("#") or set(text) <= {"-", ":", " "}:
            continue
        left = raw.lstrip()
        if module.NON_NORMATIVE_SECTION_RE.search(heading or ""):
            continue
        is_list_item = bool(module.LIST_ITEM_RE.match(left))
        section_is_normative = bool(heading and module.NORMATIVE_SECTION_RE.search(heading))
        if (
            module.OBLIGATION_RE.search(text)
            or left.startswith("- [")
            or (is_list_item and section_is_normative)
        ):
            found.append((line_no, text))
    return found


def build_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy2(ROOT / CONFIG_RELATIVE, root / CONFIG_RELATIVE)
    shutil.copytree(ROOT / TEMPLATES_DIR, root / TEMPLATES_DIR)
    return root


def test_shipped_issue_templates_are_valid() -> None:
    assert validate_issue_templates(ROOT) == []


def test_configured_normative_sections_match_independent_audit_parser() -> None:
    config = load_config()
    audit = auditor()
    for section in config["normative_sections"]:
        assert audit.NORMATIVE_HEADING_RE.search(section), section
        assert not audit.NON_NORMATIVE_HEADING_RE.search(section), section
    for marker in config["non_normative_markers"]:
        assert audit.NON_NORMATIVE_HEADING_RE.search(marker), marker


def test_configured_normative_sections_match_producer_parser() -> None:
    config = load_config()
    spec = producer()
    for section in config["normative_sections"]:
        assert spec.NORMATIVE_SECTION_RE.search(section), section
    for marker in config["non_normative_markers"]:
        assert spec.NON_NORMATIVE_SECTION_RE.search(marker), marker


def test_templates_are_inert_for_the_requirement_extractor() -> None:
    spec = producer()
    for path in template_paths():
        assert extracted_candidates(spec, path) == [], path.name


def test_removing_a_normative_section_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    template = root / TEMPLATES_DIR / "feature.md"
    template.write_text(
        "\n".join(line for line in template.read_text(encoding="utf-8").splitlines() if line.strip() != "## Invariantes"),
        encoding="utf-8",
    )
    errors = validate_issue_templates(root)
    assert any("seção normativa ausente: Invariantes" in error for error in errors), errors


def test_non_normative_heading_does_not_satisfy_a_normative_section(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    template = root / TEMPLATES_DIR / "feature.md"
    template.write_text(
        template.read_text(encoding="utf-8").replace("## Escopo", "## Out of scope"),
        encoding="utf-8",
    )
    errors = validate_issue_templates(root)
    assert any("seção normativa ausente: Escopo" in error for error in errors), errors


def test_placeholder_list_item_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    template = root / TEMPLATES_DIR / "bug.md"
    template.write_text(template.read_text(encoding="utf-8") + "\n- [ ] Preencher\n", encoding="utf-8")
    errors = validate_issue_templates(root)
    assert any("linha de template deve ser heading ou comentário HTML" in error for error in errors), errors


def test_empty_checkbox_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    template = root / TEMPLATES_DIR / "epic.md"
    template.write_text(template.read_text(encoding="utf-8") + "\n- [ ]\n", encoding="utf-8")
    assert validate_issue_templates(root) != []


def test_missing_required_template_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    (root / TEMPLATES_DIR / "bug.md").unlink()
    errors = validate_issue_templates(root)
    assert any("bug.md ausente" in error for error in errors), errors


def test_frontmatter_without_about_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    template = root / TEMPLATES_DIR / "feature.md"
    lines = template.read_text(encoding="utf-8").splitlines()
    template.write_text(
        "\n".join("about:" if line.startswith("about:") else line for line in lines),
        encoding="utf-8",
    )
    errors = validate_issue_templates(root)
    assert any("frontmatter sem about" in error for error in errors), errors


def test_missing_config_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    (root / CONFIG_RELATIVE).unlink()
    errors = validate_issue_templates(root)
    assert any(CONFIG_RELATIVE in error for error in errors), errors


def test_blank_issues_are_disabled_so_the_canonical_form_is_used() -> None:
    import yaml

    chooser = ROOT / TEMPLATES_DIR / "config.yml"
    value = yaml.safe_load(chooser.read_text(encoding="utf-8"))
    assert value["blank_issues_enabled"] is False
    for link in value["contact_links"]:
        assert link["name"] and link["url"].startswith("https://")
