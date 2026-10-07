import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_ci_remediation_mode_returns_to_existing_controller():
    contract=json.loads((ROOT/'contracts/ci-ownership.json').read_text())
    mode=contract['modes']['ci-remediation-loop']
    assert contract['schema_version']==2
    assert mode['owner']=='corrigir-ci'
    assert mode['waits_until_terminal'] is True
    assert mode['pending_ends_remote_wait'] is False
    assert mode['post_material_green_transition']=='return-to-caller:finalize-after-ci'
    assert mode['terminal_delivery_owner']=='entregar-issue'
    assert mode['may_write_delivery_audit_artifacts'] is False
