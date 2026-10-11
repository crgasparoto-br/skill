import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_finding_completion.py"
spec = importlib.util.spec_from_file_location("completion", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
SHA = "a" * 40

def ledger():
    return {
        "head_sha": SHA, "previous_finding_ids": ["AUD-1", "AUD-2", "AUD-3"],
        "findings": [{"finding_id": f"AUD-{n}", "disposition": "blocking",
                      "status": "verified", "evidence_head_sha": SHA,
                      "validation_evidence": "focused regression passed"} for n in (1, 2, 3)],
        "ci": {"head_sha": SHA, "conclusion": "success"}, "independent_audit": "approved"
    }

class CompletionGateTests(unittest.TestCase):
    def test_all_verified_independent_approved(self):
        self.assertTrue(module.validate(ledger())[0])

    def test_pr_1316_partial_fix_not_complete(self):
        data = ledger()
        data["findings"][1]["status"] = "open"
        data["findings"][2]["status"] = "implemented-unverified"
        data["ci"]["conclusion"] = "queued"
        self.assertFalse(module.validate(data)[0])

    def test_missing_finding_rejected(self):
        data = ledger()
        data["findings"].pop()
        self.assertIn("previous findings omitted", " ".join(module.validate(data)[1]))

    def test_independent_audit_required(self):
        data = ledger()
        data["independent_audit"] = "internal-only"
        self.assertFalse(module.validate(data)[0])

    def test_excluded_finding_needs_justification(self):
        data = ledger()
        data["findings"][0].update(disposition="out-of-scope", status="not-applicable")
        self.assertFalse(module.validate(data)[0])
        data["findings"][0]["justification"] = "future phase not contracted"
        self.assertTrue(module.validate(data)[0])

    def test_stale_evidence_rejected(self):
        data = ledger()
        data["findings"][0]["evidence_head_sha"] = "b" * 40
        self.assertFalse(module.validate(data)[0])

if __name__ == "__main__":
    unittest.main()
