import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("audit_signature", ROOT/"scripts/audit_signature.py")
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


def _base_report():
    return {
        "audit_context_id":"audit-context-123", "implementation_context_id":"impl-context-123",
        "source_context_proof":{"value":"audit-context-123","issued_at":"2026-08-20T10:00:00+00:00"},
        "head_sha":"a"*40,"head_sha_after":"a"*40,"base_sha":"b"*40,"base_sha_after":"b"*40,
        "merge_preview_sha":"c"*40,"merge_preview_sha_after":"c"*40,"verdict":"rejected",
        "rejection_id":"audit-rejection:targeted-001","neutral_packet":{"implementation_conclusions_included":False,"implementation_narrative_included":False},
        "prior_internal_approval":{"head_sha":"a"*40},"evidence":[],"limitations":[],"issued_at":"2026-08-20T10:01:00+00:00",
        "findings":[{"id":"F1","audit_escape":True,"remediation_mode":"targeted-remediation","sibling_cases":[],"reusable_control_requirement":None}],
        "recommendations":[{"id":"R1","actionable":True,"remediation_mode":"targeted-remediation"}],
    }


def test_targeted_finding_does_not_require_systemic_sibling_work():
    errors=mod.report_semantic_errors(_base_report(), require_signature=False)
    assert not [e for e in errors if "sibling" in e or "reusable_control" in e], errors


def test_systemic_finding_requires_siblings_and_reusable_control():
    report=_base_report(); report["findings"][0]["remediation_mode"]="systemic-remediation"
    errors=mod.report_semantic_errors(report, require_signature=False)
    assert any("reusable_control_requirement" in e for e in errors)


def test_deterministic_failed_gate_metadata_is_accepted():
    report=_base_report()
    report["findings"][0]["failed_gate"]={
        "name":"format-check","command":"npm run format:check","deterministic":True,
        "subject_sha":"a"*40,"observed_exit_code":1,"evidence_sha256":"d"*64,
    }
    errors=mod.report_semantic_errors(report, require_signature=False)
    assert not [e for e in errors if "failed_gate" in e], errors


def test_continuation_must_reuse_previous_rejection_id():
    report=_base_report()
    report["rejection_lineage"]={"mode":"continuation","previous_rejection_id":"audit-rejection:prior-001","continued_finding_ids":["F1"]}
    errors=mod.report_semantic_errors(report, require_signature=False)
    assert any("continued rejection must reuse" in e for e in errors)
