import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def envelope():
 return {'schema_version':2,'contract_version':'2026-08-20.3','return_control_to':'entregar-issue','next_phase':'finalize-after-ci','ci_owner_closed':True,'reason':'post-ci-refreeze','previous_frozen_sha':'abcdef1','material_head_sha':'abcdef2','ci_state':'green','recovery_hint':{'checkpoint_ledger_path':'.audit/entregar-issue/stage-checkpoints.json','material_change':True,'changed_files':['app.py'],'code_growth_recheck':True,'resume_from':'hygiene'}}

def test_recovery_envelope_requires_finalize_phase(tmp_path):
 p=tmp_path/'e.json';p.write_text(json.dumps(envelope()))
 r=subprocess.run([sys.executable,str(ROOT/'scripts/validate_delivery_recovery_envelope.py'),'--input',str(p)],capture_output=True,text=True)
 assert r.returncode==0,r.stdout+r.stderr
 assert 'finalize-after-ci' in r.stdout

def test_recovery_envelope_rejects_recursive_open_owner(tmp_path):
 v=envelope();v['ci_owner_closed']=False
 p=tmp_path/'e.json';p.write_text(json.dumps(v))
 r=subprocess.run([sys.executable,str(ROOT/'scripts/validate_delivery_recovery_envelope.py'),'--input',str(p)],capture_output=True,text=True)
 assert r.returncode!=0
