"""Regressions for the trusted-auditor registry.

The registry that accepts an external audit report is kept outside the candidate
repository, so nothing in the repository would notice if the procedure that maintains
it disappeared from the documentation. These tests keep the procedure declared, and
keep the entry builder honest about the fingerprint it publishes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
SECURITY = ROOT / "docs" / "SECURITY.md"
BUILDER = ROOT / "auditar-issue" / "scripts" / "build_trusted_auditor_entry.py"
SCHEMA = ROOT / "auditar-issue" / "schemas" / "trusted-auditors.schema.json"

REQUIRED_ELEMENTS = {
    "secao do registro": "## Registro de auditores confiáveis",
    "custodiante": "**custodiante**",
    "produtor do candidato": "**produtor do candidato**",
    "detentor da chave privada": "**detentor da chave privada de auditoria**",
    "registro fora do alcance do candidato": "nunca no repositório do candidato",
    "gerador de chaves": "generate_auditor_keypair.py",
    "construtor da entrada": "build_trusted_auditor_entry.py",
    "rotacao e revogacao": "### Rotação e revogação",
    "operador unico": "### Operador único",
    "limitacao declarada": "regra de contrato, não garantia estrutural",
    "distribuicao futura do CODEOWNERS": "distribuir o `CODEOWNERS`",
    "hash derivado": "deriva `public_key_sha256` dos bytes de `public_key_pem`",
}


def missing_elements(text: str) -> list[str]:
    return [label for label, marker in REQUIRED_ELEMENTS.items() if marker not in text]


def run_builder(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(BUILDER), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def write_public_key(path: Path, *, kind: str = "ed25519") -> bytes:
    if kind == "ed25519":
        key = Ed25519PrivateKey.generate()
        public = key.public_key()
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = key.public_key()
    pem = public.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    path.write_bytes(pem)
    return pem


def valid_schema() -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


def test_security_document_declares_the_registry_procedure() -> None:
    assert missing_elements(SECURITY.read_text(encoding="utf-8")) == []


def test_every_required_element_is_detected_when_removed() -> None:
    text = SECURITY.read_text(encoding="utf-8")
    for label, marker in REQUIRED_ELEMENTS.items():
        assert label in missing_elements(text.replace(marker, "")), label


def test_builder_produces_a_schema_valid_registry(tmp_path: Path) -> None:
    public_key = tmp_path / "auditor-public.pem"
    write_public_key(public_key)
    out = tmp_path / "trusted-auditors.json"
    result = run_builder(
        "--public-key", str(public_key),
        "--key-id", "auditor-01",
        "--name", "Auditor Independente",
        "--repository", "owner/repo",
        "--registry",
        "--out", str(out),
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(out.read_text(encoding="utf-8"))
    valid_schema().validate(document)
    entry = document["auditors"][0]
    assert entry["enabled"] is True
    assert entry["repositories"] == ["owner/repo"]


def test_builder_derives_the_fingerprint_from_the_stored_key(tmp_path: Path) -> None:
    public_key = tmp_path / "auditor-public.pem"
    raw = write_public_key(public_key)
    result = run_builder(
        "--public-key", str(public_key),
        "--key-id", "auditor-01",
        "--name", "Auditor Independente",
        "--repository", "owner/repo",
    )
    assert result.returncode == 0, result.stderr
    entry = json.loads(result.stdout)
    expected = hashlib.sha256(entry["public_key_pem"].encode("utf-8")).hexdigest()
    assert entry["public_key_sha256"] == expected
    # o texto publicado preserva a chave: o hash descreve a mesma chave, não uma normalizada
    assert "BEGIN PUBLIC KEY" in entry["public_key_pem"]
    assert len(entry["public_key_pem"].encode("utf-8")) <= len(raw) + 1


def test_builder_refuses_a_private_key(tmp_path: Path) -> None:
    private_key = tmp_path / "auditor-private.pem"
    key = Ed25519PrivateKey.generate()
    private_key.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    result = run_builder(
        "--public-key", str(private_key),
        "--key-id", "auditor-01",
        "--name", "Auditor Independente",
        "--repository", "owner/repo",
    )
    assert result.returncode == 2
    assert "chave privada" in result.stderr


def test_builder_refuses_a_missing_file(tmp_path: Path) -> None:
    result = run_builder(
        "--public-key", str(tmp_path / "ausente.pem"),
        "--key-id", "auditor-01",
        "--name", "Auditor Independente",
        "--repository", "owner/repo",
    )
    assert result.returncode == 2
    assert "ausente" in result.stderr


def test_builder_refuses_a_key_that_is_not_ed25519(tmp_path: Path) -> None:
    public_key = tmp_path / "auditor-public.pem"
    write_public_key(public_key, kind="rsa")
    result = run_builder(
        "--public-key", str(public_key),
        "--key-id", "auditor-01",
        "--name", "Auditor Independente",
        "--repository", "owner/repo",
    )
    assert result.returncode == 2
    assert "Ed25519" in result.stderr


@pytest.mark.parametrize(
    ("key_id", "name"),
    [("abc", "Auditor Independente"), ("auditor-01", "Xi")],
)
def test_builder_refuses_an_entry_the_schema_rejects(tmp_path: Path, key_id: str, name: str) -> None:
    public_key = tmp_path / "auditor-public.pem"
    write_public_key(public_key)
    result = run_builder(
        "--public-key", str(public_key),
        "--key-id", key_id,
        "--name", name,
        "--repository", "owner/repo",
    )
    assert result.returncode == 2
    assert "saída inválida" in result.stderr


def test_registry_contract_documents_the_builder() -> None:
    contract = (ROOT / "auditar-issue" / "references" / "external-audit-contract.md").read_text(encoding="utf-8")
    assert "build_trusted_auditor_entry.py" in contract
    assert "docs/SECURITY.md" in contract
