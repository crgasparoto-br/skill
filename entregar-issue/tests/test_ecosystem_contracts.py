from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

SKILL = Path(__file__).resolve().parents[1]
PUBLIC_ROOT = SKILL.parent


class EcosystemContractTests(unittest.TestCase):
    def test_all_public_skills_share_contract_version_and_schema(self):
        result = subprocess.run([
            sys.executable,
            str(SKILL / "scripts/controller_cli.py"),
            "validate-contracts",
            "--skills-root",
            str(PUBLIC_ROOT),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_reused_result_requires_verifiable_source(self):
        schema = json.loads((SKILL / "schemas/subskill-result.schema.json").read_text())
        validator = Draft202012Validator(schema)
        base = {
            "schema_version": 1,
            "contract_version": "2026-08-20.3",
            "skill": "design-interface",
            "mode": "internal-verification",
            "status": "passed",
            "findings": [],
            "validations": [],
            "artifacts": [],
            "changed_files": [],
            "limitations": [],
            "requires_refreeze": False,
            "input_fingerprint": "a" * 64,
            "reused": True,
        }
        self.assertTrue(list(validator.iter_errors(base)))
        base["reuse_source"] = {
            "result_path": ".audit/results/design-interface.json",
            "sha256": "b" * 64,
            "input_fingerprint": "a" * 64,
        }
        self.assertEqual(list(validator.iter_errors(base)), [])
        base["changed_files"] = ["src/page.tsx"]
        self.assertTrue(list(validator.iter_errors(base)))

    def test_audit_remediation_contract_is_byte_identical_with_auditor(self):
        auditor = PUBLIC_ROOT / "auditar-issue"
        if not (auditor / "SKILL.md").exists():
            self.skipTest("cross-skill integration check requires sibling auditar-issue")
        for relative in ("schemas/audit-remediation.schema.json", "scripts/validate_audit_remediation.py"):
            self.assertEqual((SKILL / relative).read_bytes(), (auditor / relative).read_bytes(), relative)

    def test_audit_transport_classifier_is_byte_identical_with_auditor(self):
        auditor = PUBLIC_ROOT / "auditar-issue"
        if not (auditor / "SKILL.md").exists():
            self.skipTest("cross-skill integration check requires sibling auditar-issue")
        relative = "scripts/classify_audit_transport.py"
        self.assertEqual((SKILL / relative).read_bytes(), (auditor / relative).read_bytes(), relative)

    def test_controller_mode_never_allows_operational_approval(self):
        schema = json.loads((SKILL / "schemas/subskill-result.schema.json").read_text())
        allowed = schema["allOf"][0]["then"]["properties"]["data"]["properties"]["controller_disposition"]["enum"]
        self.assertNotIn("approved-operationally", allowed)
        self.assertIn("internally-approved", allowed)


if __name__ == "__main__":
    unittest.main()
