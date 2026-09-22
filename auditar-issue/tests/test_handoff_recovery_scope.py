from __future__ import annotations
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCRIPT=ROOT/"scripts/validate_handoff_certificate.py"; CERT=".audit/entregar-issue/handoff-ready.json"
def packet(root,m):
    arts={}
    for k,n in {"specification_snapshot":"specification-snapshot.json","requirement_closure":"requirement-closure.json","requirement_attack_matrix":"requirement-attack-matrix.json","risk_saturation":"risk-saturation.json","inherited_controls":"inherited-controls.json"}.items():
        p=root/n;p.write_text("{}");arts[k]={"name":n,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()}
    c=root/"handoff.json";c.write_text(json.dumps({"schema_version":2,"status":"ready","identity":{"head_sha":m,"material_head_sha":m,"base_sha":"b"*40},"certificate_commit_policy":{"mode":"result-only-child","allowed_paths":[CERT]},"contract_version":"2026-08-20.3","producer":{"skill":"entregar-issue","skill_sha256":"f"*64},"artifacts":arts}));return c
def run(c,h,p,paths):
    cmd=[sys.executable,str(SCRIPT),"--certificate",str(c),"--artifacts-dir",str(c.parent),"--head-sha",h,"--base-sha","b"*40,"--candidate-parent-sha",p,"--contract-version","2026-08-20.3"]
    for x in paths: cmd += ["--candidate-changed-path",x]
    return subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
def test_parent_drift():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40;q=run(packet(Path(d),m),"c"*40,"d"*40,[CERT]);assert q.returncode==2;assert "RECOVERY: post-write-refreeze" in q.stdout
def test_material_path():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40;q=run(packet(Path(d),m),"c"*40,m,[CERT,"src/app.ts"]);assert q.returncode==2;assert "RECOVERY: post-write-refreeze" in q.stdout
