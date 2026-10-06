from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ISSUE = """# Pedido

## Requisitos

- O sistema deve salvar o pedido.
- Nunca duplicar pedidos.

## Fora de escopo

- Exportar relatorios.
"""


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], capture_output=True, text=True)


def build(tmp_path: Path) -> tuple[Path, Path]:
    issue = tmp_path / "issue.md"
    issue.write_text(ISSUE, encoding="utf-8")
    snapshot = tmp_path / "specification-snapshot.json"
    closure = tmp_path / "requirement-closure.json"
    result = run(
        str(SCRIPTS / "build_specification_snapshot.py"),
        "--repository", "owner/repo", "--issue", "7", "--primary-source-id", "SRC-ISSUE",
        "--source", f"issue-body:SRC-ISSUE:{issue}", "--out", str(snapshot),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    result = run(str(SCRIPTS / "init_requirement_closure.py"), "--specification-snapshot", str(snapshot), "--out", str(closure))
    assert result.returncode == 0, result.stdout + result.stderr
    return snapshot, closure


def coverage(snapshot: Path, closure: Path) -> subprocess.CompletedProcess[str]:
    return run(str(SCRIPTS / "validate_specification_coverage.py"), "--specification-snapshot", str(snapshot), "--requirement-closure", str(closure))


def test_initial_closure_extracts_normative_items_and_is_not_terminal(tmp_path: Path) -> None:
    snapshot, closure = build(tmp_path)
    texts = [item["source_text"] for item in json.loads(closure.read_text(encoding="utf-8"))["obligations"]]
    assert any("salvar o pedido" in text for text in texts)
    assert any("duplicar" in text for text in texts)
    assert not any("Exportar" in text for text in texts)
    result = coverage(snapshot, closure)
    assert result.returncode != 0
    assert "pending" in result.stdout


def test_closure_outside_schema_is_blocked(tmp_path: Path) -> None:
    snapshot, closure = build(tmp_path)
    payload = json.loads(closure.read_text(encoding="utf-8"))
    payload["obligations"][0]["disposition"] = "out-of-scope"
    closure.write_text(json.dumps(payload), encoding="utf-8")
    result = coverage(snapshot, closure)
    assert result.returncode != 0
    assert "requirement closure schema violation" in result.stdout
