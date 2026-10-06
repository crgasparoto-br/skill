"""Regressions for the genericity rules over permanent skill assets.

The examples of forbidden content are assembled from parts on purpose: this file is
itself a permanent asset inspected by the validator it exercises, so a literal
example would make the catalog fail its own rule. That constraint is the rule
working, not an accident of the test.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = SKILL_ROOT.parent
VALIDATOR = SKILL_ROOT / "scripts" / "validate_skill_genericity.py"

HOME_PATH_EXAMPLE = "/" + "home" + "/" + "algum-usuario" + "/projeto"
IDENTIFIER_EXAMPLE = "contract" + "Id"
INTERNAL_HOST_EXAMPLE = "https://" + "acme-interno.corp" + "/spec"
RESERVED_HOST_EXAMPLE = "https://" + "exemplo.invalid" + "/x"
GENERIC_HOST_EXAMPLE = "https://" + "json-schema.org" + "/draft/2020-12/schema"
ISSUE_HEADING_EXAMPLE = "## Regra derivada " + "da issue " + "123"
NUMBERED_TEST_FILENAME = "test_issue_123_escape.py"


def run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--skill-root", str(root)],
        text=True,
        stdout=subprocess.PIPE,
    )


def write_reference(root: Path, content: str) -> Path:
    (root / "alpha").mkdir(parents=True, exist_ok=True)
    (root / "alpha" / "SKILL.md").write_text("control plane\n", encoding="utf-8")
    target = root / "alpha" / "references" / "guia.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def test_examples_actually_carry_the_forbidden_shape() -> None:
    assert HOME_PATH_EXAMPLE.startswith("/" + "home" + "/")
    assert IDENTIFIER_EXAMPLE[0].islower() and any(char.isupper() for char in IDENTIFIER_EXAMPLE)
    assert INTERNAL_HOST_EXAMPLE.startswith("https://")
    assert ISSUE_HEADING_EXAMPLE.startswith("## Regra derivada")


def test_catalog_is_free_of_concrete_coupling() -> None:
    result = run(CATALOG_ROOT)
    assert result.returncode == 0, result.stdout
    assert "READY" in result.stdout


def test_absolute_host_path_blocks(tmp_path: Path) -> None:
    write_reference(tmp_path, f"ver {HOME_PATH_EXAMPLE}\n")
    result = run(tmp_path)
    assert result.returncode == 2
    assert "absolute host path" in result.stdout


def test_concrete_identifier_in_prose_blocks(tmp_path: Path) -> None:
    write_reference(tmp_path, f"usar {IDENTIFIER_EXAMPLE} no payload\n")
    result = run(tmp_path)
    assert result.returncode == 2
    assert f"concrete identifier '{IDENTIFIER_EXAMPLE}' in prose" in result.stdout


def test_identifier_inside_code_span_does_not_block(tmp_path: Path) -> None:
    write_reference(tmp_path, f"usar `{IDENTIFIER_EXAMPLE}` no payload\n")
    result = run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_identifier_inside_fenced_block_does_not_block(tmp_path: Path) -> None:
    write_reference(tmp_path, f"exemplo:\n\n```json\n{{\"chave\": \"{IDENTIFIER_EXAMPLE}\"}}\n```\n")
    result = run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_unclosed_fence_does_not_cascade(tmp_path: Path) -> None:
    write_reference(tmp_path, f"```json\n{{\"chave\": \"{IDENTIFIER_EXAMPLE}\"}}\n")
    result = run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_internal_host_blocks(tmp_path: Path) -> None:
    write_reference(tmp_path, f"ver {INTERNAL_HOST_EXAMPLE}\n")
    result = run(tmp_path)
    assert result.returncode == 2
    assert "concrete external host" in result.stdout


def test_reserved_and_generic_hosts_do_not_block(tmp_path: Path) -> None:
    write_reference(tmp_path, f"ver {RESERVED_HOST_EXAMPLE} e {GENERIC_HOST_EXAMPLE}\n")
    result = run(tmp_path)
    assert result.returncode == 0, result.stdout


def test_numbered_issue_test_filename_blocks(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / NUMBERED_TEST_FILENAME).write_text("def test_x(): pass\n", encoding="utf-8")
    result = run(tmp_path)
    assert result.returncode == 2
    assert "numbered issue-specific test filename" in result.stdout


def test_issue_derived_heading_blocks(tmp_path: Path) -> None:
    write_reference(tmp_path, f"{ISSUE_HEADING_EXAMPLE}\n")
    result = run(tmp_path)
    assert result.returncode == 2
    assert "historical issue-derived permanent rule" in result.stdout


def test_validator_ignores_its_own_source(tmp_path: Path) -> None:
    """The validator declares the patterns it blocks, so it must exclude itself."""
    result = run(SKILL_ROOT / "scripts")
    assert result.returncode == 0, result.stdout