"""Regressions for the context budget of control planes and references.

The budget replaces a line-count rule that no validator applied. These tests prove
the three properties that make it a ratchet rather than a suggestion: a file over
the default without an allowance fails, an allowance must equal the current
measurement of its file, and an allowance that is no longer needed is rejected.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

from scripts.validate_context_budget import measure, validate_context_budget

ROOT = Path(__file__).resolve().parents[1]
CONFIG_RELATIVE = "config/context-budget.json"
ALLOWED_FILES = (
    "entregar-issue/SKILL.md",
    "auditar-issue/SKILL.md",
    "corrigir-ci/SKILL.md",
    "entregar-issue/references/terminal-handoff.md",
    "entregar-issue/references/handoff-certificate.md",
    "higienizar-repositorio/references/global-hygiene-profile.md",
)
DEFAULTS = {
    "control_plane": {"max_bytes": 200, "max_line_chars": 80},
    "reference": {"max_bytes": 200, "max_line_chars": 80},
}


def padded(total_bytes: int, max_line_chars: int) -> str:
    """Return content of exactly `total_bytes` whose longest line fits the cap."""
    count = math.ceil(total_bytes / (max_line_chars + 1))
    remaining = total_bytes - count
    lines: list[str] = []
    for index in range(count):
        take = min(max_line_chars, remaining - (count - index - 1))
        lines.append("a" * take)
        remaining -= take
    return "\n".join(lines) + "\n"


def build_root(tmp_path: Path, *, allowances: dict | None = None, defaults: dict | None = None) -> Path:
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    config = {
        "schema_version": 1,
        "system": "context-budget",
        "discovery": {"control_plane": ["*/SKILL.md"], "reference": ["*/references/**/*.md"]},
        "defaults": defaults or DEFAULTS,
        "allowances": allowances or {},
    }
    (root / CONFIG_RELATIVE).write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    write_file(root / "alpha" / "SKILL.md", "curto\n")
    write_file(root / "alpha" / "references" / "guia.md", "curta\n")
    return root


def write_file(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def shipped_subset_root(tmp_path: Path) -> Path:
    """Copy the shipped config and only the files it grants an allowance to."""
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    shutil.copy2(ROOT / CONFIG_RELATIVE, root / CONFIG_RELATIVE)
    for relative in ALLOWED_FILES:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return root


def test_shipped_context_budget_is_valid() -> None:
    assert validate_context_budget(ROOT) == []


def test_shipped_allowances_are_live_measurements() -> None:
    config = json.loads((ROOT / CONFIG_RELATIVE).read_text(encoding="utf-8"))
    allowances = config["allowances"]
    assert sorted(allowances) == sorted(ALLOWED_FILES)
    for relative, allowance in allowances.items():
        path = ROOT / relative
        assert path.is_file(), relative
        assert str(allowance.get("reason", "")).strip(), relative
        observed = measure(path)
        for key in ("max_bytes", "max_line_chars"):
            if key in allowance:
                assert allowance[key] == observed[key], f"{relative}:{key} divergiu da medição"


def test_shipped_allowance_blocks_growth(tmp_path: Path) -> None:
    root = shipped_subset_root(tmp_path)
    assert validate_context_budget(root) == []
    target = root / "entregar-issue" / "SKILL.md"
    target.write_bytes(target.read_bytes() + b"x")
    errors = validate_context_budget(root)
    assert any("entregar-issue/SKILL.md" in error and "medição atual" in error for error in errors), errors


def test_control_plane_exactly_at_the_default_passes(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_file(root / "alpha" / "SKILL.md", padded(200, 80))
    assert validate_context_budget(root) == []


def test_control_plane_one_byte_above_the_default_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_file(root / "alpha" / "SKILL.md", padded(201, 80))
    errors = validate_context_budget(root)
    assert any("alpha/SKILL.md" in error and "max_bytes=201" in error for error in errors), errors


def test_long_line_blocks_even_when_bytes_are_within_the_default(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_file(root / "alpha" / "SKILL.md", "a" * 81 + "\n")
    errors = validate_context_budget(root)
    assert any("alpha/SKILL.md" in error and "max_line_chars=81" in error for error in errors), errors


def test_reference_in_subdirectory_is_discovered(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_file(root / "alpha" / "references" / "deep" / "nested.md", padded(201, 80))
    errors = validate_context_budget(root)
    assert any("alpha/references/deep/nested.md" in error for error in errors), errors


def test_allowance_that_covers_a_file_passes(tmp_path: Path) -> None:
    root = build_root(
        tmp_path,
        allowances={"alpha/SKILL.md": {"max_bytes": 201, "reason": "dívida declarada"}},
    )
    write_file(root / "alpha" / "SKILL.md", padded(201, 80))
    assert validate_context_budget(root) == []


def test_allowance_for_a_compliant_file_blocks(tmp_path: Path) -> None:
    root = build_root(
        tmp_path,
        allowances={"alpha/SKILL.md": {"max_bytes": 201, "reason": "conveniência"}},
    )
    errors = validate_context_budget(root)
    assert any("alpha/SKILL.md" in error and "medição atual" in error for error in errors), errors


def test_allowance_for_a_missing_file_blocks(tmp_path: Path) -> None:
    root = build_root(
        tmp_path,
        allowances={"beta/SKILL.md": {"max_bytes": 201, "reason": "órfã"}},
    )
    errors = validate_context_budget(root)
    assert any("não corresponde a arquivo descoberto" in error for error in errors), errors


def test_allowance_without_a_reason_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path, allowances={"alpha/SKILL.md": {"max_bytes": 201, "reason": "  "}})
    errors = validate_context_budget(root)
    assert any("sem justificativa" in error for error in errors), errors


def test_allowance_with_an_unknown_key_blocks(tmp_path: Path) -> None:
    root = build_root(
        tmp_path,
        allowances={"alpha/SKILL.md": {"max_bytes": 201, "reason": "ok", "max_lines": 10}},
    )
    errors = validate_context_budget(root)
    assert any("chave desconhecida" in error for error in errors), errors


def test_allowance_below_the_current_measurement_blocks(tmp_path: Path) -> None:
    root = build_root(
        tmp_path,
        allowances={"alpha/SKILL.md": {"max_bytes": 250, "reason": "inflada"}},
    )
    write_file(root / "alpha" / "SKILL.md", padded(201, 80))
    errors = validate_context_budget(root)
    assert any("medição atual" in error for error in errors), errors


def test_allowance_that_does_not_exceed_the_default_blocks(tmp_path: Path) -> None:
    root = build_root(
        tmp_path,
        allowances={"alpha/SKILL.md": {"max_bytes": 200, "reason": "igual ao padrão"}},
    )
    errors = validate_context_budget(root)
    assert any("exceção desnecessária" in error for error in errors), errors


def test_missing_config_blocks(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    errors = validate_context_budget(root)
    assert any(CONFIG_RELATIVE in error for error in errors), errors


def test_discovery_pattern_without_matches_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    (root / "alpha" / "references" / "guia.md").unlink()
    errors = validate_context_budget(root)
    assert any("não corresponde a nenhum arquivo" in error for error in errors), errors
