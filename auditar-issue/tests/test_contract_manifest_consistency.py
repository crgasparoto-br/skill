from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_contract_manifest_references_only_packaged_contracts_with_matching_hashes():
    contracts = ROOT / "contracts"
    payload = json.loads((contracts / "manifest.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["contract_version"] == "2026-08-20.3"
    assert payload["files"], "manifest must index at least one packaged contract"
    for name, expected in payload["files"].items():
        path = contracts / name
        assert path.is_file(), f"manifest references missing packaged contract: {name}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == expected, f"manifest hash mismatch for {name}"
