import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_remote_gate_forbids_polling_for_future_ci():
    ownership = json.loads((ROOT / "contracts" / "ci-ownership.json").read_text())
    mode = ownership["modes"]["delivery-snapshot"]
    assert mode["owner"] == "entregar-issue"
    assert mode["waits_until_terminal"] is False
    assert mode["pending_ends_remote_wait"] is True
    assert mode["may_rerun_or_dispatch"] is False


def test_multi_file_publication_is_atomic_by_default():
    efficiency = (ROOT / "references" / "controller-execution-efficiency.md").read_text(encoding="utf-8")
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    assert "preparar todos os blobs e uma unica tree/commit" in efficiency
    assert "Publicar `.audit/entregar-issue` em um unico `result-only-child`" in terminal


def test_audit_remediation_reuses_structured_findings():
    efficiency = (ROOT / "references" / "controller-execution-efficiency.md").read_text(encoding="utf-8")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "nao repetir discovery, readiness ou decomposicao integral da issue" in efficiency
    assert "usar os findings como work items prontos" in skill


def test_preflight_selects_execution_capability_once():
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "`local-git`, `connector-only` ou `artifact-bundle`" in skill
    assert "nao repetir clone" in skill


def test_head_stability_guard_does_not_force_branch_backwards():
    efficiency = (ROOT / "references" / "controller-execution-efficiency.md").read_text(encoding="utf-8")
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    assert "nao force-push para restaurar SHA **material** antigo" in efficiency
    assert "result-only-child` stale" in efficiency
    assert "reconsultar o remoto" in terminal


def test_completed_remote_failure_delegates_to_ci_remediation_without_new_prompt():
    remote = (ROOT / "references" / "remote-gate.md").read_text(encoding="utf-8")
    efficiency = (ROOT / "references" / "controller-execution-efficiency.md").read_text(encoding="utf-8")
    assert "completed/failure" in remote
    assert "corrigir-ci" in remote
    assert "sem pedir novo prompt" in remote
    assert "corrigir-ci" in efficiency
    assert "post-write-refreeze" in efficiency


def test_pending_ci_transfers_owner_in_same_top_level_invocation():
    ownership = json.loads((ROOT / "contracts" / "ci-ownership.json").read_text())
    delivery = ownership["modes"]["delivery-snapshot"]
    remediation = ownership["modes"]["ci-remediation-loop"]
    terminal = (ROOT / "references" / "terminal-handoff.md").read_text(encoding="utf-8")
    assert delivery["pending_ends_remote_wait"] is True
    assert remediation["waits_until_terminal"] is True
    assert "transferir ownership para `corrigir-ci`" in terminal
    assert "mesma invocacao" in terminal
