#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

VERSION="2026-08-20.3"
# Runtime mirror of schemas/delivery-recovery-envelope.schema.json; tests/test_delivery_recovery_envelope_contract.py checks parity.
REASONS={'post-ci-refreeze','handoff-only'}
HINT_KEYS={'checkpoint_ledger_path','material_change','changed_files','code_growth_recheck','resume_from'}
def main()->int:
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);a=p.parse_args()
 try:v=json.loads(Path(a.input).read_text(encoding='utf-8'))
 except Exception as exc: print(f'BLOCK: invalid recovery envelope: {exc}');return 2
 e=[]
 req=['schema_version','contract_version','return_control_to','next_phase','ci_owner_closed','reason','previous_frozen_sha','material_head_sha','ci_state','recovery_hint']
 for k in req:
  if k not in v:e.append(f'missing {k}')
 for k in sorted(set(v)-set(req)):e.append(f'unexpected field {k}')
 if v.get('reason') not in REASONS:e.append('reason is invalid')
 for k in ('previous_frozen_sha','material_head_sha'):
  if not isinstance(v.get(k),str) or len(v[k])<7:e.append(f'{k} must be a SHA string')
 if v.get('schema_version')!=2:e.append('schema_version must be 2')
 if v.get('contract_version')!=VERSION:e.append('contract_version mismatch')
 if v.get('return_control_to')!='entregar-issue':e.append('return_control_to must be entregar-issue')
 if v.get('next_phase')!='finalize-after-ci':e.append('next_phase must be finalize-after-ci')
 if v.get('ci_owner_closed') is not True:e.append('ci_owner_closed must be true')
 if v.get('ci_state')!='green':e.append('ci_state must be green')
 h=v.get('recovery_hint')
 if not isinstance(h,dict):e.append('recovery_hint must be object')
 else:
  for k in sorted(HINT_KEYS-set(h)):e.append(f'recovery_hint missing {k}')
  for k in sorted(set(h)-HINT_KEYS):e.append(f'recovery_hint unexpected field {k}')
  if h.get('checkpoint_ledger_path')!='.audit/entregar-issue/stage-checkpoints.json':e.append('unexpected checkpoint ledger path')
  files=h.get('changed_files')
  if not isinstance(files,list) or not all(isinstance(x,str) for x in files) or len(set(files))!=len(files):e.append('changed_files must be an array of unique strings')
  for k in ('material_change','code_growth_recheck'):
   if not isinstance(h.get(k),bool):e.append(f'{k} must be boolean')
  if h.get('resume_from') is not None and not isinstance(h.get('resume_from'),str):e.append('resume_from must be string or null')
  if h.get('material_change') is True and h.get('code_growth_recheck') is True and h.get('resume_from')!='hygiene':e.append('code growth recheck must resume from hygiene')
  if h.get('material_change') is False and h.get('resume_from') not in ('freeze','handoff',None):e.append('unchanged material must resume from freeze/handoff')
 if e:
  for x in e:print(f'BLOCK: {x}')
  return 2
 print('READY: delivery recovery envelope returns to finalize-after-ci')
 return 0
if __name__=='__main__':raise SystemExit(main())
