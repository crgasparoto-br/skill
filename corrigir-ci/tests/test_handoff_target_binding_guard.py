from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINDING = ROOT / "scripts" / "validate_handoff_target_binding.py"
TERMINAL = ROOT / "scripts" / "validate_ci_terminal_state.py"
SHA_MATERIAL = "a" * 40
SHA_CHILD = "b" * 40


def certificate(subject):
    return {
        "schema_version": 2,
        "status": "ready",
        "contract_version": "2026-08-20.3",
        "subject": subject,
        "identity": {"material_head_sha": SHA_MATERIAL},
        "certificate_commit_policy": {
            "mode": "result-only-child",
            "allowed_paths": [".audit/entregar-issue/handoff-ready.json"],
        },
    }


class HandoffTargetBindingGuardTest(unittest.TestCase):
    def run_script(self, script, cert, *args):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "handoff-ready.json"
            path.write_text(json.dumps(cert), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(script), "--certificate", str(path), *args],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            return proc.returncode, proc.stdout

    def test_current_target_activates_governed_handoff(self):
        cert = certificate({
            "repository": "org/repo",
            "work_item_kind": "issue",
            "work_item_number": 42,
            "pull_request": 77,
            "base_ref": "develop",
            "head_ref": "fix/42",
        })
        code, out = self.run_script(
            BINDING, cert,
            "--repository", "org/repo",
            "--work-item-kind", "issue",
            "--work-item-number", "42",
            "--pull-request", "77",
            "--base-ref", "develop",
            "--head-ref", "fix/42",
        )
        self.assertEqual(code, 0, out)
        self.assertIn("TARGET_BINDING: current-target", out)

    def test_foreign_target_is_ignored_not_latched(self):
        cert = certificate({
            "repository": "org/repo",
            "work_item_kind": "issue",
            "work_item_number": 41,
            "pull_request": 76,
            "base_ref": "develop",
            "head_ref": "fix/41",
        })
        code, out = self.run_script(
            BINDING, cert,
            "--repository", "org/repo",
            "--pull-request", "77",
            "--base-ref", "develop",
            "--head-ref", "fix/42",
        )
        self.assertEqual(code, 3, out)
        self.assertIn("TARGET_BINDING: foreign-target", out)
        self.assertIn("must not activate governed_handoff_observed", out)

    def test_unbound_certificate_is_ignored(self):
        cert = certificate(None)
        code, out = self.run_script(BINDING, cert, "--repository", "org/repo")
        self.assertEqual(code, 3, out)
        self.assertIn("TARGET_BINDING: unbound-or-invalid", out)

    def test_terminal_latch_rejects_foreign_subject(self):
        cert = certificate({
            "repository": "org/repo",
            "pull_request": 76,
            "base_ref": "develop",
            "head_ref": "fix/41",
        })
        code, out = self.run_script(
            TERMINAL, cert,
            "--expected-material-head-sha", SHA_MATERIAL,
            "--current-head-sha", SHA_CHILD,
            "--current-parent-sha", SHA_MATERIAL,
            "--current-changed-path", ".audit/entregar-issue/handoff-ready.json",
            "--repository", "org/repo",
            "--pull-request", "77",
            "--base-ref", "develop",
            "--head-ref", "fix/42",
        )
        self.assertEqual(code, 2, out)
        self.assertIn("not bound to the current CI target", out)
        self.assertIn("RECOVERY: fresh-handoff-required", out)


if __name__ == "__main__":
    unittest.main()
