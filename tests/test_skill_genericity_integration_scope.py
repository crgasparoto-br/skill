"""Ensure permanent skill assets remain gated while operational MCP endpoints are allowed."""

import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTANCE_HOST = "https://" + "auth.tenant-domain.org"
VALIDATOR = runpy.run_path(
    str(ROOT / "entregar-issue/scripts/validate_skill_genericity.py")
)["validate_skill_genericity"]


def test_operational_integration_keeps_instance_specific_oauth_hostname(tmp_path):
    directory = tmp_path / "integrations" / "github-delivery-mcp"
    directory.mkdir(parents=True)
    (directory / "deployment.md").write_text(INSTANCE_HOST, encoding="utf-8")
    assert VALIDATOR(tmp_path) == []


def test_permanent_skill_hostnames_still_rejected(tmp_path):
    directory = tmp_path / "entregar-issue"
    directory.mkdir()
    (directory / "SKILL.md").write_text(INSTANCE_HOST, encoding="utf-8")
    errors = VALIDATOR(tmp_path)
    assert any("auth.tenant-domain.org" in error for error in errors)
