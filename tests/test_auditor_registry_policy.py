"""Regressions for the trusted-auditor registry.

The registry that accepts an external audit report is kept outside the candidate
repository, so nothing in the repository would notice if the procedure that maintains
it disappeared from the documentation.

Two earlier versions of this file failed an independent audit, and both failures are
recorded here because they explain the shape of the checks:

- the first checked literal markers only, so removing the clause a heading introduced
  was not detected while the test claimed to cover every required element;
- the second checked clause text over the whole document, so a clause moved to another
  section, hidden in a Markdown comment, or inverted while keeping the literal was not
  detected.

The checks below are therefore scoped to the registry section, ignore commented text,
and anchor each clause at the start of its own line. The clause wording is canonical:
rewording a clause requires updating this table, and that is deliberate, because a gate
that guesses synonyms cannot prove the procedure is still declared.

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
MIN_CLAUSES = 22

REQUIRED_CLAUSES = {
    "subsecao de custodia e separacao": r"^### Custódia e separação de funções$",
    "subsecao de procedimento": r"^### Procedimento$",
    "subsecao de rotacao": r"^### Rotação e revogação$",
    "subsecao de operador unico": r"^### Operador único$",
    "registro inalteravel pelo candidato": r"^A independência de auditoria é arquitetural:.*registro que o candidato não pode alterar",
    "custodiante autoriza e revoga": r"^- o \*\*custodiante\*\* mantém o registro: autoriza, adiciona e revoga chaves",
    "produtor nao aprova o proprio registro": r"^- o \*\*produtor do candidato\*\* implementa a entrega e não pode manter, editar nem aprovar o próprio registro",
    "detentor da chave nao implementa": r"^- o \*\*detentor da chave privada de auditoria\*\* assina pareceres em contexto separado e não pode ter participado da implementação auditada",
    "funcoes nao acumulaveis": r"^- para o mesmo candidato, nenhuma dessas funções pode estar na mesma pessoa",
    "chave gerada com senha e fora do contexto": r"^1\. gerar o par Ed25519 com `generate_auditor_keypair\.py`, com a chave privada cifrada por senha, fora do repositório e fora do contexto de implementação",
    "fingerprint derivado da chave publicada": r"^2\. montar a entrada do registro com `build_trusted_auditor_entry\.py`, que deriva `public_key_sha256` dos bytes de `public_key_pem`",
    "registro publicado fora do candidato": r"^3\. o custodiante revisa a entrada, confirma `repositories` e publica o registro no ambiente do operador, nunca no repositório do candidato",
    "validacao por caminho local": r"^4\. a validação do parecer referencia o registro apenas por caminho local",
    "rotacao periodica declarada": r"^- rotacionar no período declarado pelo custodiante",
    "rotacao com janela para pareceres antigos": r"^- uma rotação adiciona a nova chave e mantém a anterior apenas durante a janela em que pareceres antigos ainda precisam ser validados",
    "revogacao remove a entrada": r"^- revogar é remover a entrada",
    "chave revogada nao aprova": r"^- parecer assinado por chave removida do registro não aprova, mesmo com assinatura válida",
    "limitacao de operador unico": r"^Enquanto houver um único proprietário no `\.github/CODEOWNERS`, a separação de funções acima é regra de contrato, não garantia estrutural",
    "declarar em vez de presumir": r"^- declarar a limitação em vez de presumir independência",
    "chave privada fora do repositorio": r"^- manter a chave privada de auditoria fora do repositório e fora do contexto de implementação",
    "independencia nao veio de separacao de pessoas": r"^- registrar no artefato de auditoria que a independência foi obtida por contexto separado e custódia declarada, não por separação de pessoas",
    "distribuir o CODEOWNERS": r"^- distribuir o `CODEOWNERS` assim que houver uma segunda pessoa, antes de depender da separação para uma aprovação material",
}


def visible_text(text: str) -> str:
    """Remove Markdown comments: text nobody reads cannot declare a procedure."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def registry_section(text: str) -> str:
    lines = visible_text(text).splitlines()
    start = next((index for index, line in enumerate(lines) if line.strip() == SECTION_HEADING), None)
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


def replace_section(text: str, new_section: str) -> str:
    section = registry_section(text)
    assert section, "a seção do registro precisa existir para ser mutada"
    head, _, tail = visible_text(text).partition(section)
    return head + new_section + tail


def section_lines(text: str) -> list[str]:
    return registry_section(text).splitlines()


def clause_lines(text: str, pattern: str) -> list[str]:
    return [line for line in section_lines(text) if re.search(pattern, line)]


