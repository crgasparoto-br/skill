#!/usr/bin/env python3
from pathlib import Path
import re, sys, json

root=Path(sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parents[1])
refs=[root/'SKILL.md', *sorted((root/'references').glob('*.md'))]
pat=re.compile(r'scripts/([A-Za-z0-9_.-]+\.py)')
missing=[]; referenced=set()
for p in refs:
    if not p.exists():
        continue
    for name in pat.findall(p.read_text(encoding='utf-8')):
        referenced.add(name)
        if not (root/'scripts'/name).exists():
            missing.append(name)
out={
    'status':'PASS' if not missing else 'FAIL',
    'referenced_scripts':sorted(referenced),
    'missing_scripts':sorted(set(missing)),
}
print(json.dumps(out,ensure_ascii=False,indent=2))
sys.exit(0 if not missing else 1)
