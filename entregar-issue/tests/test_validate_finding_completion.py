import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_finding_completion.py"
spec = importlib.util.spec_from_file_location("completion", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SHA = "a" * 40


def fixtures():
    ledger = {
        "repository": "example/repo", "pr_number": 90, "audit_round": "round-1",
        "head_sha": SHA,
        "findings": [
            {"finding_id": f"AUD-{n}", "disposition": "blocking", "status": "verified",
             "evidence_head_sha": SHA, "validation_evidence": "test run evidence"} for n in (1, 2, 3)
        ],
    }
    manifest = {"repository": "example/repo", "pr_number": 90, "audit_round": "round-1",
                "finding_ids": ["AUD-1", "AUD-2", "AUD-3"]}
    attestation = {
        "repository": "example/repo", "pr_number": 90, "audit_round": "round-1",
        "head_sha": SHA, "verified_findings": {f"AUD-{n}": SHA for n in (1, 2, 3)},
        "accepted_exclusions": [], "ci": {"head_sha": SHA, "conclusion": "success",
                                           "run_url": "https://github.com/example/repo/actions/runs/1"},
        "independent_audit": "approved", "auditor": "reviewer", "implementer": "developer",
        "audit_url": "https://github.com/example/repo/pull/90#pullrequestreview-1",
    }
    return ledger, manifest, attestation


class CompletionGateTests(unittest.TestCase):
    def test_verified(self):
        self.assertTrue(module.validate(*fixtures())[0])

    def test_missing_trusted_inputs(self):
        ledger, _, _ = fixtures()
        self.assertFalse(module.validate(ledger)[0])

    def test_omitted_finding_even_if_self_declared_previous_altered(self):
        ledger, manifest, att = fixtures()
        ledger["findings"].pop()
        ledger["previous_finding_ids"] = ["AUD-1", "AUD-2"]
        self.assertFalse(module.validate(ledger, manifest, att)[0])

    def test_partial_fix(self):
        ledger, manifest, att = fixtures()
        ledger["findings"][1]["status"] = "open"
        self.assertFalse(module.validate(ledger, manifest, att)[0])

    def test_unverified_evidence(self):
        ledger, manifest, att = fixtures()
        att["verified_findings"].pop("AUD-1")
        self.assertFalse(module.validate(ledger, manifest, att)[0])

    def test_false_audit_approval(self):
        ledger, manifest, att = fixtures()
        att["auditor"] = "developer"
        self.assertFalse(module.validate(ledger, manifest, att)[0])

    def test_stale_ci(self):
        ledger, manifest, att = fixtures()
        att["ci"]["head_sha"] = "b" * 40
        self.assertFalse(module.validate(ledger, manifest, att)[0])

    def test_optional_open_rejected(self):
        ledger, manifest, att = fixtures()
        ledger["findings"][0].update(disposition="optional-recommendation", status="open",
                                     justification="later")
        self.assertFalse(module.validate(ledger, manifest, att)[0])

    def test_optional_requires_accepted_exclusion(self):
        ledger, manifest, att = fixtures()
        ledger["findings"][0].update(disposition="optional-recommendation", status="not-applicable",
                                     justification="future optional request")
        self.assertFalse(module.validate(ledger, manifest, att)[0])
        att["accepted_exclusions"].append("AUD-1")
        self.assertTrue(module.validate(ledger, manifest, att)[0])

    def test_changed_round(self):
        ledger, manifest, att = fixtures()
        ledger["audit_round"] = "other"
        self.assertFalse(module.validate(ledger, manifest, att)[0])

    def test_bad_input(self):
        ledger, manifest, att = fixtures()
        ledger["findings"] = [None]
        self.assertFalse(module.validate(ledger, manifest, att)[0])


if __name__ == "__main__":
    unittest.main()
