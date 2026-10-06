from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_audit_preflight_understands_code_growth():
 s=(ROOT/'SKILL.md').read_text(); pre=(ROOT/'scripts/check_delivery_preflight.py').read_text(); cert=(ROOT/'scripts/validate_handoff_certificate.py').read_text()
 assert 'code-growth-audit.md' in s
 assert 'check_code_growth_evidence.py' in pre
 assert '"code_growth"' in cert and 'certified CODE-GROWTH-001 did not pass' in cert
