import json
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[1]

def test_ci_modes_are_mutually_exclusive_and_return_to_controller():
    contract=json.loads((ROOT/'contracts/ci-ownership.json').read_text())
    delivery=contract['modes']['delivery-snapshot']; remediation=contract['modes']['ci-remediation-loop']
    assert contract['schema_version']==2
    assert delivery['owner']=='entregar-issue'
    assert remediation['owner']=='corrigir-ci'
    assert delivery['waits_until_terminal'] is False
    assert remediation['waits_until_terminal'] is True
    assert remediation['post_material_green_transition']=='return-to-caller:finalize-after-ci'
    assert remediation['terminal_delivery_owner']=='entregar-issue'
    assert remediation['may_write_delivery_audit_artifacts'] is False

def test_corrigir_ci_consumes_exact_canonical_contract():
    sibling=ROOT.parent/'corrigir-ci'/'contracts/ci-ownership.json'
    if not sibling.exists(): pytest.skip('cross-skill integration check requires sibling corrigir-ci')
    assert (ROOT/'contracts/ci-ownership.json').read_bytes()==sibling.read_bytes()
