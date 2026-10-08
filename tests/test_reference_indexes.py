"""Regressions for the navigability of long references.

A reference that cannot be entered without being read whole defeats progressive
loading. These tests cover both sides: a long reference must be navigable, and an
index must not be decorative, so every entry has to resolve and every section has to
appear.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_reference_indexes import validate_reference_indexes

ROOT = Path(__file__).resolve().parents[1]
CONFIG_RELATIVE = "config/reference-index.json"
THRESHOLD = 200

NAVIGABLE = (
    "# Guia\n"
    "\n"
    "## Quando ler este arquivo\n"
    "\n"
    "Sempre que houver duvida material.\n"
    "\n"
    "## Índice\n"
    "\n"
    "- [Secao um](#secao-um)\n"
    "\n"
    "## Secao um\n"
    "\n"
    "conteudo\n"
)


def pad(content: str, total_bytes: int) -> str:
    current = len(content.encode("utf-8"))
    if current >= total_bytes:
        return content
    return content + "x" * (total_bytes - current) + "\n"


def write_reference(root: Path, content: str) -> Path:
    target = root / "alpha" / "references" / "guia.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def build_root(tmp_path: Path, *, exclusions: dict | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    config = {
        "schema_version": 1,
        "system": "reference-index",
        "index_threshold_bytes": THRESHOLD,
        "exclusions": exclusions or {},
    }
    (root / CONFIG_RELATIVE).write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    write_reference(root, NAVIGABLE)
    return root


def test_shipped_reference_indexes_are_valid() -> None:
    assert validate_reference_indexes(ROOT) == []


def test_shipped_threshold_selects_only_long_references() -> None:
    config = json.loads((ROOT / CONFIG_RELATIVE).read_text(encoding="utf-8"))
    threshold = config["index_threshold_bytes"]
    references = [path for path in ROOT.glob("*/references/**/*.md") if path.is_file()]
    long_references = [path for path in references if path.stat().st_size >= threshold]
    assert long_references, "nenhuma referência acima do limiar: o lint não teria efeito"
    assert len(long_references) < len(references), "o limiar não distingue referência longa de curta"


def test_short_reference_without_index_passes(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    assert validate_reference_indexes(root) == []


def test_missing_index_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_reference(root, pad("# Guia\n\n## Quando ler este arquivo\n\nSempre.\n\n## Secao\n\nconteudo\n", THRESHOLD + 1))
    errors = validate_reference_indexes(root)
    assert any("sem seção de índice" in error for error in errors), errors


def test_missing_conditional_block_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_reference(root, pad("# Guia\n\n## Índice\n\n- [Secao](#secao)\n\n## Secao\n\nconteudo\n", THRESHOLD + 1))
    errors = validate_reference_indexes(root)
    assert any("Quando ler este arquivo" in error for error in errors), errors


def test_unresolved_anchor_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    content = NAVIGABLE.replace("(#secao-um)", "(#secao-inexistente)")
    write_reference(root, pad(content, THRESHOLD + 1))
    errors = validate_reference_indexes(root)
    assert any("âncora de índice não resolve" in error for error in errors), errors


def test_heading_absent_from_the_index_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    content = NAVIGABLE + "\n## Secao dois\n\noutro conteudo\n"
    write_reference(root, pad(content, THRESHOLD + 1))
    errors = validate_reference_indexes(root)
    assert any("seção ausente do índice" in error and "secao-dois" in error for error in errors), errors


def test_non_local_index_entry_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    content = NAVIGABLE.replace("- [Secao um](#secao-um)", "- [Secao um](outra-referencia.md)")
    write_reference(root, pad(content, THRESHOLD + 1))
    errors = validate_reference_indexes(root)
    assert any("não é âncora local" in error for error in errors), errors


def test_empty_index_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    content = "# Guia\n\n## Quando ler este arquivo\n\nSempre.\n\n## Índice\n\n## Secao um\n\nconteudo\n"
    write_reference(root, pad(content, THRESHOLD + 1))
    errors = validate_reference_indexes(root)
    assert any("sem nenhuma entrada" in error for error in errors), errors


def test_conditional_and_index_headings_are_not_index_entries(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_reference(root, pad(NAVIGABLE, THRESHOLD + 1))
    assert validate_reference_indexes(root) == []


def test_exclusion_covers_a_long_reference(tmp_path: Path) -> None:
    root = build_root(tmp_path, exclusions={"alpha/references/guia.md": {"reason": "template preenchido"}})
    write_reference(root, pad("# Guia\n\n## Secao\n\nconteudo\n", THRESHOLD + 1))
    assert validate_reference_indexes(root) == []


def test_exclusion_for_a_missing_file_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path, exclusions={"alpha/references/ausente.md": {"reason": "orfa"}})
    errors = validate_reference_indexes(root)
    assert any("não corresponde a referência descoberta" in error for error in errors), errors


def test_exclusion_without_a_reason_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path, exclusions={"alpha/references/guia.md": {"reason": "  "}})
    errors = validate_reference_indexes(root)
    assert any("sem justificativa" in error for error in errors), errors


def test_exclusion_below_the_threshold_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path, exclusions={"alpha/references/guia.md": {"reason": "desnecessaria"}})
    errors = validate_reference_indexes(root)
    assert any("exceção desnecessária" in error for error in errors), errors


def test_missing_config_blocks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    errors = validate_reference_indexes(root)
    assert any(CONFIG_RELATIVE in error for error in errors), errors


def test_reference_discovery_without_matches_blocks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / CONFIG_RELATIVE).write_text(
        json.dumps({"schema_version": 1, "system": "reference-index", "index_threshold_bytes": THRESHOLD}),
        encoding="utf-8",
    )
    errors = validate_reference_indexes(root)
    assert any("nenhuma referência encontrada" in error for error in errors), errors
