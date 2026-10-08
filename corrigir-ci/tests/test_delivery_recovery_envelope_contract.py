import json
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def envelope():
 return {'schema_version':2,'contract_version':'2026-08-20.3','return_control_to':'entregar-issue','next_phase':'finalize-after-ci','ci_owner_closed':True,'reason':'post-ci-refreeze','previous_frozen_sha':'abcdef1','material_head_sha':'abcdef2','ci_state':'green','recovery_hint':{'checkpoint_ledger_path':'.audit/entregar-issue/stage-checkpoints.json','material_change':True,'changed_files':['app.py'],'code_growth_recheck':True,'resume_from':'hygiene'}}

def test_recovery_envelope_requires_finalize_phase(tmp_path):
 p=tmp_path/'e.json';p.write_text(json.dumps(envelope()))
 r=subprocess.run([sys.executable,str(ROOT/'scripts/validate_delivery_recovery_envelope.py'),'--input',str(p)],check=False, capture_output=True,text=True)
 assert r.returncode==0,r.stdout+r.stderr
 assert 'finalize-after-ci' in r.stdout

def test_recovery_envelope_rejects_recursive_open_owner(tmp_path):
 v=envelope();v['ci_owner_closed']=False
 p=tmp_path/'e.json';p.write_text(json.dumps(v))
 r=subprocess.run([sys.executable,str(ROOT/'scripts/validate_delivery_recovery_envelope.py'),'--input',str(p)],check=False, capture_output=True,text=True)
 assert r.returncode!=0

def _script_accepts(tmp_path, value):
 p=tmp_path/'e.json';p.write_text(json.dumps(value))
 return subprocess.run([sys.executable,str(ROOT/'scripts/validate_delivery_recovery_envelope.py'),'--input',str(p)],check=False, capture_output=True,text=True).returncode==0

def test_validator_and_schema_agree(tmp_path):
 from jsonschema import Draft202012Validator
 schema=Draft202012Validator(json.loads((ROOT/'schemas/delivery-recovery-envelope.schema.json').read_text(encoding='utf-8')))
 variants=[envelope()]
 for key,value in (('reason','other'),('material_head_sha','abc'),('extra',1),('ci_state','red'),('previous_frozen_sha',None)):
  v=envelope();v[key]=value;variants.append(v)
 for key,value in (('material_change','yes'),('changed_files',['a','a']),('resume_from',3),('extra',1)):
  v=envelope();v['recovery_hint'][key]=value;variants.append(v)
 v=envelope();del v['recovery_hint']['resume_from'];variants.append(v)
 for v in variants:
  assert _script_accepts(tmp_path,v)==schema.is_valid(v),v
