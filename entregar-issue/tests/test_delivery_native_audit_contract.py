from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "classify_audit_transport.py"


def run_manifest(value: dict):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "manifest.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--manifest", str(path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return proc.returncode, proc.stdout.strip()


def base_manifest() -> dict:
    anchor = "a" * 40
    return {
        "schema_version": 1,
        "repository": "owner/repo",
        "trusted_anchor_sha": anchor,
        "contract": {
            "path": "docs/MASTER_SPEC.md",
            "observed_at_sha": anchor,
            "source_sha256": "b" * 64,
            "canonical": True,
            "audit_mode": "native-github",
            "legacy_handoff_policy": "not-required",
            "github_native_identity": True,
            "exact_sha_evidence": True,
            "independent_review": True,
            "remote_ci_evidence": True,
        },
    }


def test_trusted_native_contract_skips_result_only_handoff():
    code, out = run_manifest(base_manifest())
    assert code == 0, out
    result = json.loads(out)
    assert result["mode"] == "native-github-audit"
    assert result["legacy_handoff_required"] is False


def test_untrusted_candidate_contract_cannot_select_native_mode():
    value = base_manifest()
    value["contract"]["observed_at_sha"] = "c" * 40
    code, out = run_manifest(value)
    assert code == 0, out
    assert json.loads(out)["mode"] == "certified-handoff"


def test_missing_independent_review_falls_back_to_certified_handoff():
    value = base_manifest()
    value["contract"]["independent_review"] = False
    code, out = run_manifest(value)
    assert code == 0, out
    assert json.loads(out)["mode"] == "certified-handoff"


def test_delivery_contract_never_publishes_audit_root_in_native_mode():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ref = (ROOT / "references" / "native-github-audit-contract.md").read_text(encoding="utf-8")
    assert "terminal_native_audit_ready=READY" in skill
    assert "nao criar `.audit/entregar-issue`" in ref


def test_native_mode_has_no_universal_legacy_handoff_requirement():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "Nenhum retorno apto a auditoria independente ocorre sem `handoff-ready.json`" not in skill
    assert "Quando `audit_transport=certified-handoff`, nenhum retorno apto a auditoria independente ocorre sem `handoff-ready.json`" in skill
    assert "Quando `audit_transport=native-github-audit`, manter estado equivalente apenas no runtime/workspace efemero" in skill
    assert "nao criar nem publicar `.audit/entregar-issue/` no repositorio" in skill
