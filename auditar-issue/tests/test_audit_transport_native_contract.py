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
            check=False, text=True,
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
            "legacy_handoff_policy": "forbidden",
            "github_native_identity": True,
            "exact_sha_evidence": True,
            "independent_review": True,
            "remote_ci_evidence": True,
        },
    }


def test_trusted_base_native_contract_selects_native_github():
    code, out = run_manifest(base_manifest())
    assert code == 0, out
    result = json.loads(out)
    assert result["mode"] == "native-github-audit"
    assert result["legacy_handoff_required"] is False


def test_candidate_cannot_self_exempt_from_handoff():
    value = base_manifest()
    value["contract"]["observed_at_sha"] = "c" * 40
    code, out = run_manifest(value)
    assert code == 0, out
    result = json.loads(out)
    assert result["mode"] == "certified-handoff"
    assert result["reason"] == "candidate-or-untrusted-contract-cannot-self-exempt"


def test_incomplete_native_contract_falls_back_closed():
    value = base_manifest()
    value["contract"]["exact_sha_evidence"] = False
    code, out = run_manifest(value)
    assert code == 0, out
    assert json.loads(out)["mode"] == "certified-handoff"


def test_skill_contract_does_not_require_legacy_handoff_in_native_mode():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    ref = (ROOT / "references" / "native-github-audit-contract.md").read_text(encoding="utf-8")
    assert "native-github-audit" in skill
    assert "ausencia de `.audit/entregar-issue`" in skill
    assert "candidate" in ref.lower()


def test_not_required_policy_selects_native_with_stale_legacy_context():
    """Regression PR 1316: old handoff is not a gate under a trusted native contract."""
    value = base_manifest()
    value["repository"] = "crgasparoto-br/controle_calorias"
    value["contract"]["path"] = "docs/audit/github-native-contract.json"
    value["contract"]["legacy_handoff_policy"] = "not-required"
    value["legacy_handoff"] = {
        "material_head_sha": "d0da06cb" + "0" * 32,
        "published_head_sha": "38a1b6fb" + "0" * 32,
        "status": "stale",
    }
    code, out = run_manifest(value)
    assert code == 0, out
    result = json.loads(out)
    assert result["mode"] == "native-github-audit"
    assert result["legacy_handoff_required"] is False


def test_native_precedence_is_explicit_in_skill_and_reference():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    guide = (ROOT / "references" / "native-github-audit-contract.md").read_text(encoding="utf-8")
    assert "Gate de precedencia (obrigatorio" in skill
    assert "superseded-by-trusted-contract" in guide
    assert "CI verde, isoladamente, tambem nao aprova" in guide
