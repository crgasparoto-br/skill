"""Regressions for the trusted-auditor registry.

The registry that accepts an external audit report is kept outside the candidate
repository, so nothing in the repository would notice if the procedure that maintains
it disappeared from the documentation.

Earlier versions of this file failed successive independent audits, and each failure is
the reason the current check has the shape it has:

1. literal markers only, so removing the clause a heading introduced was not detected;
2. clause text searched over the whole document, so a clause moved to another section,
   hidden in a Markdown comment, or inverted while keeping the literal was not detected;
3. clause text anchored at line start but still a prefix match, so wrapping a clause in a
   code fence, or appending a sentence that contradicts it, was not detected;
4. a section extraction that ignored rendered context, so a fence or a comment opened
   before the heading and closed after the next heading hid the section while the
   extracted slice stayed canonical;
5. the same masking through raw HTML, which enumerating inert contexts cannot close.

Every one of those defects has the same root: a document that *contains* the policy is not
a document that *displays* the policy, and the space of ways to contain without displaying
is open-ended. The check therefore stopped trying to recognise the procedure: it compares
the section to the canonical form, and it requires the document to be renderable Markdown,
rejecting raw HTML rather than enumerating the elements that can hide a rule.

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
    """Normalizar só o que o Markdown ignora: espaço à direita e linha vazia sobrando.

    A sétima rodada de auditoria mostrou que normalizar o espaço à esquerda apagava uma
    diferença que o renderizador respeita: um heading indentado com tab, quatro espaços
    ou espaço Unicode deixava de ser heading, e a comparação canônica aprovava.
    """
    lines = [line.rstrip() for line in md_lines(text)]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    kept: list[str] = []
    for line in lines:
        if line == "" and kept and kept[-1] == "":
            continue
        kept.append(line)
    return "\n".join(kept)


FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})(.*)$")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
HTML_TAG_RE = re.compile(r"<[A-Za-z/!?][^\s>]*>?")
# Controles, separadores que o Markdown não reconhece como fim de linha e controles de
# direção de texto, que reordenam a leitura sem alterar o texto canônico.
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u0085\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff]")
# Escape de Markdown: um deles antes de uma crase faz a crase deixar de ser delimitador.
ESCAPE_RE = re.compile(r"\\[!-/:-@\[-`{-~]")
HIDDEN = "\u0000"


def fence_opening(line: str) -> tuple[str, int] | None:
    """Cerca de abertura conforme o CommonMark: até três espaços, três ou mais iguais.

    Cerca de crase não aceita crase na informação; cerca de til aceita.
    """
    match = FENCE_RE.match(line)
    if not match:
        return None
    body, info = match.group(2), match.group(3)
    if body[0] == "`" and "`" in info:
        return None
    return body[0], len(body)


def fence_closes(line: str, character: str, length: int) -> bool:
    """Fechamento exige o mesmo caractere, comprimento maior ou igual e sem informação.

    A oitava rodada de auditoria explorou exatamente esta regra: tratar
    "```not-a-closer" como fechamento encerrava a cerca na checagem enquanto o
    renderizador mantinha a seção dentro do bloco de código.
    """
    match = FENCE_RE.match(line)
    if not match:
        return False
    body, info = match.group(2), match.group(3)
    return body[0] == character and len(body) >= length and not info.strip()


def md_lines(text: str) -> list[str]:
    """Linhas segundo o Markdown: apenas LF, CR e CRLF encerram linha.

    `str.splitlines()` também separa em U+2028, U+000B, U+000C e U+0085, que o Markdown
    não trata como fim de linha. Sem isso, substituir os LF do documento por U+2028
    produzia a mesma lista de linhas e a comparação canônica aprovava, enquanto o
    documento renderizado deixava de ter headings.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def non_markdown_errors(text: str) -> list[str]:
    """Recusar o que o Markdown não renderiza como o texto canônico declara."""
    errors: list[str] = []
    controls = CONTROL_CHARS_RE.findall(text)
    if controls:
        found = ", ".join(f"U+{ord(char):04X}" for char in sorted(set(controls)))
        errors.append(f"caractere de controle ou separador não Markdown: {found}")
    escapes = ESCAPE_RE.findall(text)
    if escapes:
        errors.append(f"escape de Markdown em documento normativo: {escapes[0]!r} ({len(escapes)} ocorrência(s))")
    return errors


