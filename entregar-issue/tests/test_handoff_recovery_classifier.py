from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]; SCRIPT=ROOT/"scripts/classify_handoff_recovery.py"; CERT=".audit/entregar-issue/handoff-ready.json"
def cert(p,m): p.write_text(json.dumps({"identity":{"material_head_sha":m,"head_sha":m},"certificate_commit_policy":{"mode":"result-only-child","allowed_paths":[CERT]}})); return p
def run(c,h,p,paths,b="current-target",auditor_scope=None,requires_refreeze=False):
    cmd=[sys.executable,str(SCRIPT),"--certificate",str(c),"--current-head-sha",h,"--current-parent-sha",p,"--target-binding-status",b]
    if auditor_scope: cmd += ["--auditor-recovery-scope", auditor_scope]
    if requires_refreeze: cmd += ["--auditor-requires-refreeze"]
    for x in paths: cmd += ["--current-changed-path",x]
    q=subprocess.run(cmd,check=False, text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT); assert q.returncode==0,q.stdout; return json.loads(q.stdout)
def test_terminal():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40; c=cert(Path(d)/"c.json",m); assert run(c,"b"*40,m,[CERT])["recovery_scope"]=="terminal-handoff-valid"
def test_handoff_only():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40; c=cert(Path(d)/"c.json",m); assert run(c,m,"c"*40,[])["recovery_scope"]=="handoff-only"
def test_parent_drift_refreeze():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40; c=cert(Path(d)/"c.json",m); assert run(c,"d"*40,"c"*40,[CERT])["recovery_scope"]=="post-write-refreeze"
def test_material_path_refreeze():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40; c=cert(Path(d)/"c.json",m); assert run(c,"b"*40,m,[CERT,"src/app.ts"])["recovery_scope"]=="post-write-refreeze"
def test_foreign_target():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40; c=cert(Path(d)/"c.json",m); assert run(c,"b"*40,m,[CERT],"foreign-target")["recovery_scope"]=="fresh-handoff-required"
        assert run(c,"b"*40,m,[CERT],"inherited-base-artifact")["recovery_scope"]=="fresh-handoff-required"


def test_auditor_refreeze_floor_never_downgrades_to_handoff_only():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40; c=cert(Path(d)/"c.json",m)
        result=run(c,m,"c"*40,[],auditor_scope="post-write-refreeze")
        assert result["recovery_scope"]=="post-write-refreeze"
        assert result["reason"]=="auditor-recovery-floor:post-write-refreeze"

def test_auditor_requires_refreeze_flag_never_downgrades_to_handoff_only():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40; c=cert(Path(d)/"c.json",m)
        result=run(c,m,"c"*40,[],requires_refreeze=True)
        assert result["recovery_scope"]=="post-write-refreeze"
        assert result["auditor_requires_refreeze"] is True

def test_fresh_remote_material_drift_overrides_auditor_handoff_only():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40; c=cert(Path(d)/"c.json",m)
        result=run(c,"d"*40,"c"*40,[CERT],auditor_scope="handoff-only")
        assert result["recovery_scope"]=="post-write-refreeze"
        assert result["reason"]=="current-parent-differs-from-certified-material"

def test_foreign_target_stays_fresh_even_with_refreeze_floor():
    with tempfile.TemporaryDirectory() as d:
        m="a"*40; c=cert(Path(d)/"c.json",m)
        result=run(c,"b"*40,m,[CERT],b="foreign-target",auditor_scope="post-write-refreeze",requires_refreeze=True)
        assert result["recovery_scope"]=="fresh-handoff-required"