def policy_errors(text: str) -> list[str]:
    section = registry_section(text)
    if not section:
        return [f"seção do registro ausente: {SECTION_HEADING}"]
    errors = [
        f"cláusula ausente: {label}"
        for label, pattern in REQUIRED_CLAUSES.items()
        if not re.search(pattern, section, re.MULTILINE)
    ]
    body = [
        line
        for line in section.splitlines()
        if line.strip() and not line.startswith("###") and line.strip() != SECTION_HEADING
    ]
    if len(body) < MIN_SECTION_LINES:
        errors.append(f"seção do registro com corpo insuficiente: {len(body)} linhas")
    return errors


def declared_reference() -> str:
    return SECURITY.read_text(encoding="utf-8")


# --- a política declarada -------------------------------------------------------------


def test_security_document_declares_the_registry_procedure() -> None:
    assert policy_errors(declared_reference()) == []


def test_clause_set_is_not_silently_trimmed() -> None:
    assert len(REQUIRED_CLAUSES) >= MIN_CLAUSES


def test_missing_section_is_detected() -> None:
    """A seção inteira é pré-condição: sem ela, nenhuma cláusula é avaliável."""
    text = declared_reference()
    lines = [line for line in section_lines(text) if line.strip() != SECTION_HEADING]
    errors = policy_errors(replace_section(text, "\n".join(lines)))
    assert errors == [f"seção do registro ausente: {SECTION_HEADING}"], errors


# --- controles negativos: cada classe de remoção precisa ser detectada -----------------


@pytest.mark.parametrize("label", list(REQUIRED_CLAUSES))
def test_clause_removed_from_the_section_is_detected(label: str) -> None:
    text = declared_reference()
    pattern = REQUIRED_CLAUSES[label]
    assert clause_lines(text, pattern), label
    remaining = [line for line in section_lines(text) if not re.search(pattern, line)]
    assert f"cláusula ausente: {label}" in policy_errors(replace_section(text, "\n".join(remaining))), label


@pytest.mark.parametrize("label", list(REQUIRED_CLAUSES))
def test_clause_relocated_outside_the_section_is_detected(label: str) -> None:
    text = declared_reference()
    pattern = REQUIRED_CLAUSES[label]
    moved = clause_lines(text, pattern)
    assert moved, label
    remaining = [line for line in section_lines(text) if not re.search(pattern, line)]
    mutated = replace_section(text, "\n".join(remaining))
    mutated = mutated.replace("## Merge e release", "## Merge e release\n\n" + "\n".join(moved), 1)
    assert f"cláusula ausente: {label}" in policy_errors(mutated), label


@pytest.mark.parametrize("label", list(REQUIRED_CLAUSES))
def test_clause_hidden_in_a_markdown_comment_is_detected(label: str) -> None:
    text = declared_reference()
    pattern = REQUIRED_CLAUSES[label]
    lines = [f"<!-- {line} -->" if re.search(pattern, line) else line for line in section_lines(text)]
    assert f"cláusula ausente: {label}" in policy_errors(replace_section(text, "\n".join(lines))), label


def test_inverted_clause_is_detected() -> None:
    text = declared_reference()
    target = "- para o mesmo candidato, nenhuma dessas funções pode estar na mesma pessoa."
    assert target in text
    mutated = text.replace(target, "- é incorreto afirmar que para o mesmo candidato nenhuma dessas funções pode estar na mesma pessoa.")
    assert "cláusula ausente: funcoes nao acumulaveis" in policy_errors(mutated)


def test_padded_but_gutted_section_is_detected() -> None:
    text = declared_reference()
    kept = [line for line in section_lines(text) if line.startswith("#")]
    padding = ["enchimento para satisfazer o corpo mínimo"] * (MIN_SECTION_LINES + 5)
    errors = policy_errors(replace_section(text, "\n".join(kept + padding)))
    assert any(error.startswith("cláusula ausente") for error in errors), errors


def test_every_line_of_the_registry_section_is_load_bearing() -> None:
    """Nenhuma linha do procedimento pode sumir sem que a checagem reprove."""
    text = declared_reference()
    lines = section_lines(text)
    assert len([line for line in lines if line.strip()]) >= MIN_SECTION_LINES
    unprotected = [
        line
        for index, line in enumerate(lines)
        if line.strip()
        and not policy_errors(replace_section(text, "\n".join(item for position, item in enumerate(lines) if position != index)))
    ]
    assert unprotected == [], unprotected


def test_registry_section_is_bounded_by_the_next_heading() -> None:
    section = registry_section(declared_reference())
    assert section.startswith(SECTION_HEADING)
    assert "## Merge e release" not in section
    assert "### Operador único" in section


# --- construtor de entrada -------------------------------------------------------------


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
