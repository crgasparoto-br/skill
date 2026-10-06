"""Regressions for the trusted-auditor registry.

The registry that accepts an external audit report is kept outside the candidate
repository, so nothing in the repository would notice if the procedure that maintains
it disappeared from the documentation.

Three earlier versions of this file failed an independent audit, and each failure is the
reason the current check has the shape it has:

1. literal markers only, so removing the clause a heading introduced was not detected;
2. clause text searched over the whole document, so a clause moved to another section,
   hidden in a Markdown comment, or inverted while keeping the literal was not detected;
3. clause text anchored at line start but still a prefix match, so wrapping a clause in a
   code fence, or appending a sentence that contradicts it, was not detected.

Every one of those defects has the same root: a text that *contains* the policy is not a
text that *declares* the policy, and the space of ways to contain without declaring is
open-ended. The check therefore stopped trying to recognise the procedure and compares
the section to the canonical form instead.

The wording is canonical on purpose. To change the procedure, change `docs/SECURITY.md`
and `CANONICAL_SECTION` in the same commit: the diff in this file is then the evidence
that the change was deliberate. The section must also be declared exactly once, between
the authority boundaries and the merge policy.

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
SECTION_OPENING = "## Fronteiras de autoridade"
SECTION_CLOSING = "## Merge e release"
MIN_CANONICAL_LINES = 20

CANONICAL_SECTION = """## Registro de auditores confiáveis

A independência de auditoria é arquitetural: contexto separado, leitura somente e rederivação com parser próprio. O controle que fecha o ciclo é externo: `validate_external_audit_report.py --trusted-auditors <registro>` aceita apenas parecer assinado por chave presente em um registro que o candidato não pode alterar.

### Custódia e separação de funções

- o **custodiante** mantém o registro: autoriza, adiciona e revoga chaves;
- o **produtor do candidato** implementa a entrega e não pode manter, editar nem aprovar o próprio registro;
- o **detentor da chave privada de auditoria** assina pareceres em contexto separado e não pode ter participado da implementação auditada;
- para o mesmo candidato, nenhuma dessas funções pode estar na mesma pessoa.

### Procedimento

1. gerar o par Ed25519 com `generate_auditor_keypair.py`, com a chave privada cifrada por senha, fora do repositório e fora do contexto de implementação;
2. montar a entrada do registro com `build_trusted_auditor_entry.py`, que deriva `public_key_sha256` dos bytes de `public_key_pem` em vez de aceitar valor informado;
3. o custodiante revisa a entrada, confirma `repositories` e publica o registro no ambiente do operador, nunca no repositório do candidato;
4. a validação do parecer referencia o registro apenas por caminho local.

### Rotação e revogação

- rotacionar no período declarado pelo custodiante e sempre que houver dúvida sobre a custódia da chave privada;
- uma rotação adiciona a nova chave e mantém a anterior apenas durante a janela em que pareceres antigos ainda precisam ser validados;
- revogar é remover a entrada; `enabled` é constante `true` no esquema atual, então não existe desabilitação parcial sem que o esquema mude;
- parecer assinado por chave removida do registro não aprova, mesmo com assinatura válida.

### Operador único

Enquanto houver um único proprietário no `.github/CODEOWNERS`, a separação de funções acima é regra de contrato, não garantia estrutural. Nesse cenário:

