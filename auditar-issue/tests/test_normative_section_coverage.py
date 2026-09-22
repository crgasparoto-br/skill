from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_normative_section_coverage.py"


def write_snapshot(base: Path, text: str) -> tuple[Path, Path]:
    source_dir = base / "specification-sources"
    source_dir.mkdir()
    source = source_dir / "SRC-ISSUE.txt"
    source.write_text(text, encoding="utf-8")
    snapshot = base / "specification-snapshot.json"
    snapshot.write_text(json.dumps({
        "schema_version": 1,
        "repository": "owner/repo",
        "issue": 1,
        "primary_source_id": "SRC-ISSUE",
        "sources": [{
            "id": "SRC-ISSUE",
            "kind": "issue-body",
            "path": "specification-sources/SRC-ISSUE.txt",
            "textual": True,
        }],
    }), encoding="utf-8")
    return snapshot, source


def run(snapshot: Path, closure: Path):
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--specification-snapshot", str(snapshot),
            "--requirement-closure", str(closure),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def test_blocks_when_normative_scope_bullet_is_missing_from_closure() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        snapshot, _ = write_snapshot(
            base,
            "## Escopo\n"
            "- Consolidar primitivas compartilhadas.\n"
            "- Definir grid responsivo e densidade.\n",
        )
        closure = base / "closure.json"
        closure.write_text(json.dumps({
            "obligations": [{
                "source_id": "SRC-ISSUE",
                "source_line": 2,
                "source_text": "Consolidar primitivas compartilhadas.",
            }]
        }), encoding="utf-8")

        proc = run(snapshot, closure)

        assert proc.returncode == 2
        assert "normative specification list item missing" in proc.stdout
        assert "Definir grid responsivo e densidade." in proc.stdout


def test_accepts_complete_normative_scope_coverage_and_ignores_out_of_scope() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        snapshot, _ = write_snapshot(
            base,
            "## Requirements\n"
            "- Consolidate shared primitives.\n"
            "- Define responsive density.\n"
            "\n## Out of scope\n"
            "- Replace the framework.\n",
        )
        closure = base / "closure.json"
        closure.write_text(json.dumps({
            "obligations": [
                {"source_id": "SRC-ISSUE", "source_line": 2, "source_text": "Consolidate shared primitives."},
                {"source_id": "SRC-ISSUE", "source_line": 3, "source_text": "Define responsive density."},
            ]
        }), encoding="utf-8")

        proc = run(snapshot, closure)

        assert proc.returncode == 0, proc.stdout
        assert "verified (2 list items)" in proc.stdout
        assert "Replace the framework" not in proc.stdout
