import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))


def test_audit_preflight_is_profile_aware():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    preflight = (ROOT / "scripts" / "check_delivery_preflight.py").read_text(encoding="utf-8")
    cert = (ROOT / "scripts" / "validate_handoff_certificate.py").read_text(encoding="utf-8")
    assert "evidence_profile" in skill
    assert "standard_evidence" in preflight
    assert 'profile == "critical"' in preflight
    assert 'profile == "standard"' in cert


def test_preflight_revalidates_anchors_in_supplied_source_checkout(tmp_path):
    from test_certified_delivery_preflight import BASE, HEAD, MERGE, make_certificate, run, write_packet

    matrix, risk, inherited, closure = write_packet(tmp_path)
    data = json.loads(closure.read_text())
    data["source_location"] = "src/service.py:1-1"
    closure.write_text(json.dumps(data))
    cert = make_certificate(tmp_path, matrix, risk, inherited, closure)
    data = json.loads(cert.read_text())
    data["validators"]["validate_evidence_source_locations.py"] = "a" * 64
    data["controls"] = {"source_locations": {
        "applicable": True, "status": "passed", "checked": 1, "subject_sha": HEAD,
    }}
    cert.write_text(json.dumps(data))
    source = tmp_path / "material"
    (source / "src").mkdir(parents=True)
    anchored = source / "src/service.py"
    anchored.write_text("value = 1\n")
    arguments = [
        "--certificate", str(cert), "--artifacts-dir", str(tmp_path),
        "--head-sha", HEAD, "--base-sha", BASE, "--merge-preview-sha", MERGE,
        "--contract-version", "2026-08-20.3", "--source-repository-root", str(source),
    ]
    accepted = run(*arguments)
    assert accepted.returncode == 0, accepted.stdout
    anchored.unlink()
    rejected = run(*arguments)
    assert rejected.returncode == 2, rejected.stdout
    assert "source location revalidation" in rejected.stdout
