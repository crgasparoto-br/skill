from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExternalAuditTests(unittest.TestCase):
    def test_signed_report_validates_and_tampering_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_key = root / "private.pem"
            public_key = root / "public.pem"
            report = root / "external-audit.json"
            registry = root / "trusted-auditors.json"
            subprocess.run([
                sys.executable, str(ROOT / "scripts/generate_auditor_keypair.py"),
                "--private-out", str(private_key), "--public-out", str(public_key),
            ], check=True, capture_output=True, text=True)
            public_pem = public_key.read_text(encoding="utf-8")
            registry.write_text(json.dumps({
                "schema_version": 1,
                "auditors": [{
                    "key_id": "auditor-1",
                    "name": "Independent Auditor",
                    "enabled": True,
                    "repositories": ["owner/repo"],
                    "public_key_pem": public_pem,
                    "public_key_sha256": hashlib.sha256(public_pem.encode("utf-8")).hexdigest(),
                }],
            }), encoding="utf-8")
            subprocess.run([
                sys.executable, str(ROOT / "scripts/init_external_audit_report.py"),
                "--repository", "owner/repo", "--issue", "7", "--base-ref", "main",
                "--head-sha", "a" * 40, "--base-sha", "b" * 40,
                "--merge-preview-sha", "c" * 40, "--orchestration-cycle", "2",
                "--implementation-context-id", "implementation-context-1",
                "--audit-context-id", "audit-context-2",
                "--context-proof-kind", "agent-run-id",
                "--context-proof-value", "audit-context-2",
                "--context-proof-issuer", "independent-runner",
                "--origin", "Independent runner outside the implementation context",
                "--out", str(report),
            ], check=True, stdout=subprocess.PIPE, text=True)
            value = json.loads(report.read_text(encoding="utf-8"))
            value.update({
                "head_sha_after": value["head_sha"],
                "base_sha_after": value["base_sha"],
                "merge_preview_sha_after": value["merge_preview_sha"],
                "verdict": "approved",
                "evidence": [{
                    "id": "EV-1",
                    "claim": "The issue contract was checked against the frozen runtime.",
                    "source": "independent execution log",
                    "observed_at": value["issued_at"],
                }],
            })
            report.write_text(json.dumps(value), encoding="utf-8")
            subprocess.run([
                sys.executable, str(ROOT / "scripts/sign_external_audit_report.py"),
                str(report), "--private-key", str(private_key), "--key-id", "auditor-1",
            ], check=True, capture_output=True, text=True)
            valid = subprocess.run([
                sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                str(report), "--trusted-auditors", str(registry),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(0, valid.returncode, valid.stderr)

            duplicate_registry = root / "duplicate-trusted-auditors.json"
            duplicate_value = json.loads(registry.read_text(encoding="utf-8"))
            duplicate_value["auditors"].append(dict(duplicate_value["auditors"][0]))
            duplicate_registry.write_text(json.dumps(duplicate_value), encoding="utf-8")
            duplicate = subprocess.run([
                sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                str(report), "--trusted-auditors", str(duplicate_registry),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(1, duplicate.returncode)
            self.assertIn("unique", duplicate.stderr.lower())

            tampered = json.loads(report.read_text(encoding="utf-8"))
            tampered["origin"] = "changed after signature"
            report.write_text(json.dumps(tampered), encoding="utf-8")
            invalid = subprocess.run([
                sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                str(report), "--trusted-auditors", str(registry),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(1, invalid.returncode)
            self.assertIn("signature", invalid.stderr.lower())


    def test_signer_rejects_same_context_and_approved_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_key = root / "private.pem"
            public_key = root / "public.pem"
            report = root / "external-audit.json"
            subprocess.run([
                sys.executable, str(ROOT / "scripts/generate_auditor_keypair.py"),
                "--private-out", str(private_key), "--public-out", str(public_key),
            ], check=True, capture_output=True, text=True)
            subprocess.run([
                sys.executable, str(ROOT / "scripts/init_external_audit_report.py"),
                "--repository", "owner/repo", "--issue", "7", "--base-ref", "main",
                "--head-sha", "a" * 40, "--base-sha", "b" * 40,
                "--merge-preview-sha", "c" * 40, "--orchestration-cycle", "2",
                "--implementation-context-id", "implementation-context-1",
                "--audit-context-id", "audit-context-2",
                "--context-proof-kind", "agent-run-id",
                "--context-proof-value", "audit-context-2",
                "--context-proof-issuer", "independent-runner",
                "--origin", "Independent runner outside the implementation context",
                "--out", str(report),
            ], check=True, stdout=subprocess.PIPE, text=True)
            value = json.loads(report.read_text(encoding="utf-8"))
            value.update({
                "head_sha_after": value["head_sha"],
                "base_sha_after": value["base_sha"],
                "merge_preview_sha_after": value["merge_preview_sha"],
                "verdict": "approved",
                "evidence": [{
                    "id": "EV-1",
                    "claim": "The issue contract was independently checked against runtime.",
                    "source": "independent execution log",
                    "observed_at": value["issued_at"],
                }],
            })
            value["audit_context_id"] = value["implementation_context_id"]
            value["source_context_proof"]["value"] = value["audit_context_id"]
            report.write_text(json.dumps(value), encoding="utf-8")
            same_context = subprocess.run([
                sys.executable, str(ROOT / "scripts/sign_external_audit_report.py"),
                str(report), "--private-key", str(private_key), "--key-id", "auditor-1",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(2, same_context.returncode)
            self.assertIn("audit context", same_context.stderr.lower())

            value["audit_context_id"] = "audit-context-2"
            value["source_context_proof"]["value"] = "audit-context-2"
            value["findings"] = [{
                "id": "A-1",
                "severity": "high",
                "description": "A material requirement remains unverified.",
                "evidence": ["EV-1"],
                "escape_category": "execution-state-gap",
                "required_gate": "F28",
                "literal_case": "Invalid configuration still reaches the outbound callback.",
                "sibling_cases": ["Disabled state reaches outbound", "Missing secret reaches outbound"],
                "audit_escape": False,
                "remediation_mode": "targeted-remediation",
                "reusable_control_requirement": "Add a reusable negative control for invalid outbound state.",
            }]
            report.write_text(json.dumps(value), encoding="utf-8")
            with_finding = subprocess.run([
                sys.executable, str(ROOT / "scripts/sign_external_audit_report.py"),
                str(report), "--private-key", str(private_key), "--key-id", "auditor-1",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(2, with_finding.returncode)
            self.assertIn("approved report", with_finding.stderr.lower())

    def test_solo_report_roundtrip_and_exact_registry_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_key = root / "private.pem"
            public_key = root / "public.pem"
            report = root / "solo-external-audit.json"
            registry = root / "trusted-auditors.json"
            subprocess.run([
                sys.executable, str(ROOT / "scripts/generate_auditor_keypair.py"),
                "--private-out", str(private_key), "--public-out", str(public_key),
            ], check=True, capture_output=True, text=True)
            public_pem = public_key.read_text(encoding="utf-8")
            registry.write_text(json.dumps({
                "schema_version": 1,
                "auditors": [{
                    "key_id": "solo-key-1",
                    "name": "Configured Solo Operator",
                    "enabled": True,
                    "repositories": ["owner/repo"],
                    "public_key_pem": public_pem,
                    "public_key_sha256": hashlib.sha256(public_pem.encode("utf-8")).hexdigest(),
                }],
            }), encoding="utf-8")
            subprocess.run([
                sys.executable, str(ROOT / "scripts/init_external_audit_report.py"),
                "--repository", "owner/repo", "--issue", "175", "--base-ref", "develop",
                "--head-sha", "a" * 40, "--base-sha", "b" * 40,
                "--merge-preview-sha", "c" * 40, "--orchestration-cycle", "1",
                "--implementation-context-id", "implementation-context-175",
                "--audit-context-id", "solo-context-175",
                "--context-proof-kind", "agent-run-id",
                "--context-proof-value", "solo-context-175",
                "--context-proof-issuer", "configured-runner",
                "--origin", "Configured solo context; no third-party human approval claimed",
                "--assurance-mode", "single-operator-separate-context",
                "--operator-github-id", "12345", "--pull-request", "176",
                "--issue-body-sha256", "d" * 64, "--out", str(report),
            ], check=True, stdout=subprocess.PIPE, text=True)
            value = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(value["assurance_mode"], "single-operator-separate-context")
            self.assertFalse(value["independent"])
            self.assertEqual(value["pull_request"], 176)
            self.assertEqual(value["operator_github_id"], 12345)
            self.assertEqual(value["issue_body_sha256"], "d" * 64)
            value["evidence"] = [{
                "id": "EV-SOLO-1",
                "claim": "The exact target was checked in the configured solo context.",
                "source": "configured execution log",
                "observed_at": value["issued_at"],
            }]
            report.write_text(json.dumps(value), encoding="utf-8")
            subprocess.run([
                sys.executable, str(ROOT / "scripts/sign_external_audit_report.py"),
                str(report), "--private-key", str(private_key), "--key-id", "solo-key-1",
            ], check=True, capture_output=True, text=True)

            valid = subprocess.run([
                sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                str(report), "--trusted-auditors", str(registry), "--exact-repository-only",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(0, valid.returncode, valid.stderr)

            multi_registry = root / "multi-exact-trusted-auditors.json"
            multi_value = json.loads(registry.read_text(encoding="utf-8"))
            multi_value["auditors"][0]["repositories"] = ["owner/repo", "owner/other"]
            multi_registry.write_text(json.dumps(multi_value), encoding="utf-8")
            multi_exact = subprocess.run([
                sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                str(report), "--trusted-auditors", str(multi_registry), "--exact-repository-only",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(0, multi_exact.returncode, multi_exact.stderr)

            for index, malformed_scope in enumerate(("owner", "owner/repo/extra", "owner/repo with space")):
                malformed_registry = root / f"malformed-scope-{index}.json"
                malformed_value = json.loads(registry.read_text(encoding="utf-8"))
                malformed_value["auditors"][0]["repositories"] = [malformed_scope]
                malformed_registry.write_text(json.dumps(malformed_value), encoding="utf-8")
                malformed_result = subprocess.run([
                    sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                    str(report), "--trusted-auditors", str(malformed_registry), "--exact-repository-only",
                ], check=False, capture_output=True, text=True)
                self.assertEqual(1, malformed_result.returncode, malformed_scope)
                self.assertIn("owner/repo", malformed_result.stderr.lower())

            duplicate_scope_registry = root / "duplicate-scope-trusted-auditors.json"
            duplicate_scope_value = json.loads(registry.read_text(encoding="utf-8"))
            duplicate_scope_value["auditors"][0]["repositories"] = ["owner/repo", "owner/repo"]
            duplicate_scope_registry.write_text(json.dumps(duplicate_scope_value), encoding="utf-8")
            duplicate_scope_result = subprocess.run([
                sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                str(report), "--trusted-auditors", str(duplicate_scope_registry), "--exact-repository-only",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(1, duplicate_scope_result.returncode)
            self.assertIn("duplicate", duplicate_scope_result.stderr.lower())

            wildcard_registry = root / "wildcard-trusted-auditors.json"
            wildcard_value = json.loads(registry.read_text(encoding="utf-8"))
            wildcard_value["auditors"][0]["repositories"] = ["owner/*"]
            wildcard_registry.write_text(json.dumps(wildcard_value), encoding="utf-8")
            compatible = subprocess.run([
                sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                str(report), "--trusted-auditors", str(wildcard_registry),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(0, compatible.returncode, compatible.stderr)
            rejected_wildcard = subprocess.run([
                sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                str(report), "--trusted-auditors", str(wildcard_registry), "--exact-repository-only",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(1, rejected_wildcard.returncode)
            self.assertIn("wildcard", rejected_wildcard.stderr.lower())

            duplicate = report.read_text(encoding="utf-8").rstrip()
            duplicate = duplicate[:-1] + ', "repository": "owner/repo"}\n'
            report.write_text(duplicate, encoding="utf-8")
            duplicate_result = subprocess.run([
                sys.executable, str(ROOT / "scripts/validate_external_audit_report.py"),
                str(report), "--trusted-auditors", str(registry),
            ], check=False, capture_output=True, text=True)
            self.assertEqual(1, duplicate_result.returncode)
            self.assertIn("duplicate", duplicate_result.stderr.lower())

    def test_solo_fields_without_mode_are_rejected_by_signer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "legacy-shaped-report.json"
            subprocess.run([
                sys.executable, str(ROOT / "scripts/init_external_audit_report.py"),
                "--repository", "owner/repo", "--issue", "175", "--base-ref", "develop",
                "--head-sha", "a" * 40, "--base-sha", "b" * 40,
                "--merge-preview-sha", "c" * 40, "--orchestration-cycle", "1",
                "--implementation-context-id", "implementation-context-175",
                "--audit-context-id", "legacy-context-175", "--context-proof-kind", "agent-run-id",
                "--context-proof-value", "legacy-context-175", "--context-proof-issuer", "runner",
                "--origin", "Legacy independent audit", "--out", str(report),
            ], check=True, stdout=subprocess.PIPE, text=True)
            value = json.loads(report.read_text(encoding="utf-8"))
            value["operator_github_id"] = 12345
            report.write_text(json.dumps(value), encoding="utf-8")
            private_key = root / "private.pem"
            public_key = root / "public.pem"
            subprocess.run([
                sys.executable, str(ROOT / "scripts/generate_auditor_keypair.py"),
                "--private-out", str(private_key), "--public-out", str(public_key),
            ], check=True, capture_output=True, text=True)
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts/sign_external_audit_report.py"),
                str(report), "--private-key", str(private_key), "--key-id", "legacy-key",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(2, result.returncode)
            self.assertIn("solo fields", result.stderr.lower())
            value.pop("operator_github_id")
            value["assurance_mode"] = "unrecognized-mode"
            report.write_text(json.dumps(value), encoding="utf-8")
            unknown_mode = subprocess.run([
                sys.executable, str(ROOT / "scripts/sign_external_audit_report.py"),
                str(report), "--private-key", str(private_key), "--key-id", "legacy-key",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(2, unknown_mode.returncode)
            self.assertIn("unknown assurance_mode", unknown_mode.stderr)

    def test_prior_internal_approval_turns_independent_finding_into_audit_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_key = root / "private.pem"
            public_key = root / "public.pem"
            report = root / "external-audit.json"
            subprocess.run([
                sys.executable, str(ROOT / "scripts/generate_auditor_keypair.py"),
                "--private-out", str(private_key), "--public-out", str(public_key),
            ], check=True, capture_output=True, text=True)
            subprocess.run([
                sys.executable, str(ROOT / "scripts/init_external_audit_report.py"),
                "--repository", "owner/repo", "--issue", "7", "--base-ref", "main",
                "--head-sha", "a" * 40, "--base-sha", "b" * 40,
                "--merge-preview-sha", "c" * 40, "--orchestration-cycle", "2",
                "--implementation-context-id", "implementation-context-1",
                "--audit-context-id", "audit-context-2",
                "--context-proof-kind", "agent-run-id",
                "--context-proof-value", "audit-context-2",
                "--context-proof-issuer", "independent-runner",
                "--origin", "Independent runner outside the implementation context",
                "--prior-internal-head-sha", "a" * 40,
                "--prior-internal-report-sha256", "d" * 64,
                "--prior-internal-assurance-level", "controller-adversarial",
                "--prior-internal-approved-at", "2026-07-28T09:00:00Z",
                "--out", str(report),
            ], check=True, stdout=subprocess.PIPE, text=True)
            value = json.loads(report.read_text(encoding="utf-8"))
            value.update({
                "head_sha_after": value["head_sha"],
                "base_sha_after": value["base_sha"],
                "merge_preview_sha_after": value["merge_preview_sha"],
                "verdict": "rejected",
                "evidence": [{
                    "id": "EV-1", "claim": "Independent execution reproduced a blocking defect.",
                    "source": "independent log", "observed_at": value["issued_at"],
                }],
                "findings": [{
                    "id": "A-ESC", "severity": "high",
                    "description": "The internally approved SHA still lacks a required retry path.",
                    "evidence": ["EV-1"], "escape_category": "execution-state-gap",
                    "required_gate": "F28",
                    "literal_case": "Profile query fails and no local retry action is rendered.",
                    "sibling_cases": ["Patient request query fails without retry", "Entitlement query fails without retry"],
                    "audit_escape": False,
                    "remediation_mode": "targeted-remediation",
                "reusable_control_requirement": "Add a reusable recoverable-error retry control for every query section.",
                }],
            })
            report.write_text(json.dumps(value), encoding="utf-8")
            rejected = subprocess.run([
                sys.executable, str(ROOT / "scripts/sign_external_audit_report.py"),
                str(report), "--private-key", str(private_key), "--key-id", "auditor-1",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(2, rejected.returncode)
            self.assertIn("audit escapes", rejected.stderr.lower())

            value["findings"][0]["audit_escape"] = True
            report.write_text(json.dumps(value), encoding="utf-8")
            accepted = subprocess.run([
                sys.executable, str(ROOT / "scripts/sign_external_audit_report.py"),
                str(report), "--private-key", str(private_key), "--key-id", "auditor-1",
            ], check=False, capture_output=True, text=True)
            self.assertEqual(0, accepted.returncode, accepted.stderr)



if __name__ == "__main__":
    unittest.main()
