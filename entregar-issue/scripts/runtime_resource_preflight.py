#!/usr/bin/env python3
from pathlib import Path
import re, sys, json

root=Path(sys.argv[1] if len(sys.argv)>1 else Path(__file__).resolve().parents[1])
refs=[root/'SKILL.md', *sorted((root/'references').glob('*.md'))]
pat=re.compile(r'(?<![A-Za-z0-9_.-])(scripts/([A-Za-z0-9_.-]+\\.py))')
missing=[]; referenced=set()
for p in refs:
    if not p.exists():
        continue
    text=p.read_text(encoding='utf-8')
    for match in pat.finditer(text):
        prefix=text[max(0,match.start()-96):match.start()]
        external=re.search(r'<([a-z0-9-]+)>/$', prefix)
        if external and external.group(1) not in {'skill', root.name}:
            continue
        name=match.group(2)
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
