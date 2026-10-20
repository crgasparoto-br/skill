from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_evidence_source_locations.py"


def run(tmp_path: Path, snippets: list[str], files: dict[str, str], *, require_qualified_paths: bool = False) -> subprocess.CompletedProcess[str]:
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"checks": snippets}), encoding="utf-8")
    argv = [sys.executable, str(SCRIPT), "--repository-root", str(root), "--evidence", str(evidence)]
    if require_qualified_paths:
        argv.append("--require-qualified-paths")
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def test_exact_and_basename_valid(tmp_path: Path) -> None:
    proc = run(tmp_path, ["apps/web/page.ts:1-3", "page.ts:2,3"], {"apps/web/page.ts": "a\nb\nc\n"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "validated 3" in proc.stdout


def test_stale_ref_after_extraction_fails(tmp_path: Path) -> None:
    proc = run(tmp_path, ["src/public-entrypoint.mjs:9-10"], {"src/public-entrypoint.mjs": "a\nb\n"})
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


def test_cross_language_paths_are_validated(tmp_path: Path) -> None:
    proc = run(
        tmp_path,
        ["services/worker.go:1-2", "libraries/adapter.rs:1", "views/screen.vue:1", "scripts/task.sh:1"],
        {
            "services/worker.go": "a\nb\n",
            "libraries/adapter.rs": "a\n",
            "views/screen.vue": "a\n",
            "scripts/task.sh": "a\n",
        },
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "validated 4" in proc.stdout


def test_partial_checkout_requires_qualified_paths(tmp_path: Path) -> None:
    proc = run(
        tmp_path, ["component.vue:1"], {"ui/component.vue": "line\n"},
        require_qualified_paths=True,
    )
    assert proc.returncode == 2
    assert "unqualified source path" in proc.stdout
    accepted = run(
        tmp_path, ["ui/component.vue:1"], {"ui/component.vue": "line\n"},
        require_qualified_paths=True,
    )
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_framework_routes_and_extensionless_build_files(tmp_path: Path) -> None:
    proc = run(
        tmp_path,
        ["src/routes/[user]/page.tsx:1", "infra/Dockerfile:1", "./Makefile:1", "packages/@widgets/adapter.ts:1"],
        {
            "src/routes/[user]/page.tsx": "page\n",
            "infra/Dockerfile": "build\n",
            "Makefile": "rule\n",
            "packages/@widgets/adapter.ts": "adapter\n",
        },
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "validated 4" in proc.stdout


def test_dynamic_route_stale_anchor_must_fail(tmp_path: Path) -> None:
    proc = run(
        tmp_path, ["src/entry.ts:1", "src/routes/[user]/page.tsx:9"],
        {"src/entry.ts": "ok\n", "src/routes/[user]/page.tsx": "short\n"},
    )
    assert proc.returncode == 2
    assert "src/routes/[user]/page.tsx:9 outside 1-1" in proc.stdout


def test_unrecognized_language_anchor_fails_instead_of_being_skipped(tmp_path: Path) -> None:
    proc = run(
        tmp_path, ["src/entry.ts:1", "src/other.go:25"],
        {"src/entry.ts": "ok\n", "src/other.go": "short\n"},
    )
    assert proc.returncode == 2
    assert "src/other.go:25 outside 1-1" in proc.stdout


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


def test_malformed_suffix_and_non_numeric_lines_fail(tmp_path: Path) -> None:
    proc = run(tmp_path, ["src/module.ts:1-INVALID", "src/module.ts:not-a-line", "src/module.ts:1-"], {"src/module.ts": "line\n"})
    assert proc.returncode == 2
    assert proc.stdout.count("malformed line range") == 3


def test_unicode_filename_and_json_key_both_checked(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "café.py").write_text("line\n", encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"src/café.py:9": "code location", "references": ["src/café.py:1"]}), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--repository-root", str(root), "--evidence", str(evidence)], capture_output=True, text=True, check=False)
    assert proc.returncode == 2
    assert "outside 1-1" in proc.stdout


def test_diagnostics_not_evidence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"stderr": "unrelated.ts:999", "references": ["src/app.ts:1"]}), encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.ts").write_text("line\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--repository-root", str(root), "--evidence", str(evidence)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_qualified_paths_with_dot_prefix_partial_checkout(tmp_path: Path) -> None:
    proc = run(tmp_path, ["./src/page.ts:1"], {"src/page.ts": "ok\n"}, require_qualified_paths=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_shorthand_stale_anchor_after_refactor_fails_closed(tmp_path: Path) -> None:
    proc = run(
        tmp_path,
        ["src/tree.ts:1-2 and :919-945", "src/desktop.mjs:1-3 search and :473-635 CRUD"],
        {"src/tree.ts": "a\nb\nc\n", "src/desktop.mjs": "a\nb\nc\n"},
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stdout.count("abbreviated line reference") == 2
    assert "tree.ts and :919-945" in proc.stdout
    assert "desktop.mjs and :473-635" in proc.stdout


def test_shorthand_in_bounds_is_still_ambiguous(tmp_path: Path) -> None:
    proc = run(tmp_path, ["src/page.ts:1 and :2"], {"src/page.ts": "a\nb\n"})
    assert proc.returncode == 2
    assert "repeat the complete source path" in proc.stdout
    accepted = run(tmp_path, ["src/page.ts:1 and src/page.ts:2"], {"src/page.ts": "a\nb\n"})
    assert accepted.returncode == 0, accepted.stdout + accepted.stderr


def test_unrelated_colon_and_multiple_files_do_not_false_positive(tmp_path: Path) -> None:
    proc = run(
        tmp_path,
        ["src/a.py:1 plus prose and value :5; src/b.py:1", "src/a.py:1 and src/b.py:1"],
        {"src/a.py": "a\n", "src/b.py": "b\n"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
