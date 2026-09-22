from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_handoff_readiness_cross_checks_learning_and_escape_ledgers() -> None:
    readiness = (ROOT / "scripts" / "validate_handoff_readiness.py").read_text(encoding="utf-8")
    assert "--learning-closure" in readiness
    assert "validate_independent_rejection_closure.py" in readiness
    assert "previous independent rejection requires learning-closure.json" in readiness


def test_certificate_builder_requires_previous_snapshots_and_forwards_learning() -> None:
    builder = (ROOT / "scripts" / "build_handoff_certificate.py").read_text(encoding="utf-8")
    assert "--previous-inherited-controls" in builder
    assert "--previous-audit-escape-closure" in builder
    assert '"--learning-closure", str(files["learning_closure"])' in builder
    assert "validate_independent_rejection_closure.py" in builder


def test_terminal_guard_revalidates_learning_against_published_escape_ledger() -> None:
    terminal = (ROOT / "scripts" / "validate_terminal_handoff.py").read_text(encoding="utf-8")
    assert '"--learning-closure", str(artifact_path("learning_closure"))' in terminal
    assert "--previous-audit-escape-closure" in terminal
    assert '"--evidence-profile", evidence_profile' in terminal
    assert "systemic_reaudit and not args.previous_inherited_controls" in terminal
