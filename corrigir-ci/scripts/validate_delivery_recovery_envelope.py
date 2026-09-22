#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path
VERSION="2026-08-20.3"
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);a=p.parse_args()
 try:v=json.loads(Path(a.input).read_text(encoding='utf-8'))
 except Exception as exc: print(f'BLOCK: invalid recovery envelope: {exc}');return 2
 e=[]
 req=['schema_version','contract_version','return_control_to','next_phase','ci_owner_closed','reason','previous_frozen_sha','material_head_sha','ci_state','recovery_hint']
 for k in req:
  if k not in v:e.append(f'missing {k}')
 if v.get('schema_version')!=2:e.append('schema_version must be 2')
 if v.get('contract_version')!=VERSION:e.append('contract_version mismatch')
 if v.get('return_control_to')!='entregar-issue':e.append('return_control_to must be entregar-issue')
 if v.get('next_phase')!='finalize-after-ci':e.append('next_phase must be finalize-after-ci')
 if v.get('ci_owner_closed') is not True:e.append('ci_owner_closed must be true')
 if v.get('ci_state')!='green':e.append('ci_state must be green')
 h=v.get('recovery_hint')
 if not isinstance(h,dict):e.append('recovery_hint must be object')
 else:
  if h.get('checkpoint_ledger_path')!='.audit/entregar-issue/stage-checkpoints.json':e.append('unexpected checkpoint ledger path')
  if not isinstance(h.get('changed_files'),list):e.append('changed_files must be array')
  if h.get('material_change') is True and h.get('code_growth_recheck') is True and h.get('resume_from')!='hygiene':e.append('code growth recheck must resume from hygiene')
  if h.get('material_change') is False and h.get('resume_from') not in ('freeze','handoff',None):e.append('unchanged material must resume from freeze/handoff')
 if e:
  for x in e:print(f'BLOCK: {x}')
  return 2
 print('READY: delivery recovery envelope returns to finalize-after-ci')
 return 0
if __name__=='__main__':raise SystemExit(main())
