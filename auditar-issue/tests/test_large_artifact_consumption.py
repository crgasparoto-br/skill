from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from audit_artifact_io import artifact_metadata, pack_json_artifact  # noqa: E402 - sys.path ajustado acima antes do import local
from test_certified_delivery_preflight import BASE, HEAD, MERGE, run, write_packet  # noqa: E402 - sys.path ajustado acima antes do import local


def test_auditor_preflight_consumes_sharded_delivery_artifacts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        matrix, risk, inherited, closure = write_packet(base)
        spec = base / "specification-snapshot.json"

        pack_json_artifact(closure, force=True, shard_bytes=128)
        pack_json_artifact(matrix, force=True, shard_bytes=128)

        artifacts = {
            "specification_snapshot": spec,
            "requirement_closure": closure,
            "requirement_attack_matrix": matrix,
            "risk_saturation": risk,
            "inherited_controls": inherited,
        }
        cert = base / "handoff-ready.json"
        cert.write_text(json.dumps({
            "schema_version": 1,
            "status": "ready",
            "identity": {"head_sha": HEAD, "base_sha": BASE, "merge_preview_sha": MERGE},
            "contract_version": "2026-08-20.3",
            "producer": {"skill": "entregar-issue", "skill_sha256": "a" * 64},
            "validators": {},
            "artifact_transport": {"version": 1, "supported_formats": ["plain-json", "base64-shards-v1"]},
            "artifacts": {key: artifact_metadata(path) for key, path in artifacts.items()},
            "previous_independent_rejection": False,
        }), encoding="utf-8")

        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", HEAD, "--base-sha", BASE,
            "--merge-preview-sha", MERGE, "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 0, proc.stdout

        part = base / artifact_metadata(closure)["artifact_transport"]["parts"][0]["path"]
        part.write_bytes(part.read_bytes() + b"A")
        proc = run(
            "--certificate", str(cert), "--artifacts-dir", str(base),
            "--attack-matrix", str(matrix), "--risk-saturation", str(risk),
            "--inherited-controls", str(inherited), "--head-sha", HEAD, "--base-sha", BASE,
            "--merge-preview-sha", MERGE, "--contract-version", "2026-08-20.3",
        )
        assert proc.returncode == 2
        assert "transport validation failed" in proc.stdout
