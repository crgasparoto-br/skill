"""Offline tests for release evidence gate (no real identities or credentials)."""
import unittest
from verify_release_evidence import CASES, validate

HEAD = "a" * 40


def complete():
    return {
        "pr_head": HEAD,
        "image_digest": "sha256:" + "b" * 64,
        "dependency_lock_sha256": "c" * 64,
        "cases": {name: {
            "result": "PASS", "kind": "LIVE",
            "timestamp_utc": "2026-10-10T02:00:00Z",
            "evidence_reference": "operator-evidence-" + name,
        } for name in CASES},
    }


class EvidenceTests(unittest.TestCase):
    def test_complete_structure(self):
        self.assertEqual(validate(complete(), HEAD), [])

    def test_rejects_offline_disguised_as_live(self):
        doc = complete()
        doc["cases"]["unauthorized_all_tools"]["kind"] = "OFFLINE"
        self.assertTrue(validate(doc, HEAD))

    def test_rejects_missing_negative_session(self):
        doc = complete()
        del doc["cases"]["unauthorized_zero_github_calls"]
        self.assertTrue(validate(doc, HEAD))

    def test_rejects_mismatched_head(self):
        self.assertTrue(validate(complete(), "d" * 40))

    def test_rejects_missing_artifact_digest(self):
        doc = complete()
        del doc["image_digest"]
        self.assertTrue(validate(doc, HEAD))

    def test_rejects_sensitive_field_names(self):
        doc = complete()
        doc["access_token"] = "do-not-store"
        self.assertTrue(validate(doc, HEAD))

    def test_rejects_unsupported_timestamp(self):
        doc = complete()
        doc["cases"]["authorized_main"]["timestamp_utc"] = "yesterday"
        self.assertTrue(validate(doc, HEAD))


if __name__ == "__main__":
    unittest.main()