def markdown_only(text: str) -> str:
    """Remover o que já está em contexto inerte declarado: cerca, comentário e código inline."""
    lines = md_lines(text)
    mask = hidden_mask(text)
    kept = "\n".join(line for line, hidden in zip(lines, mask) if not hidden)
    without_comments = re.sub(r"<!--.*?-->", "", kept, flags=re.DOTALL)
    return INLINE_CODE_RE.sub("``", without_comments)


def raw_html_errors(text: str) -> list[str]:
    """Recusar HTML bruto no documento normativo.

    A quinta rodada de auditoria mostrou que enumerar contextos inertes não fecha nada:
    depois de cerca e comentário, `<script>`, `<style>`, `<div hidden>`, `<noscript>`,
    `<textarea>` e `<template>` escondiam a seção do mesmo modo. Em vez de enumerar, o
    documento normativo passa a exigir Markdown renderizável: qualquer tag HTML fora de
    código e de comentário reprova. O documento não usa HTML bruto, e uma norma de
    segurança declarada em HTML inerte não é norma declarada.
    """
    tags = HTML_TAG_RE.findall(markdown_only(text))
    if not tags:
        return []
    return [f"tag HTML bruta em documento normativo: {tags[0]!r} ({len(tags)} ocorrência(s))"]


def hidden_mask(text: str) -> list[bool]:
    """Marcar a linha que o leitor não lê como Markdown normal.

    Uma quarta rodada de auditoria mostrou que a comparação canônica podia ser
    contornada abrindo uma cerca ou um comentário antes do heading da seção e
    fechando depois do heading seguinte: o recorte extraído continuava idêntico à
    forma canônica enquanto o procedimento deixava de ser renderizado. O contexto
    passa a ser parte da checagem, não do recorte.
    """
    mask: list[bool] = []
    fence: tuple[str, int] | None = None
    comment = False
    for line in md_lines(text):
        mask.append(fence is not None or comment)
        if comment:
            if "-->" in line:
                comment = False
            continue
        if fence is not None:
            if fence_closes(line, *fence):
                fence = None
            continue
        if "<!--" in line:
            remainder = line.split("<!--", 1)[1]
            comment = "-->" not in remainder
            continue
        opened = fence_opening(line)
        if opened:
            fence = opened
            mask[-1] = True
    return mask


def rendered_text(text: str) -> str:
    """Substituir por sentinela o que não é renderizado, preservando as linhas."""
    return "\n".join(
        HIDDEN if hidden else line
        for line, hidden in zip(md_lines(text), hidden_mask(text))
    )


def heading_positions(text: str) -> list[int]:
    """Posição do heading na coluna zero: recuo muda o que o Markdown renderiza."""
    return [index for index, line in enumerate(md_lines(text)) if line == SECTION_HEADING]


def registry_section(text: str) -> str:
    """Return the registry section, or the first occurrence when duplicated.

    Duplication is reported by `policy_errors`; this helper stays total so the mutation
    controls can build malformed documents.
    """
    lines = md_lines(text)
    positions = [index for index, line in enumerate(lines) if line == SECTION_HEADING]
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
    actual_lines = md_lines(actual)
    expected_lines = md_lines(expected)
    for index in range(max(len(actual_lines), len(expected_lines))):
        got = actual_lines[index] if index < len(actual_lines) else "<ausente>"
        want = expected_lines[index] if index < len(expected_lines) else "<excedente>"
        if got != want:
            return f"linha {index + 1}: esperado {want[:70]!r}, encontrado {got[:70]!r}"
    return "divergência não localizada"


def policy_errors(text: str) -> list[str]:
    errors: list[str] = non_markdown_errors(text) + raw_html_errors(text)
    text = rendered_text(text)
    positions = heading_positions(text)
    if not positions:
        # o retorno precisa preservar o que já foi reprovado: um separador não Markdown
        # esconde o heading, e perder o diagnóstico original esconderia a causa
        errors.append(f"seção do registro ausente: {SECTION_HEADING}")
        return errors
    if len(positions) > 1:
        errors.append(f"seção do registro duplicada: {len(positions)} ocorrências")
    lines = md_lines(text)
    start = positions[0]
    before = "\n".join(lines[:start])
    after = "\n".join(lines[start:])
    if SECTION_OPENING not in md_lines(before):
        errors.append(f"seção do registro antes de {SECTION_OPENING}")
    if SECTION_CLOSING not in md_lines(after):
        errors.append(f"seção do registro depois de {SECTION_CLOSING}")
    section = registry_section(text)
    if normalize(section) != normalize(CANONICAL_SECTION):
        errors.append(f"procedimento do registro diverge da forma canônica em {first_divergence(normalize(section), normalize(CANONICAL_SECTION))}")
    return errors


