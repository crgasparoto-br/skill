#!/usr/bin/env python3
"""Validate the canonical issue templates consumed by the delivery skills.

The delivery controller derives requirement candidates from the issue body:
`entregar-issue/scripts/specification.py` treats list items under normative
sections, checkbox items and obligation phrasing as mandatory candidates, and the
independent control in `auditar-issue` re-derives the same items with its own
parser. A template that omits a normative section silently shrinks what the
closure must cover, and a template that ships placeholder list items silently
inflates it. Both are contract drift, so this validator fails closed on them.

Invariants enforced here:

1. `config/issue-templates.json` exists and is well formed;
2. the required templates exist in the configured templates directory;
3. every template declares `name` and `about` in its frontmatter;
4. every template body line is a heading or part of an HTML comment, so no
   placeholder item can ever be extracted as a requirement;
5. every configured normative section is declared by a heading that carries no
   non-normative marker;
6. the template chooser configuration is valid YAML and does not silently
   re-enable blank issues.

The inertia of the guidance text itself is proven separately, against the real
producer regexes, by `tests/test_issue_templates.py`.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

try:
    from .catalog import ROOT
except ImportError:  # pragma: no cover - direct script execution
    from catalog import ROOT

CONFIG_RELATIVE = "config/issue-templates.json"
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
FRONTMATTER_FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$")
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"
CHOOSER_FILE = "config.yml"


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def load_config(root: Path, errors: list[str]) -> dict[str, Any] | None:
    path = root / CONFIG_RELATIVE
    if not path.is_file():
        errors.append(f"{CONFIG_RELATIVE} ausente")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{CONFIG_RELATIVE} inválido: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{CONFIG_RELATIVE} deve conter objeto JSON")
        return None
    if value.get("schema_version") != 1:
        errors.append(f"{CONFIG_RELATIVE}: schema_version inesperada")
    if value.get("system") != "issue-templates":
        errors.append(f"{CONFIG_RELATIVE}: system inesperado")
    return value


def string_list(config: dict[str, Any], key: str, errors: list[str], *, allow_empty: bool = False) -> list[str]:
    value = config.get(key)
    if not isinstance(value, list) or (not value and not allow_empty):
        errors.append(f"{CONFIG_RELATIVE}: {key} deve ser lista não vazia")
        return []
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{CONFIG_RELATIVE}: {key} contém item inválido")
            continue
        result.append(item.strip())
    return result


def split_template(path: Path) -> tuple[dict[str, str] | None, list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return None, lines
    end = next((index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        return None, lines
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        match = FRONTMATTER_FIELD_RE.match(line)
        if match:
            fields[match.group(1)] = match.group(2).strip().strip("'\"")
    return fields, lines[end + 1 :]


def template_headings(body: list[str]) -> list[str]:
    headings: list[str] = []
    in_comment = False
    for raw in body:
        stripped = raw.strip()
        if in_comment:
            in_comment = COMMENT_CLOSE not in stripped
            continue
        if stripped.startswith(COMMENT_OPEN):
            in_comment = COMMENT_CLOSE not in stripped
            continue
        match = HEADING_RE.match(stripped)
        if match:
            headings.append(normalize(match.group(1)))
    return headings


def validate_template(
    path: Path,
    relative: str,
    normative: list[str],
    markers: list[str],
    errors: list[str],
) -> None:
    fields, body = split_template(path)
    if fields is None:
        errors.append(f"{relative}: frontmatter YAML ausente ou não fechado")
        return
    for field in ("name", "about"):
        if not fields.get(field, "").strip():
            errors.append(f"{relative}: frontmatter sem {field} não vazio")

    in_comment = False
    for line_no, raw in enumerate(body, start=1):
        stripped = raw.strip()
        if in_comment:
            in_comment = COMMENT_CLOSE not in stripped
            continue
        if not stripped:
            continue
        if stripped.startswith(COMMENT_OPEN):
            in_comment = COMMENT_CLOSE not in stripped
            continue
        if HEADING_RE.match(stripped):
            continue
        errors.append(
            f"{relative}:{line_no}: linha de template deve ser heading ou comentário HTML; "
            "item ou prosa pré-preenchida entra no fechamento de requisitos"
        )

    headings = template_headings(body)
    if not headings:
        errors.append(f"{relative}: nenhum heading declarado")
    for section in normative:
        token = normalize(section)
        matched = any(
            token in heading and not any(normalize(marker) in heading for marker in markers)
            for heading in headings
        )
        if not matched:
            errors.append(f"{relative}: seção normativa ausente: {section}")


def validate_chooser(templates_dir: Path, relative_dir: str, errors: list[str]) -> None:
    path = templates_dir / CHOOSER_FILE
    if not path.is_file():
        return
    try:
        import yaml
    except ImportError:  # pragma: no cover - dependency declared in requirements
        errors.append(f"{relative_dir}/{CHOOSER_FILE}: PyYAML indisponível para validar o YAML")
        return
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        errors.append(f"{relative_dir}/{CHOOSER_FILE}: YAML inválido: {exc}")
        return
    if not isinstance(value, dict):
        errors.append(f"{relative_dir}/{CHOOSER_FILE}: deve conter mapeamento YAML")
        return
    if "blank_issues_enabled" in value and not isinstance(value["blank_issues_enabled"], bool):
        errors.append(f"{relative_dir}/{CHOOSER_FILE}: blank_issues_enabled deve ser booleano")
    links = value.get("contact_links")
    if links is not None:
        if not isinstance(links, list):
            errors.append(f"{relative_dir}/{CHOOSER_FILE}: contact_links deve ser lista")
            return
        for index, link in enumerate(links):
            if not isinstance(link, dict):
                errors.append(f"{relative_dir}/{CHOOSER_FILE}: contact_links[{index}] não é mapeamento")
                continue
            for field in ("name", "url"):
                if not str(link.get(field, "")).strip():
                    errors.append(f"{relative_dir}/{CHOOSER_FILE}: contact_links[{index}] sem {field}")


def validate_issue_templates(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    config = load_config(root, errors)
    if config is None:
        return errors

    templates_dir_value = config.get("templates_dir")
    if not isinstance(templates_dir_value, str) or not templates_dir_value.strip():
        errors.append(f"{CONFIG_RELATIVE}: templates_dir ausente")
        return errors
    relative_dir = templates_dir_value.strip()
    templates_dir = root / relative_dir
    if not templates_dir.is_dir():
        errors.append(f"{relative_dir} ausente")
        return errors

    normative = string_list(config, "normative_sections", errors)
    markers = string_list(config, "non_normative_markers", errors)
    required = string_list(config, "required_templates", errors)
    string_list(config, "guidance_sources", errors, allow_empty=True)

    for name in required:
        candidate = templates_dir / f"{name}.md"
        if not candidate.is_file():
            errors.append(f"{relative_dir}/{name}.md ausente")

    for path in sorted(templates_dir.glob("*.md")):
        relative = f"{relative_dir}/{path.name}"
        if normative and markers:
            validate_template(path, relative, normative, markers, errors)

    validate_chooser(templates_dir, relative_dir, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = validate_issue_templates(args.root.resolve())
    if errors:
        print("Issue template validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Issue template validation OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())