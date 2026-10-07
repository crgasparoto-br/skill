from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def test_delivery_contract_is_resume_aware():
 s=(ROOT/'references/delivery-contract.md').read_text()
 assert '2026-08-20.3' in s
 assert 'changed_files=[]' in s
