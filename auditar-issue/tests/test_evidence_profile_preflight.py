from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_audit_preflight_is_profile_aware():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    preflight = (ROOT / "scripts" / "check_delivery_preflight.py").read_text(encoding="utf-8")
    cert = (ROOT / "scripts" / "validate_handoff_certificate.py").read_text(encoding="utf-8")
    assert "evidence_profile" in skill
    assert "standard_evidence" in preflight
    assert 'profile == "critical"' in preflight
    assert 'profile == "standard"' in cert
