"""Offline tests for release evidence gate (no real identities or credentials)."""
import hashlib
import tempfile
import unittest
from pathlib import Path

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

    def test_rejects_wrong_lock_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "requirements.lock.txt"
            lock.write_bytes(b"audited-lock")
            errors = validate(complete(), HEAD, lock_path=lock)
        self.assertIn("dependency lock hash differs from audited file", errors)

    def test_accepts_matching_artifact_identifiers(self):
        doc = complete()
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "requirements.lock.txt"
            lock.write_bytes(b"audited-lock")
            doc["dependency_lock_sha256"] = hashlib.sha256(lock.read_bytes()).hexdigest()
            errors = validate(doc, HEAD, lock_path=lock, deployed_image_digest=doc["image_digest"])
        self.assertEqual(errors, [])

    def test_rejects_deployed_digest_mismatch(self):
        errors = validate(complete(), HEAD, deployed_image_digest="sha256:" + "d" * 64)
        self.assertIn("deployed image digest differs from evidence", errors)

    def test_rejects_future_timestamp(self):
        doc = complete()
        doc["cases"]["authorized_main"]["timestamp_utc"] = "2099-01-01T00:00:00Z"
        self.assertTrue(any("future" in e for e in validate(doc, HEAD)))

    def test_rejects_impossible_date(self):
        doc = complete()
        doc["cases"]["authorized_main"]["timestamp_utc"] = "2026-99-99T00:00:00Z"
        self.assertTrue(validate(doc, HEAD))

    def test_rejects_unsupported_timestamp(self):
        doc = complete()
        doc["cases"]["authorized_main"]["timestamp_utc"] = "yesterday"
        self.assertTrue(validate(doc, HEAD))


if __name__ == "__main__":
    unittest.main()
