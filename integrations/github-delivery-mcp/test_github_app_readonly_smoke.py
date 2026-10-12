"""Read-only VPS smoke produces only metadata and refuses unsafe results."""
import io
import json
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr

import github_app_readonly_smoke as target


class ReadonlySmokeTests(unittest.TestCase):
    def test_branch_and_checks_from_readonly_app(self):
        sha = "a" * 40
        with patch.object(target, "mint_token", return_value="SECRET") as mint, patch.object(
                target, "_get_json", side_effect=[
                    {"commit": {"sha": sha}}, {"total_count": 1, "check_runs": [{}]}
                ]) as get:
            result = target.smoke()
        self.assertEqual(result["head_sha"], sha)
        self.assertEqual(result["check_run_count"], 1)
        self.assertNotIn("SECRET", str(result))
        mint.assert_called_once_with(
            repository="crgasparoto-br/training-system",
            operation="read-checks", server_authorized=True)
        self.assertEqual(get.call_count, 2)

    def test_missing_checks_page_rejected(self):
        with patch.object(target, "mint_token", return_value="SECRET"), patch.object(
                target, "_get_json", side_effect=[
                    {"commit": {"sha": "a"*40}},
                    {"total_count": 2, "check_runs": [{}]}]):
            with self.assertRaises(RuntimeError):
                target.smoke()

    def test_invalid_branch_sha_rejected_before_checks(self):
        with patch.object(target, "mint_token", return_value="SECRET"), patch.object(
                target, "_get_json", return_value={"commit": {"sha": "unsafe"}}) as get:
            with self.assertRaises(RuntimeError):
                target.smoke()
            get.assert_called_once()

    def test_errors_redacted(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(target, "smoke", side_effect=RuntimeError("SECRET")), \
                redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(target.main(), 1)
        self.assertNotIn("SECRET", out.getvalue() + err.getvalue())

    def test_prints_safe_metadata_only(self):
        out = io.StringIO()
        with patch.object(target, "smoke", return_value={
                "repository": "crgasparoto-br/training-system", "branch": "develop",
                "head_sha": "a"*40, "check_run_count": 0, "read_only": True}), \
                redirect_stdout(out):
            self.assertEqual(target.main(), 0)
        self.assertTrue(json.loads(out.getvalue())["read_only"])