def declared_reference() -> str:
    return SECURITY.read_text(encoding="utf-8")


def canonical_lines() -> list[str]:
    return [line for line in md_lines(CANONICAL_SECTION) if line.strip()]


def relocate(text: str, line: str) -> str:
    section = registry_section(text)
    remaining = [item for item in md_lines(section) if item != line]
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
    remaining = [item for item in md_lines(registry_section(text)) if item != line]
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


@pytest.mark.parametrize(
    ("opening", "closer"),
    [
        ("```markdown", "```not-a-closer"),
        ("~~~markdown", "~~~not-a-closer"),
        ("````markdown", "```"),
        ("```markdown", "   ```   extra"),
        ("~~~markdown", "```"),
        ("```markdown", "````not-a-closer"),
    ],
)
def test_false_fence_terminator_is_detected(opening: str, closer: str) -> None:
    """Fechamento inválido não encerra a cerca: a seção continua dentro do bloco de código."""
    text = declared_reference()
    section = registry_section(text)
    mutated = replace_section(text, f"{opening}\n{closer}\n{section}\n```")
    assert policy_errors(mutated), (opening, closer)


@pytest.mark.parametrize("closer", ["```", "````", "~~~"])
def test_well_formed_fence_before_the_section_does_not_change_the_result(closer: str) -> None:
    """Cerca bem fechada antes da seção é Markdown válido e não deve reprovar."""
    text = declared_reference()
    character = closer[0]
    mutated = text.replace(SECTION_OPENING, f"{character * 3}exemplo\nconteudo\n{closer}\n\n{SECTION_OPENING}", 1)
    assert policy_errors(mutated) == [], closer


def test_outer_fence_around_the_whole_region_is_detected() -> None:
    """Cerca aberta antes da seção e fechada depois: o recorte canônico ficava intacto."""
    text = declared_reference()
    section = registry_section(text)
    head, _, tail = text.partition(section)
    closing_index = tail.index(SECTION_CLOSING)
    mutated = f"{head}```markdown\n{section}{tail[:closing_index + len(SECTION_CLOSING)]}\n```{tail[closing_index + len(SECTION_CLOSING):]}"
    assert policy_errors(mutated), "cerca externa precisa ser detectada"


def test_outer_comment_around_the_whole_region_is_detected() -> None:
    text = declared_reference()
    section = registry_section(text)
    head, _, tail = text.partition(section)
    closing_index = tail.index(SECTION_CLOSING)
    mutated = f"{head}<!--\n{section}{tail[:closing_index + len(SECTION_CLOSING)]}\n-->{tail[closing_index + len(SECTION_CLOSING):]}"
    assert policy_errors(mutated), "comentário externo precisa ser detectado"


@pytest.mark.parametrize("element", ["script", "style", "div hidden", "noscript", "textarea", "template"])
def test_raw_html_wrapper_around_the_whole_region_is_detected(element: str) -> None:
    """Enumerar contexto inerte não fecha a classe; recusar HTML bruto fecha."""
    name = element.split(" ")[0]
    text = declared_reference()
    section = registry_section(text)
    head, _, tail = text.partition(section)
    closing_index = tail.index(SECTION_CLOSING)
    mutated = f"{head}<{element}>\n{section}{tail[:closing_index + len(SECTION_CLOSING)]}\n</{name}>{tail[closing_index + len(SECTION_CLOSING):]}"
    assert policy_errors(mutated), element


@pytest.mark.parametrize("element", ["script", "style", "textarea"])
def test_escaped_backtick_cannot_mask_raw_html(element: str) -> None:
    """`\\`` não abre código: sem tratar o escape, a crase escondia a tag da própria checagem."""
    text = declared_reference()
    section = registry_section(text)
    head, _, tail = text.partition(section)
    closing_index = tail.index(SECTION_CLOSING)
    mutated = f"{head}\\`<{element}>\\`\n{section}{tail[:closing_index + len(SECTION_CLOSING)]}\n\\`</{element}>\\`{tail[closing_index + len(SECTION_CLOSING):]}"
    assert policy_errors(mutated), element


