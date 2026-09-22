from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_artifact_io import artifact_metadata, artifact_relative_paths, load_json_artifact, pack_json_artifact


def test_round_trip_and_metadata_are_exact() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "large.json"
        value = {"items": [{"id": i, "text": "x" * 200} for i in range(200)]}
        raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        path.write_bytes(raw)
        meta = pack_json_artifact(path, force=True, shard_bytes=256)
        assert meta["logical_sha256"] == hashlib.sha256(raw).hexdigest()
        assert meta["artifact_transport"]["format"] == "base64-shards-v1"
        assert load_json_artifact(path) == value
        assert len(artifact_relative_paths(path)) > 2


def test_tampered_part_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "large.json"
        path.write_text(json.dumps({"payload": "z" * 5000}), encoding="utf-8")
        meta = pack_json_artifact(path, force=True, shard_bytes=128)
        part = Path(tmp) / meta["artifact_transport"]["parts"][0]["path"]
        part.write_bytes(part.read_bytes() + b"A")
        try:
            artifact_metadata(path)
        except ValueError as exc:
            assert "mismatch" in str(exc)
        else:
            raise AssertionError("tampered shard must fail closed")


def test_part_path_traversal_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "large.json"
        path.write_text(json.dumps({"payload": "z" * 5000}), encoding="utf-8")
        pack_json_artifact(path, force=True, shard_bytes=128)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["parts"][0]["path"] = "../escape.b64"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        try:
            load_json_artifact(path)
        except ValueError as exc:
            assert "invalid artifact part path" in str(exc)
        else:
            raise AssertionError("path traversal must fail closed")
