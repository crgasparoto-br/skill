#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--report',required=True); p.add_argument('--head-sha',required=True); a=p.parse_args()
    try: v=json.loads(Path(a.report).read_text(encoding='utf-8'))
    except Exception as exc: print(f'BLOCK: invalid code-growth artifact: {exc}'); return 2
    e=[]
    if not isinstance(v,dict): e.append('code-growth artifact root must be object')
    else:
        if v.get('control_id')!='CODE-GROWTH-001': e.append('unexpected code-growth control id')
        if v.get('status')!='passed': e.append('certified code-growth control did not pass')
        if v.get('subject_sha')!=a.head_sha: e.append('code-growth evidence is stale for material head')
        if v.get('blocking_files'): e.append('code-growth evidence contains blocking files')
        if not isinstance(v.get('policy'),dict): e.append('code-growth evidence lacks policy')
    if e:
        for x in e: print(f'BLOCK: {x}')
        return 2
    print('READY: certified CODE-GROWTH-001 evidence is structurally valid; independent refutation still required')
    return 0
if __name__=='__main__': raise SystemExit(main())
