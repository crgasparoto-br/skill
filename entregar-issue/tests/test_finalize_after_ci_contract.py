import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def payload(material_change=True):
    return {'schema_version':2,'contract_version':'2026-08-20.3','return_control_to':'entregar-issue','next_phase':'finalize-after-ci','ci_owner_closed':True,'reason':'post-ci-refreeze' if material_change else 'handoff-only','previous_frozen_sha':'abcdef1','material_head_sha':'abcdef2','ci_state':'green','recovery_hint':{'checkpoint_ledger_path':'.audit/entregar-issue/stage-checkpoints.json','material_change':material_change,'changed_files':['app.py'] if material_change else [],'code_growth_recheck':material_change,'resume_from':'hygiene' if material_change else 'handoff'}}

def test_finalize_checkpoint_accepts_closed_ci_owner(tmp_path):
    p=tmp_path/'e.json';p.write_text(json.dumps(payload()),encoding='utf-8')
    r=subprocess.run([sys.executable,str(ROOT/'scripts/finalize_after_ci_checkpoint.py'),'--input',str(p)],check=False, capture_output=True,text=True)
    assert r.returncode==0,r.stdout+r.stderr
    assert 'finalize-after-ci checkpoint accepted' in r.stdout

def test_finalize_checkpoint_rejects_open_ci_owner(tmp_path):
    v=payload();v['ci_owner_closed']=False
    p=tmp_path/'e.json';p.write_text(json.dumps(v),encoding='utf-8')
    r=subprocess.run([sys.executable,str(ROOT/'scripts/finalize_after_ci_checkpoint.py'),'--input',str(p)],check=False, capture_output=True,text=True)
    assert r.returncode!=0

def test_skill_forbids_ping_pong_controller():
    text=(ROOT/'SKILL.md').read_text(encoding='utf-8')
    ref=(ROOT/'references/finalize-after-ci.md').read_text(encoding='utf-8')
    assert 'next_phase=finalize-after-ci' in text
    assert 'nao pode invocar `entregar-issue` de volta' in text.lower()
    assert 'ping-pong' in ref
