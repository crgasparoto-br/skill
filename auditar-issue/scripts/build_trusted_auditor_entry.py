#!/usr/bin/env python3
"""Build a trusted-auditor registry entry from a public key file.

The registry that accepts an external audit report is kept outside the candidate
repository, so a malformed entry is caught by no repository test: the signature check
fails only later, while an approval is being consumed, and the failure looks like an
invalid report instead of a broken registry.

Deriving `public_key_sha256` from the stored `public_key_pem` removes that class of
error, because the fingerprint can no longer disagree with the key it describes. The
value is computed here and is not accepted as input.

Usage:

    python build_trusted_auditor_entry.py \
      --public-key <auditor-public.pem> \
      --key-id <key-id> \
      --name <auditor name> \
      --repository <owner/repo> [--repository <other/pattern>] \
      [--registry] [--out <trusted-auditors.json>]

`--registry` emits the whole registry document instead of a single entry. With one
auditor the registry needs no manual merge, which is where a hand-edited hash appears.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA_RELATIVE = Path("schemas") / "trusted-auditors.schema.json"
PRIVATE_MARKER = "PRIVATE KEY"


def normalize_pem(text: str) -> str:
    """Return the PEM text in the exact form the fingerprint covers."""
    lines = [line.strip() for line in text.strip().splitlines()]
    return "\n".join(lines) + "\n"


def load_registry_schema() -> dict:
    schema_path = Path(__file__).resolve().parents[1] / SCHEMA_RELATIVE
    return json.loads(schema_path.read_text(encoding="utf-8"))


def build_entry(public_key_path: Path, key_id: str, name: str, repositories: list[str]) -> tuple[dict | None, str | None]:
    if not public_key_path.is_file():
        return None, f"arquivo de chave pública ausente: {public_key_path}"
    try:
        raw = public_key_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"arquivo de chave pública ilegível: {exc}"
    if PRIVATE_MARKER in raw:
        return None, "o arquivo contém chave privada; o registro aceita apenas chave pública"
    pem = normalize_pem(raw)
    try:
        key = serialization.load_pem_public_key(pem.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - a malformed key must produce a clear refusal
        return None, f"chave pública inválida: {exc}"
    if not isinstance(key, Ed25519PublicKey):
        return None, "a chave pública precisa ser Ed25519"
    entry = {
        "key_id": key_id,
        "name": name,
        "enabled": True,
        "repositories": repositories,
        "public_key_pem": pem,
        "public_key_sha256": hashlib.sha256(pem.encode("utf-8")).hexdigest(),
    }
    return entry, None


def validate(document: dict) -> list[str]:
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - dependency declared by the skill
        return ["jsonschema ausente: não foi possível validar a saída contra o esquema"]
    schema = load_registry_schema()
    validator = jsonschema.Draft202012Validator(schema)
    return [f"saída inválida: {error.message}" for error in sorted(validator.iter_errors(document), key=lambda e: e.path)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--public-key", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--repository", action="append", default=[], required=True)
    parser.add_argument("--registry", action="store_true", help="emitir o documento de registro completo")
    parser.add_argument("--out", help="arquivo de saída; sem ele, escreve na saída padrão")
    args = parser.parse_args()

    entry, error = build_entry(Path(args.public_key).expanduser(), args.key_id, args.name, list(args.repository))
    if error or entry is None:
        print(f"FAIL: {error}", file=sys.stderr)
        return 2
    document = {"schema_version": 1, "auditors": [entry]} if args.registry else entry
    errors = validate(document if args.registry else {"schema_version": 1, "auditors": [document]})
    if errors:
        for message in errors:
            print(f"FAIL: {message}", file=sys.stderr)
        return 2
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).expanduser().write_text(payload, encoding="utf-8")
        print(f"entrada gravada em {args.out}")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())