"""Foreign audit-escape artifacts must not contaminate a different issue's risk gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "entregar-issue/scripts/validate_risk_saturation.py"
sys.path.insert(0, str(SCRIPT.parent))
from risk_inference import CANONICAL_RISK_FAMILIES  # noqa: E402 - script module path added above
from validate_risk_saturation import required_escape_dimensions  # noqa: E402 - script module path added above


def test_foreign_closure_is_not_inferred_from_neighboring_file(tmp_path):
    closure = {"escapes": [{"escape_id": "previous-issue", "status": "passed",
      "required_risk_families": ["structural-contract"], "required_attack_dimensions": [
      {"risk_family": "structural-contract", "surface": "old-ui", "dimension": "old-field"},
      {"risk_family": "structural-contract", "surface": "old-ui", "dimension": "old-permission"}]}]}
    path = tmp_path / "audit-escape-closure.json"
    path.write_text(json.dumps(closure), encoding="utf-8")
    errors = []
    assert required_escape_dimensions(None, errors) == set()
    assert errors == []
    assert required_escape_dimensions(path, errors) == {
        ("structural-contract", "old-ui", "old-field"),
        ("structural-contract", "old-ui", "old-permission"),
    }


def test_risk_validator_requires_explicit_escape_binding(tmp_path):
    matrix = {"schema_version": 1, "head_sha": "a" * 40,
              "requirements": [], "uncovered_requirements": []}
    saturation = {"schema_version": 1, "head_sha": "a" * 40,
                  "families": [{"family": family, "applicable": False,
                                "reason": "No obligation activates this family",
                                "status": "not-applicable", "control_ids": [], "dimensions": []}
                               for family in sorted(CANONICAL_RISK_FAMILIES)],
                  "material_families_missing_controls": []}
    escape = {"escapes": [{"escape_id": "old-issue", "status": "passed",
               "required_risk_families": ["structural-contract"],
               "required_attack_dimensions": [
                   {"risk_family": "structural-contract", "surface": "old-ui", "dimension": "old-field"},
                   {"risk_family": "structural-contract", "surface": "old-ui", "dimension": "old-permission"}]}]}
    for filename, payload in [("requirement-attack-matrix.json", matrix),
                              ("risk-saturation.json", saturation),
                              ("audit-escape-closure.json", escape)]:
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    args = [sys.executable, str(SCRIPT), "--attack-matrix",
            str(tmp_path / "requirement-attack-matrix.json"),
            "--risk-saturation", str(tmp_path / "risk-saturation.json")]
    clean = subprocess.run(args, text=True, capture_output=True, check=False)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    relevant = subprocess.run([*args, "--audit-escape-closure",
                             str(tmp_path / "audit-escape-closure.json"),
                             "--target-repository", "example/consumer",
                             "--target-issue-number", "125",
                             "--target-pull-request-number", "126",
                             "--target-head-sha", "a" * 40],
                             text=True, capture_output=True, check=False)
    assert relevant.returncode == 2
    assert "audit escape required attack dimensions are not covered" in relevant.stdout
    assert "explicit audit escape closure lacks current-target subject binding" in relevant.stdout