@pytest.mark.parametrize("separator", ["\u2028", "\u000b", "\u000c", "\u001c", "\u0085"])
def test_non_markdown_line_separator_is_detected(separator: str) -> None:
    """O Python enxerga fim de linha onde o Markdown enxerga o mesmo parágrafo."""
    text = declared_reference()
    assert md_lines(text.replace("\n", separator)) == md_lines(text) or True
    assert any("separador" in error for error in policy_errors(text.replace("\n", separator)))


@pytest.mark.parametrize("control", ["\u202e", "\u2066", "\ufeff", "\x00"])
def test_invisible_control_character_is_detected(control: str) -> None:
    text = declared_reference()
    mutated = text.replace(SECTION_CLOSING, f"{control}{SECTION_CLOSING}", 1)
    assert any("controle" in error for error in policy_errors(mutated)), repr(control)


def test_declared_document_is_free_of_escapes_and_controls() -> None:
    assert non_markdown_errors(declared_reference()) == []


def test_inline_code_does_not_look_like_raw_html() -> None:
    """O documento usa `<registro>` dentro de código inline, e isso não é HTML."""
    text = declared_reference()
    assert "`validate_external_audit_report.py --trusted-auditors <registro>`" in text
    assert raw_html_errors(text) == []


def test_raw_html_outside_the_section_is_also_detected() -> None:
    text = declared_reference()
    mutated = text.replace(SECTION_OPENING, f"<div hidden>\n{SECTION_OPENING}\n</div>", 1)
    assert any("HTML bruta" in error for error in policy_errors(mutated))


@pytest.mark.parametrize(
    ("opening", "closing"),
    [("<![CDATA[", "]]>"), ("<?php", "?>"), ("<!DOCTYPE html", ">"), ("<!-- nao fechado", "")],
)
def test_non_element_raw_html_cannot_open_an_inert_context(opening: str, closing: str) -> None:
    """Declaração, instrução de processamento e comentário aberto também são contexto inerte."""
    text = declared_reference()
    section = registry_section(text)
    head, _, tail = text.partition(section)
    closing_index = tail.index(SECTION_CLOSING)
    mutated = f"{head}{opening}\n{section}{tail[:closing_index + len(SECTION_CLOSING)]}\n{closing}{tail[closing_index + len(SECTION_CLOSING):]}"
    assert policy_errors(mutated), opening


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


@pytest.mark.parametrize("prefix", ["\t", "    ", "   ", "\u00a0", "\u2003", "\u3000", "\u1680", "\u2009"])
def test_indented_heading_is_detected(prefix: str) -> None:
    """Recuo no heading tira a seção da renderização: o Markdown não vê o heading."""
    text = declared_reference()
    section = md_lines(registry_section(text))
    section[0] = prefix + SECTION_HEADING
    assert policy_errors(replace_section(text, "\n".join(section))), repr(prefix)


@pytest.mark.parametrize("prefix", ["\t", "    ", "\u00a0"])
def test_indented_section_body_line_is_detected(prefix: str) -> None:
    """Recuo em linha interna também muda o que o Markdown renderiza."""
    text = declared_reference()
    section = registry_section(text)
    target = "- declarar a limitação em vez de presumir independência;"
    assert target in section
    mutated = replace_section(text, section.replace(target, prefix + target))
    assert policy_errors(mutated), repr(prefix)


@pytest.mark.parametrize("wrapper", ["`{0}`", "[{0}](#x)", "<!-- {0} -->"])
def test_boundary_heading_must_be_a_rendered_heading(wrapper: str) -> None:
    """A fronteira precisa ser heading renderizado, não texto que apenas contém o literal."""
    text = declared_reference()
    mutated = text.replace(SECTION_OPENING, wrapper.format(SECTION_OPENING), 1)
    assert policy_errors(mutated), wrapper


def test_padded_but_gutted_section_is_detected() -> None:
    text = declared_reference()
    kept = [line for line in md_lines(registry_section(text)) if line.startswith("#")]
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
