"""Regressions for the trusted-auditor registry.

The registry that accepts an external audit report is kept outside the candidate
repository, so nothing in the repository would notice if the procedure that maintains
it disappeared from the documentation.

A first version of this file checked only literal markers, such as a heading, and its
negative control was therefore tautological: removing a heading was detected, while
removing the clause that heading introduced was not. The checks below are clause-based,
and every clause is proved discriminating by removing its own text.

These tests also keep the entry builder honest about the fingerprint it publishes.
"""

from __future__ import annotations

import hashlib
import json
import re
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

SECTION_HEADING = "## Registro de auditores confiáveis"
MIN_SECTION_LINES = 15

REQUIRED_CLAUSES = {
    "secao do registro": r"^## Registro de auditores confiáveis$",
    "subsecao de custodia e separacao": r"^### Custódia e separação de funções$",
    "subsecao de procedimento": r"^### Procedimento$",
    "subsecao de rotacao": r"^### Rotação e revogação$",
    "subsecao de operador unico": r"^### Operador único$",
    "registro inalteravel pelo candidato": r"registro que o candidato não pode alterar",
    "custodiante autoriza e revoga": r"\*\*custodiante\*\* mantém o registro: autoriza, adiciona e revoga chaves",
    "produtor nao aprova o proprio registro": r"\*\*produtor do candidato\*\*[^\n]*não pode manter, editar nem aprovar o próprio registro",
    "detentor da chave nao implementa": r"\*\*detentor da chave privada de auditoria\*\*[^\n]*não pode ter participado da implementação auditada",
    "funcoes nao acumulaveis": r"nenhuma dessas funções pode estar na mesma pessoa",
    "chave gerada com senha e fora do contexto": r"chave privada cifrada por senha, fora do repositório e fora do contexto de implementação",
    "fingerprint derivado da chave publicada": r"deriva `public_key_sha256` dos bytes de `public_key_pem`",
    "registro publicado fora do candidato": r"nunca no repositório do candidato",
    "validacao por caminho local": r"referencia o registro apenas por caminho local",
    "rotacao com janela para pareceres antigos": r"mantém a anterior apenas durante a janela em que pareceres antigos ainda precisam ser validados",
    "rotacao periodica declarada": r"rotacionar no período declarado pelo custodiante",
    "revogacao remove a entrada": r"revogar é remover a entrada",
    "chave revogada nao aprova": r"chave removida do registro não aprova, mesmo com assinatura válida",
    "limitacao de operador unico": r"regra de contrato, não garantia estrutural",
    "declarar em vez de presumir": r"declarar a limitação em vez de presumir independência",
    "chave privada fora do repositorio": r"chave privada de auditoria fora do repositório e fora do contexto de implementação",
    "independencia nao veio de separacao de pessoas": r"não por separação de pessoas",
    "distribuir o CODEOWNERS": r"distribuir o `CODEOWNERS` assim que houver uma segunda pessoa",
    "gerador de chaves citado": r"`generate_auditor_keypair.py`",
    "construtor da entrada citado": r"`build_trusted_auditor_entry.py`",
}


def registry_section(text: str) -> str:
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip() == SECTION_HEADING), None)
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


def policy_errors(text: str) -> list[str]:
    errors = [f"cláusula ausente: {label}" for label, pattern in REQUIRED_CLAUSES.items() if not re.search(pattern, text, re.MULTILINE)]
    body = [
        line
        for line in registry_section(text).splitlines()
        if line.strip() and not line.startswith("###") and line.strip() != SECTION_HEADING
    ]
    if len(body) < MIN_SECTION_LINES:
        errors.append(f"seção do registro com corpo insuficiente: {len(body)} linhas")
    return errors


def strip_clause(text: str, pattern: str) -> str:
    """Remove every occurrence of a clause, including the heading anchor it lives on."""
    return re.sub(pattern, "", text, flags=re.MULTILINE)


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
    assert policy_errors(SECURITY.read_text(encoding="utf-8")) == []


def test_each_required_clause_is_detected_when_removed() -> None:
    text = SECURITY.read_text(encoding="utf-8")
    for label, pattern in REQUIRED_CLAUSES.items():
        errors = policy_errors(strip_clause(text, pattern))
        assert f"cláusula ausente: {label}" in errors, label


def test_gutted_section_is_detected() -> None:
    text = SECURITY.read_text(encoding="utf-8")
    section = registry_section(text)
    gutted = "\n".join(line for line in section.splitlines() if line.startswith("#"))
    errors = policy_errors(text.replace(section, gutted))
    assert any("corpo insuficiente" in error for error in errors), errors


def test_every_line_of_the_registry_section_is_load_bearing() -> None:
    """Nenhuma linha do procedimento pode sumir sem que a checagem reprove.

    Uma versão anterior deste arquivo verificava marcadores literais, e por isso
    removia-se a cláusula que um heading introduzia sem que nada acusasse. Este
    controle percorre linha por linha da seção real, e cada remoção precisa produzir
    pelo menos um erro de política.
    """
    text = SECURITY.read_text(encoding="utf-8")
    section = registry_section(text)
    lines = section.splitlines()
    unprotected = [
        line
        for index, line in enumerate(lines)
        if line.strip()
        and not policy_errors(text.replace(section, "\n".join(item for position, item in enumerate(lines) if position != index)))
    ]
    assert unprotected == [], unprotected


def test_registry_section_is_bounded_by_the_next_heading() -> None:
    section = registry_section(SECURITY.read_text(encoding="utf-8"))
    assert section.startswith(SECTION_HEADING)
    assert "## Merge e release" not in section
    assert "### Operador único" in section


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


def test_builder_refuses_malformed_and_unreadable_keys(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.pem"
    malformed.write_text("-----BEGIN PUBLIC KEY-----\nnao-e-chave\n-----END PUBLIC KEY-----\n", encoding="utf-8")
    result = run_builder(
        "--public-key", str(malformed),
        "--key-id", "auditor-01",
        "--name", "Auditor Independente",
        "--repository", "owner/repo",
    )
    assert result.returncode == 2
    assert "inválida" in result.stderr

    binary = tmp_path / "binary.pem"
    binary.write_bytes(b"\xff\xfe\x00\x01")
    result = run_builder(
        "--public-key", str(binary),
        "--key-id", "auditor-01",
        "--name", "Auditor Independente",
        "--repository", "owner/repo",
    )
    assert result.returncode == 2
    assert "ilegível" in result.stderr


def test_builder_refuses_an_empty_repository_list_through_the_schema(tmp_path: Path) -> None:
    public_key = tmp_path / "auditor-public.pem"
    write_public_key(public_key)
    result = run_builder(
        "--public-key", str(public_key),
        "--key-id", "auditor-01",
        "--name", "Auditor Independente",
        "--repository", "",
    )
    assert result.returncode == 2
    assert "saída inválida" in result.stderr


def test_builder_requires_a_repository_argument(tmp_path: Path) -> None:
    public_key = tmp_path / "auditor-public.pem"
    write_public_key(public_key)
    result = run_builder(
        "--public-key", str(public_key),
        "--key-id", "auditor-01",
        "--name", "Auditor Independente",
    )
    assert result.returncode == 2
    assert "--repository" in result.stderr
    assert "saída inválida" not in result.stderr


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