- declarar a limitação em vez de presumir independência;
- manter a chave privada de auditoria fora do repositório e fora do contexto de implementação, com senha distinta das demais;
- registrar no artefato de auditoria que a independência foi obtida por contexto separado e custódia declarada, não por separação de pessoas;
- distribuir o `CODEOWNERS` assim que houver uma segunda pessoa, antes de depender da separação para uma aprovação material."""


def normalize(text: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    kept: list[str] = []
    for line in lines:
        if line == "" and kept and kept[-1] == "":
            continue
        kept.append(line)
    return "\n".join(kept)


def heading_positions(text: str) -> list[int]:
    return [index for index, line in enumerate(text.splitlines()) if line.strip() == SECTION_HEADING]


def registry_section(text: str) -> str:
    """Return the registry section, or the first occurrence when duplicated.

    Duplication is reported by `policy_errors`; this helper stays total so the mutation
    controls can build malformed documents.
    """
    lines = text.splitlines()
    positions = [index for index, line in enumerate(lines) if line.strip() == SECTION_HEADING]
    if not positions:
        return ""
    start = positions[0]
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return "\n".join(lines[start:end])


def replace_section(text: str, new_section: str) -> str:
    section = registry_section(text)
    assert section, "a seção do registro precisa existir para ser mutada"
    head, _, tail = text.partition(section)
    return head + new_section + tail


def first_divergence(actual: str, expected: str) -> str:
    actual_lines = actual.splitlines()
    expected_lines = expected.splitlines()
    for index in range(max(len(actual_lines), len(expected_lines))):
        got = actual_lines[index] if index < len(actual_lines) else "<ausente>"
        want = expected_lines[index] if index < len(expected_lines) else "<excedente>"
        if got != want:
            return f"linha {index + 1}: esperado {want[:70]!r}, encontrado {got[:70]!r}"
    return "divergência não localizada"


def policy_errors(text: str) -> list[str]:
    errors: list[str] = []
    positions = heading_positions(text)
    if not positions:
        return [f"seção do registro ausente: {SECTION_HEADING}"]
    if len(positions) > 1:
        errors.append(f"seção do registro duplicada: {len(positions)} ocorrências")
    lines = text.splitlines()
    start = positions[0]
    before = "\n".join(lines[:start])
    after = "\n".join(lines[start:])
    if SECTION_OPENING not in before:
        errors.append(f"seção do registro antes de {SECTION_OPENING}")
    if SECTION_CLOSING not in after:
        errors.append(f"seção do registro depois de {SECTION_CLOSING}")
    section = registry_section(text)
    if normalize(section) != normalize(CANONICAL_SECTION):
        errors.append(f"procedimento do registro diverge da forma canônica em {first_divergence(normalize(section), normalize(CANONICAL_SECTION))}")
    return errors


def declared_reference() -> str:
    return SECURITY.read_text(encoding="utf-8")


def canonical_lines() -> list[str]:
    return [line for line in CANONICAL_SECTION.splitlines() if line.strip()]


def relocate(text: str, line: str) -> str:
    section = registry_section(text)
    remaining = [item for item in section.splitlines() if item != line]
    mutated = replace_section(text, "\n".join(remaining))
    return mutated.replace(SECTION_CLOSING, f"{SECTION_CLOSING}\n\n{line}", 1)


def fence(line: str) -> list[str]:
    return ["```markdown", line, "```"]


# --- a política declarada -------------------------------------------------------------


def test_security_document_declares_the_registry_procedure() -> None:
    assert policy_errors(declared_reference()) == []


def test_canonical_section_is_substantial() -> None:
    assert len(canonical_lines()) >= MIN_CANONICAL_LINES


def test_canonical_section_is_the_one_shipped_in_the_document() -> None:
    assert normalize(registry_section(declared_reference())) == normalize(CANONICAL_SECTION)


# --- controles negativos: cada classe de mascaramento precisa ser detectada ------------
#
# Todas as classes abaixo passaram por alguma versão anterior deste arquivo. Nenhuma
# delas é detectada por reconhecimento de texto; todas são detectadas porque alteram o
# que a seção declara.


@pytest.mark.parametrize("line", canonical_lines())
def test_removed_line_is_detected(line: str) -> None:
    text = declared_reference()
    remaining = [item for item in registry_section(text).splitlines() if item != line]
    assert policy_errors(replace_section(text, "\n".join(remaining))), line


@pytest.mark.parametrize("line", canonical_lines())
def test_relocated_line_is_detected(line: str) -> None:
    assert policy_errors(relocate(declared_reference(), line)), line


@pytest.mark.parametrize("line", canonical_lines())
def test_commented_line_is_detected(line: str) -> None:
    text = declared_reference()
    section = registry_section(text)
    mutated = replace_section(text, section.replace(line, f"<!-- {line} -->"))
    assert policy_errors(mutated), line


@pytest.mark.parametrize("line", canonical_lines())
def test_fenced_line_is_detected(line: str) -> None:
    """Cerca transforma procedimento em exemplo, e exemplo não é regra."""
    text = declared_reference()
    section = registry_section(text)
    mutated = replace_section(text, section.replace(line, "\n".join(fence(line))))
    assert policy_errors(mutated), line


@pytest.mark.parametrize("line", canonical_lines())
def test_contradicting_suffix_is_detected(line: str) -> None:
    """Manter o literal e acrescentar a negação não pode continuar aprovando."""
    text = declared_reference()
    section = registry_section(text)
    mutated = replace_section(text, section.replace(line, f"{line} É permitido o contrário do que esta linha afirma."))
    assert policy_errors(mutated), line


def test_fenced_body_is_detected() -> None:
    text = declared_reference()
    section = registry_section(text)
    mutated = replace_section(text, "\n".join(["```markdown", section, "```"]))
    assert policy_errors(mutated)


def test_duplicated_section_is_detected() -> None:
    text = declared_reference()
    section = registry_section(text)
    mutated = f"{text}\n\n{section}\n"
    errors = policy_errors(mutated)
    assert any("duplicada" in error for error in errors), errors


def test_relocated_section_is_detected() -> None:
    text = declared_reference()
    section = registry_section(text)
    without = replace_section(text, "").rstrip()
    mutated = f"{without}\n\n{section}\n"
    errors = policy_errors(mutated)
    assert any("depois de" in error for error in errors), errors


def test_missing_section_is_detected() -> None:
    text = declared_reference()
    mutated = replace_section(text, "")
    errors = policy_errors(mutated)
    assert errors == [f"seção do registro ausente: {SECTION_HEADING}"], errors


def test_renamed_heading_is_detected() -> None:
    text = declared_reference()
    section = registry_section(text).replace(SECTION_HEADING, "## Registro de auditores")
    assert policy_errors(replace_section(text, section))


def test_padded_but_gutted_section_is_detected() -> None:
    text = declared_reference()
    kept = [line for line in registry_section(text).splitlines() if line.startswith("#")]
    padding = ["enchimento para satisfazer qualquer contagem"] * 30
    assert policy_errors(replace_section(text, "\n".join(kept + padding)))


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
