from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_evidence_source_locations.py"


def run(tmp_path: Path, snippets: list[str], files: dict[str, str]) -> subprocess.CompletedProcess[str]:
    root = tmp_path / "repo"
    root.mkdir()
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"checks": snippets}), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repository-root", str(root), "--evidence", str(evidence)],
        capture_output=True, text=True, check=False,
    )


def test_exact_and_basename_valid(tmp_path: Path) -> None:
    proc = run(tmp_path, ["apps/web/page.ts:1-3", "page.ts:2,3"], {"apps/web/page.ts": "a\nb\nc\n"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "validated 3" in proc.stdout


def test_stale_ref_after_refactor_fails(tmp_path: Path) -> None:
    proc = run(tmp_path, ["scripts/categories-interface.mjs:1019-1020"], {"scripts/categories-interface.mjs": "a\nb\n"})
    assert proc.returncode == 2
    assert "outside 1-2" in proc.stdout


def test_missing_source_fails(tmp_path: Path) -> None:
    proc = run(tmp_path, ["src/removed.ts:1-3"], {"src/active.ts": "x\n"})
    assert proc.returncode == 2
    assert "missing source" in proc.stdout


def test_ambiguous_basename_fails(tmp_path: Path) -> None:
    proc = run(tmp_path, ["page.ts:1"], {"a/page.ts": "a\n", "b/page.ts": "b\n"})
    assert proc.returncode == 2
    assert "ambiguous basename" in proc.stdout


def test_inverted_or_zero_ranges_fail(tmp_path: Path) -> None:
    proc = run(tmp_path, ["page.ts:3-2", "page.ts:0"], {"page.ts": "a\nb\nc\n"})
    assert proc.returncode == 2
    assert "page.ts:3-2" in proc.stdout
    assert "page.ts:0" in proc.stdout


def test_empty_evidence_fails_closed(tmp_path: Path) -> None:
    proc = run(tmp_path, ["CI: completed/success"], {"page.ts": "a\n"})
    assert proc.returncode == 2
    assert "no source locations" in proc.stdout


def test_ignores_urls_without_line_anchors(tmp_path: Path) -> None:
    proc = run(tmp_path, ["https://github.com/a/b", "CI run 123", "src/page.ts:1"], {"src/page.ts": "line\n"})
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_symlink_outside_repository_fails(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    secret = tmp_path / "outside.ts"
    secret.write_text("private\n", encoding="utf-8")
    (root / "link.ts").symlink_to(secret)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"references": ["link.ts:1"]}), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--repository-root", str(root), "--evidence", str(evidence)], capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "symlink or path escapes" in proc.stdout
