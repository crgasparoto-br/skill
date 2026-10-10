"""Ensure permanent skill assets remain gated while operational MCP endpoints are allowed."""

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = runpy.run_path(
    str(ROOT / "entregar-issue/scripts/validate_skill_genericity.py")
)["validate_skill_genericity"]


def test_operational_integration_keeps_instance_specific_oauth_hostname(tmp_path):
    directory = tmp_path / "integrations" / "github-delivery-mcp"
    directory.mkdir(parents=True)
    (directory / "deployment.md").write_text("https://auth.solveritconsultoria.com.br", encoding="utf-8")
    assert VALIDATOR(tmp_path) == []


def test_permanent_skill_hostnames_still_rejected(tmp_path):
    directory = tmp_path / "entregar-issue"
    directory.mkdir()
    (directory / "SKILL.md").write_text("https://auth.solveritconsultoria.com.br", encoding="utf-8")
    errors = VALIDATOR(tmp_path)
    assert any("auth.solveritconsultoria.com.br" in error for error in errors)
