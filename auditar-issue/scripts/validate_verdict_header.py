#!/usr/bin/env python3
"""Fail-closed validation of the user-visible audit verdict header."""
import argparse
import hashlib
import html
import re
from pathlib import Path

HEADER = re.compile(r"^# RESULTADO: (APROVADA COM RESSALVAS|APROVADA INTERNAMENTE|APROVADA|INCONCLUSIVA|REPROVADA)$")
SUMMARY = re.compile(r"^> \*\*Conclusao:\*\* \`([^\`]+)\` — achados bloqueantes: \`(\d+)\` — recomendacoes opcionais: \`(\d+)\`$")
REASON = re.compile(r"^> \*\*Motivo determinante:\*\* \S.+$")
MERGE = re.compile(r"^> \*\*Libera merge/release:\*\* (SIM|NAO)$")
VALIDITY = re.compile(r"^\*\*Validade:\*\* (Independente|Controller-adversarial|Pre-auditoria)$")
TRIAGE = re.compile(r"^\*\*Triagem:\*\* bloqueadores comprovados: `([0-9]+)` \| riscos inferidos: `([0-9]+)` \| limitacoes do auditor: `([0-9]+)`$")


def validate(text: str) -> list[str]:
    errors = []
    if text.startswith("\ufeff"):
        errors.append("BOM antes do veredito")
    lines = text.splitlines()
    if len(lines) < 6 or not (match := HEADER.fullmatch(lines[0])):
        errors.append("primeira linha deve conter exatamente # RESULTADO: <veredito valido>")
        return errors
    verdict = match.group(1)
    if len(lines) < 6 or lines[1] != "":
        errors.append("linha vazia obrigatoria apos veredito")
    summary = SUMMARY.fullmatch(lines[2]) if len(lines) > 2 else None
    if summary is None:
        errors.append("bloco de conclusao ausente ou invalido")
    elif summary.group(1) != verdict:
        errors.append("veredito da conclusao diverge da primeira linha")
    if len(lines) <= 3 or not REASON.fullmatch(lines[3]) or "[" in lines[3]:
        errors.append("motivo determinante ausente ou placeholder")
    merge = MERGE.fullmatch(lines[4]) if len(lines) > 4 else None
    if not merge:
        errors.append("decisao de merge/release ausente")
    if len(lines) <= 5 or lines[5] != "":
        errors.append("linha vazia obrigatoria antes da validade")
    validity = VALIDITY.fullmatch(lines[6]) if len(lines) > 6 else None
    if validity is None:
        errors.append("validade ausente ou invalida")
    errors.extend(validate_triage(verdict, summary, lines))
    errors.extend(validate_body(lines))
    errors.extend(validate_decision(verdict, summary, merge, validity))
    return errors


def validate_triage(verdict, summary, lines):
    errors = []
    triage = TRIAGE.fullmatch(lines[7]) if len(lines) > 7 else None
    if triage is None:
        return ["triagem factual ausente ou invalida"]
    confirmed, risks, limitations = (int(value) for value in triage.groups())
    if summary and confirmed != int(summary.group(2)):
        errors.append("triagem diverge do numero de achados bloqueantes")
    if confirmed and verdict != "REPROVADA":
        errors.append("bloqueador comprovado exige REPROVADA, mesmo com limitacao do auditor")
    if verdict == "REPROVADA" and not confirmed:
        errors.append("REPROVADA sem bloqueador comprovado")
    if limitations and verdict in ("APROVADA", "APROVADA COM RESSALVAS", "APROVADA INTERNAMENTE"):
        errors.append("limitacao material do auditor impede aprovacao")
    if verdict == "INCONCLUSIVA" and not limitations:
        errors.append("INCONCLUSIVA exige limitacao do auditor")
    sections = canonical_sections(lines)
    if confirmed and "## Achados bloqueantes" not in sections:
        errors.append("bloqueadores comprovados exigem secao de achados bloqueantes")
    if risks and "## Riscos inferidos nao confirmados" not in sections:
        errors.append("riscos inferidos exigem secao propria")
    if limitations and "## Limitacoes exclusivas do auditor" not in sections:
        errors.append("limitacoes do auditor exigem secao propria")
    return errors



# Validate concrete records, rather than trusting the section titles alone.
CATEGORIES = {
    "## Achados bloqueantes": ("A", ("Requisitos afetados", "Origem comprovada", "Evidência")),
    "## Riscos inferidos nao confirmados": (
        "RISK", ("Cenário hipotético", "Base da inferência", "Grau de certeza", "Prova discriminante pendente")
    ),
    "## Limitacoes exclusivas do auditor": (
        "LIM", ("Recurso indisponível", "Gate obrigatório afetado", "Tentativas e fallbacks", "Prova indisponível")
    ),
}
PLACEHOLDER = re.compile(r"^(?:[.\-? ]+|unknown|todo|tbd|n/?a|\[[^]]*\])$", re.IGNORECASE)
SHA = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)


QUOTE_PREFIX = re.compile(r"^ {0,3}>[ \t]?")
LIST_PREFIX = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])[ \t]+")
FENCE_MARKER = re.compile(r"^ {0,3}(~{3,}|"+chr(96)+r"{3,})(.*)$")
HTML_RAW_OPEN = re.compile(r"^ {0,3}<(pre|script|style|textarea)(?:[ \t>])", re.IGNORECASE)
# CommonMark HTML blocks of type 6 terminate at a blank line, not at the
# closing tag. Recognize the full standard block-tag list to avoid mistaking
# illustrative HTML content for evidence headings in Markdown.
HTML_BLOCK_TAGS = (
    "address", "article", "aside", "base", "basefont", "blockquote", "body",
    "caption", "center", "col", "colgroup", "dd", "details", "dialog",
    "dir", "div", "dl", "dt", "fieldset", "figcaption", "figure",
    "footer", "form", "frame", "frameset", "h1", "h2", "h3", "h4",
    "h5", "h6", "head", "header", "hr", "html", "iframe", "legend",
    "li", "link", "main", "menu", "menuitem", "meta", "nav",
    "noframes", "ol", "optgroup", "option", "output", "p", "param",
    "search", "section", "summary", "table", "tbody", "td", "tfoot",
    "th", "thead", "title", "tr", "track", "ul",
)
HTML_BLOCK_OPEN = re.compile(
    r"^ {0,3}</?(?:" + "|".join(HTML_BLOCK_TAGS) + r")(?=[ \t/>])",
    re.IGNORECASE,
)
# CommonMark type 7: a complete opening/closing HTML tag on its own line
# starts a raw block terminated by a blank line, including custom elements.
HTML_BLOCK_GENERIC = re.compile(
    r"^ {0,3}</?[A-Za-z][A-Za-z0-9-]*"
    r"(?:[ \t]+[A-Za-z_:][\w:.-]*(?:[ \t]*=[ \t]*(?:\"[^\"]*\"|'[^']*'|[^ \t=<>\x60'\"]+))?)*"
    r"[ \t]*/?>[ \t]*$"
)

# Only an evidence-shaped identifier at the start of a visible record counts.
# Inline emphasis/code may decorate the ID, but cannot conceal it.
# A visible evidence identifier may be decorated by CommonMark inline markup.
# The rendering-equivalent identifier remains material even if it is a link,
# emphasis, strike-through, inline HTML, or a numeric HTML entity.
INLINE_EVIDENCE_TAG = r"(?:strong|b|em|i|del|s|strike|code|span|a)"
VISIBLE_RECORD_ID = re.compile(
    r"^(?:\[[^\]]+\][ \t]+)?"
    r"(?:\*\*|__|\*|_|~~|`{1,3}|<(?:" + INLINE_EVIDENCE_TAG + r")(?:[ \t]+[^>]*?)?>)*"
    r"\[?((?:A|RISK|LIM)-[0-9]{3,})"
    r"(?:\](?:\([^()\n]+\)|\[[^\]\n]*\]))?"
    r"(?:</(?:" + INLINE_EVIDENCE_TAG + r")>|\*\*|__|\*|_|~~|`{1,3})*"
    r"(?=[ \t]+[—-]|[ \t]*:|$)"
)
RECORD_LIST_PREFIX = re.compile(
    r"^ {0,3}(?:(?:>[ \t]?|(?:[-+*]|\d{1,9}[.)])[ \t]+)[ \t]*)*"
)


def line_context(line, previous_indent, previous_quote_depth):
    """Resolve fence scope and list continuations without erasing visible headings."""
    quote_depth = 0
    candidate = line
    while (match := QUOTE_PREFIX.match(candidate)):
        quote_depth += 1
        candidate = candidate[match.end():]
    if quote_depth != previous_quote_depth:
        previous_indent = 0
    list_match = LIST_PREFIX.match(candidate)
    if list_match:
        list_indent = len(list_match.group())
        candidate = candidate[list_match.end():]
        in_list = True
    else:
        indent = len(candidate) - len(candidate.lstrip(" "))
        list_indent = previous_indent if (not candidate.strip() or indent >= previous_indent) else 0
        in_list = bool(list_indent)
        if in_list and candidate.strip():
            candidate = candidate[list_indent:]
    return candidate, quote_depth, list_indent, in_list


def raw_html_line(candidate, state, quote_depth, in_list, list_indent, paragraph_open):
    """Track CommonMark raw HTML without treating inner headings as records."""
    tag, old_quote, old_list = state
    if tag and (quote_depth != old_quote or (old_list and not in_list and candidate.strip())):
        tag = None
    if tag == "html-block":
        # CommonMark type 6: the raw block ends only at a blank line.
        if not candidate.strip():
            return False, (None, 0, 0)
        return True, (tag, old_quote, old_list)
    if tag:
        if re.search(rf"</{tag}\s*>", candidate, re.IGNORECASE):
            tag = None
        return True, (tag, old_quote, old_list)
    opened = HTML_RAW_OPEN.match(candidate)
    if opened:
        tag = opened.group(1)
        if re.search(rf"</{tag}\s*>", candidate, re.IGNORECASE):
            return True, (None, 0, 0)
        return True, (tag, quote_depth, list_indent if in_list else 0)
    # CommonMark type 6 interrupts paragraphs, while type 7 cannot.
    if HTML_BLOCK_OPEN.match(candidate) or (
        not paragraph_open and HTML_BLOCK_GENERIC.match(candidate)
    ):
        return True, ("html-block", quote_depth, list_indent if in_list else 0)
    return False, (None, 0, 0)


def normalize_list_record(line, candidate, in_list):
    """Keep visible list records detectable without promoting indented code."""
    if in_list and (
        re.match(r"^ {0,3}#{1,6}(?:[ \t]+|$)", candidate)
        or re.match(r"^[ \t]*(?:[-+*]|\d{1,9}[.)])[ \t]+", candidate)
    ):
        return "- " + candidate.lstrip()
    return line


def list_code_state(line, in_list, current_indent, preceding_blank, active_code):
    """Distinguish code in a list from a visible nested list item."""
    source_indent = len(line) - len(line.lstrip(" "))
    is_code = (
        in_list and source_indent >= current_indent + 4
        and (preceding_blank or active_code)
    )
    blank = not line.strip()
    return is_code, blank, is_code or (active_code and blank)


def consume_html_comment(candidate, active):
    """Keep an HTML comment inert, preserving its closing delimiter."""
    if active:
        return True, "-->" not in candidate
    return False, False


def paragraph_still_open(active, candidate, quote_depth, old_quote_depth, old_list_indent, in_list):
    """Keep the current paragraph only inside its existing CommonMark container."""
    return bool(
        active and candidate.strip() and quote_depth == old_quote_depth
        and (not old_list_indent or in_list)
    )


def container_ended(active, old_quote, old_list, quote_depth, in_list, candidate):
    """Reset inert container state only when its Markdown container ends."""
    return bool(
        active and (
            quote_depth != old_quote
            or (old_list and not in_list and candidate.strip())
        )
    )


def visible_lines(lines):
    """Ignore inert Markdown without letting a nested fence hide visible findings."""
    output = []
    fence = None
    fence_quote = 0
    fence_list = 0
    list_indent = 0
    previous_quote_depth = 0
    html_comment = False
    comment_quote = 0
    comment_list = 0
    raw_state = (None, 0, 0)
    preceding_blank = False
    indented_list_code = False
    paragraph_open = False
    for line in lines:
        old_list_indent = list_indent
        old_quote_depth = previous_quote_depth
        candidate, quote_depth, current_indent, in_list = line_context(
            line, list_indent, previous_quote_depth,
        )
        paragraph_open = paragraph_still_open(
            paragraph_open, candidate, quote_depth, old_quote_depth, old_list_indent, in_list,
        )
        list_code, preceding_blank, indented_list_code = list_code_state(
            line, in_list, current_indent, preceding_blank, indented_list_code,
        )
        # A quote/list fence closes when its container ends. A bare following
        # heading is then visible; it must not be swallowed as an example.
        if container_ended(fence, fence_quote, fence_list, quote_depth, in_list, candidate):
            fence = None
        if container_ended(
            html_comment, comment_quote, comment_list, quote_depth, in_list, candidate,
        ):
            html_comment = False
        list_indent = current_indent
        previous_quote_depth = quote_depth
        skip_comment, html_comment = consume_html_comment(candidate, html_comment)
        if list_code or skip_comment:
            continue
        if fence is None:
            inert, raw_state = raw_html_line(
                candidate, raw_state, quote_depth, in_list, current_indent, paragraph_open,
            )
            if inert:
                paragraph_open = False
                continue
        # Root/quote lines indented by four spaces are code, not findings.
        # List-contained code is handled separately by list_code_state.
        if not in_list and len(candidate) - len(candidate.lstrip(" ")) >= 4:
            # Four-space indentation cannot start a code block during a
            # paragraph; preserve that state for subsequent type-7 HTML.
            continue
        marker = FENCE_MARKER.match(candidate)
        if marker:
            paragraph_open = False
            mark, suffix = marker.groups()
            if fence is None:
                if mark[0] == "~" or chr(96) not in suffix:
                    fence = mark
                    fence_quote = quote_depth
                    fence_list = list_indent if in_list else 0
                    continue
            elif mark[0] == fence[0] and len(mark) >= len(fence) and not suffix.strip():
                fence = None
                continue
        if fence is not None:
            continue
        # CommonMark comments are inert even when they contain ATX-looking IDs.
        if re.match(r"^ {0,3}<!--", candidate):
            paragraph_open = False
            if "-->" not in candidate:
                html_comment = True
                comment_quote = quote_depth
                comment_list = list_indent if in_list else 0
            continue
        # Preserve the list container across blank lines. A heading continuing
        # a list is never a canonical evidence record, even if indented <= 3.
        output.append(normalize_list_record(line, candidate, in_list))
        paragraph_open = bool(candidate.strip() and markdown_heading(candidate) is None)
    return output

def markdown_heading(line):
    """Recognize CommonMark ATX headings, not four-space indented code."""
    match = re.match(r"^ {0,3}(#{1,6})(?:[ \t]+|$)(.*)$", line)
    if not match:
        return None
    # Closing hashes are optional when preceded by horizontal whitespace.
    title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
    return len(match.group(1)), title


def canonical_sections(lines):
    return {
        "## " + heading[1]
        for line in visible_lines(lines)
        if (heading := markdown_heading(line)) and heading[0] == 2
    }


def non_placeholder(value):
    value = value.strip().strip(chr(96)).strip()
    return bool(value) and not PLACEHOLDER.fullmatch(value) and not re.search(
        r"\b(?:TODO|TBD|placeholder|a preencher|a definir)\b|\[(?:\.{2,}|[^]]*a preencher[^]]*)\]",
        value, re.IGNORECASE,
    )


def contextual_detail(value, minimum=20):
    """Check specificity only; independently verifying truth remains mandatory."""
    return non_placeholder(value) and len(value.strip()) >= minimum


def source_anchor(value):
    """Require a locatable artifact or command for a confirmed blocker."""
    artifact = re.search(
        r"(?:\b[\w./-]+:\d+(?:-\d+)?\b|https?://\S+|\b[0-9a-f]{40}\b|"
        r"\bCI run\s+#?\d{5,}\b)", value, re.IGNORECASE,
    )
    command = re.search(
        r"\b(?:python3?\s+-m\s+pytest|pytest)\s+"
        r"(?:-[\w-]+\s+)*[\w./-]+\.py\b[^\n]*?"
        r"\b(?:passed|failed|errors?|falhou|passou|reproduzido)\b",
        value, re.IGNORECASE,
    )
    return bool(artifact or command)


def validate_record(prefix, identifier, fields):
    """Validate contextual fields, not the independent truth of their contents."""
    errors = []
    if prefix == "A":
        if fields.get("Origem comprovada") not in (["candidato"], ["entrega"]):
            errors.append(f"{identifier}: origem deve ser candidato ou entrega")
        if fields.get("Requisitos afetados") and not contextual_detail(
            fields["Requisitos afetados"][0], minimum=6
        ):
            errors.append(f"{identifier}: requisito afetado sem identificacao suficiente")
        if fields.get("Evidência") and (
            not contextual_detail(fields["Evidência"][0], minimum=28)
            or not source_anchor(fields["Evidência"][0])
        ):
            errors.append(f"{identifier}: evidencia sem artefato/localizacao reproduzivel")
    elif prefix == "RISK":
        if fields.get("Grau de certeza") not in (["baixo"], ["medio"], ["alto"]):
            errors.append(f"{identifier}: grau de certeza invalido")
        for key in ("Cenário hipotético", "Base da inferência", "Prova discriminante pendente"):
            if fields.get(key) and not contextual_detail(fields[key][0]):
                errors.append(f"{identifier}: {key} sem contexto discriminante")
    elif prefix == "LIM":
        for key in ("Recurso indisponível", "Gate obrigatório afetado",
                    "Tentativas e fallbacks", "Prova indisponível"):
            if fields.get(key) and not contextual_detail(fields[key][0], minimum=15):
                errors.append(f"{identifier}: {key} sem contexto verificavel")
        attempts = fields.get("Tentativas e fallbacks", [""])[0]
        if attempts and not (
            ";" in attempts or "fallback" in attempts.lower()
            or "bundle" in attempts.lower()
        ):
            errors.append(f"{identifier}: tentativas e fallbacks nao discriminados")
    return errors


def nested_audit_heading(line):
    """Recognize evidence headings inside Markdown quotes or list items.

    Nested headings are visible, but cannot satisfy canonical section records.
    """
    container = r"(?:>[ \t]?|(?:[-+*]|\d{1,9}[.)])[ \t]+)"
    match = re.match(
        r"^ {0,3}" + container + r"(?: {0,3}" + container
        + r")* {0,3}(#{1,6})(?:[ \t]+|$)(.*)$", line,
    )
    if not match:
        return None
    title = re.sub(r"[ \t]+#+[ \t]*$", "", match.group(2)).strip()
    return len(match.group(1)), title


def detect_misplaced_records(plain):
    """Reject evidence-shaped records in any visible noncanonical Markdown form."""
    errors = []
    section_for_prefix = {prefix: section for section, (prefix, _) in CATEGORIES.items()}
    current_section = None
    all_ids = set()
    for line in plain:
        heading = markdown_heading(line)
        nested = heading is None
        if nested:
            heading = nested_audit_heading(line)
        if heading:
            level, title = heading
            if not nested and level == 1:
                current_section = None
            elif not nested and level == 2:
                current_section = "## " + title
            identifier_match = VISIBLE_RECORD_ID.match(html.unescape(title))
        else:
            level = 0
            # Strip container markers only at line start; prose mentioning
            # A-001 incidentally must not become a new evidence record.
            identifier_match = VISIBLE_RECORD_ID.match(
                html.unescape(RECORD_LIST_PREFIX.sub("", line).lstrip(" "))
            )
        if not identifier_match:
            continue
        identifier = identifier_match.group(1)
        prefix = identifier.split("-", 1)[0]
        if nested and heading:
            errors.append(f"{identifier}: item aninhado fora da secao canonica")
        elif level != 3 or not re.match(
            r"^(?:\[[^\]]+\] )?(?:A|RISK|LIM)-[0-9]{3,} [—-] \S", title,
        ):
            errors.append(f"{identifier}: item em formato nao canonico (H3 obrigatorio)")
        elif current_section != section_for_prefix[prefix]:
            errors.append(f"{identifier}: item fora da secao {section_for_prefix[prefix]}")
        if identifier in all_ids:
            errors.append(f"ID duplicado na triagem: {identifier}")
        all_ids.add(identifier)
    return errors

def atx_heading_positions(lines, level):
    """Collect canonical ATX headings without inflating record-parser complexity."""
    prefix = "#" * level + " "
    return [
        (index, prefix + heading[1])
        for index, line in enumerate(lines)
        if (heading := markdown_heading(line)) and heading[0] == level
    ]


def parse_evidence(lines, expected_counts):
    """Reconcile declared triage with structured, evidence-bearing body records."""
    errors = []
    plain = visible_lines(lines)
    items = {}
    sections = atx_heading_positions(plain, 2)
    boundaries = sorted(index for level in (1, 2)
                        for index, _ in atx_heading_positions(plain, level))
    errors.extend(detect_misplaced_records(plain))
    for section, (prefix, required) in CATEGORIES.items():
        found = [index for index, name in sections if name == section]
        entries = {}
        if len(found) > 1:
            errors.append(f"secao de triagem repetida: {section}")
        if found:
            start = found[0]
            end = next((index for index in boundaries if index > start), len(plain))
            content = plain[start + 1:end]
            headers = atx_heading_positions(content, 3)
            for index, (position, heading) in enumerate(headers):
                pattern = r"### (?:\[[^\]]+\] )?(" + prefix + r"-[0-9]{3,}) [—-] (\S.+)"
                match = re.fullmatch(pattern, heading)
                if match is None:
                    errors.append(f"item malformado em {section}: {heading}")
                    continue
                identifier = match.group(1)
                if not non_placeholder(match.group(2)):
                    errors.append(f"{identifier}: titulo vazio ou placeholder")
                if identifier in entries:
                    errors.append(f"ID duplicado na triagem: {identifier}")
                until = headers[index + 1][0] if index + 1 < len(headers) else len(content)
                fields = {}
                for line in content[position + 1:until]:
                    field_match = re.fullmatch(r"- \*\*(.+?):\*\*\s*(.*)", line)
                    if field_match:
                        fields.setdefault(field_match.group(1), []).append(field_match.group(2))
                for field in required:
                    values = fields.get(field, [])
                    if len(values) != 1 or not non_placeholder(values[0]):
                        errors.append(f"{identifier}: campo {field} ausente, duplicado ou placeholder")
                errors.extend(validate_record(prefix, identifier, fields))
                # Preserve the complete record, including its title and free
                # text. Changing an existing ID is still a material revision.
                entries[identifier] = {
                    "title": match.group(2).strip(),
                    "fields": fields,
                    "body": "\n".join(content[position + 1:until]).strip(),
                }
            if not headers and not any(line.strip() for line in content):
                errors.append(f"{section}: secao vazia")
            if not headers and any(
                line.strip() and not re.fullmatch(
                    r"(?i)(?:nenhum[ao]?|sem (?:achados|riscos|limitacoes))\.?", line.strip()
                )
                for line in content
            ):
                errors.append(f"{section}: conteudo sem itens estruturados")
        if len(entries) != expected_counts[section]:
            errors.append(
                f"{section}: contagem declarada {expected_counts[section]}, itens verificaveis {len(entries)}"
            )
        items[prefix] = entries
    return errors, items


def validate_body(lines):
    triage = TRIAGE.fullmatch(lines[7]) if len(lines) > 7 else None
    if triage is None:
        return []
    expected = dict(zip(CATEGORIES, (int(value) for value in triage.groups()), strict=True))
    errors, _ = parse_evidence(lines, expected)
    return errors


def changed_evidence_items(old_items, new_items):
    return {
        identifier
        for prefix in ("A", "RISK", "LIM")
        for identifier, prior_fields in old_items[prefix].items()
        if identifier not in new_items[prefix]
        or prior_fields != new_items[prefix][identifier]
    }


def validate_reclassification_proofs(fields, changed_items, previous_fields):
    """Preserve all former blocker proofs and require new proof for each edit."""
    errors = []
    if fields.get("Nova evidencia") and (
        not contextual_detail(fields["Nova evidencia"][0], minimum=28)
        or not source_anchor(fields["Nova evidencia"][0])
    ):
        errors.append("retificacao: nova evidencia sem fonte verificavel")
    proof_prefix = "Prova de reclassificacao "
    for key, historical in previous_fields.items():
        if key.startswith(proof_prefix) and fields.get(key, [])[:len(historical)] != historical:
            errors.append(f"retificacao: historico de {key.removeprefix(proof_prefix)} perdido ou alterado")
    for identifier in sorted(changed_items):
        key = f"{proof_prefix}{identifier}"
        values = fields.get(key, [])
        historical_count = len(previous_fields.get(key, []))
        if len(values) <= historical_count:
            errors.append(f"retificacao: item {identifier} alterado/retirado sem nova prova contextual")
        for value in values[historical_count:]:
            if not contextual_detail(value, minimum=28) or not source_anchor(value):
                errors.append(f"retificacao: item {identifier} alterado/retirado sem prova contextual")
    return errors

def revision_fields(lines):
    """Read the single revision ledger without interpreting unrelated sections."""
    plain = visible_lines(lines)
    headings = atx_heading_positions(plain, 2)
    starts = [i for i, heading in headings if heading == "## Retificacao do parecer"]
    if len(starts) != 1:
        return {}
    start = starts[0]
    boundaries = sorted(i for level in (1, 2)
                        for i, _ in atx_heading_positions(plain, level))
    end = next((i for i in boundaries if i > start), len(plain))
    fields = {}
    for line in plain[start + 1:end]:
        match = re.fullmatch(r"- \*\*(.+?):\*\*\s*(.*)", line)
        if match:
            fields.setdefault(match.group(1), []).append(match.group(2))
    return fields


def validate_revision(current_text, previous_text):
    """Compare entire reports and track removal or material revision of every item."""
    current_errors = validate(current_text)
    if current_errors:
        return ["novo parecer invalido: " + "; ".join(current_errors)]
    previous_errors = validate(previous_text)
    if previous_errors:
        return ["parecer anterior invalido: " + "; ".join(previous_errors)]
    old_lines = previous_text.splitlines()
    new_lines = current_text.splitlines()
    old_triage = TRIAGE.fullmatch(old_lines[7])
    new_triage = TRIAGE.fullmatch(new_lines[7]) if len(new_lines) > 7 else None
    if new_triage is None:
        return ["nova triagem invalida"]
    old_expected = dict(zip(CATEGORIES, (int(value) for value in old_triage.groups()), strict=True))
    new_expected = dict(zip(CATEGORIES, (int(value) for value in new_triage.groups()), strict=True))
    _, old_items = parse_evidence(old_lines, old_expected)
    _, new_items = parse_evidence(new_lines, new_expected)
    changed_items = changed_evidence_items(old_items, new_items)
    # Any edited report, including a changed reason or a same-ID title,
    # must carry an explicit, independently reviewable revision record.
    if current_text == previous_text:
        return []
    plain = visible_lines(new_lines)
    section = "## Retificacao do parecer"
    headings = [
        (index, heading[1])
        for index, line in enumerate(plain)
        if (heading := markdown_heading(line)) and heading[0] == 2
    ]
    starts = [index for index, title in headings if "## " + title == section]
    if len(starts) != 1:
        return ["mudanca de veredito/triagem exige Retificacao do parecer unica"]
    fields = revision_fields(new_lines)
    errors = []
    for key in ("Veredito anterior", "Veredito atual", "Motivo da retificacao", "Nova evidencia", "HEAD auditado"):
        values = fields.get(key, [])
        if len(values) != 1 or not non_placeholder(values[0]):
            errors.append(f"retificacao sem {key}")
        elif key == "Motivo da retificacao" and not contextual_detail(values[0], minimum=28):
            errors.append("retificacao: motivo sem fundamentacao contextual")
    if fields.get("Veredito anterior") != [old_lines[0].removeprefix("# RESULTADO: ")]:
        errors.append("retificacao: veredito anterior divergente")
    if fields.get("Veredito atual") != [new_lines[0].removeprefix("# RESULTADO: ")]:
        errors.append("retificacao: veredito atual divergente")
    head = fields.get("HEAD auditado", [""])[0].strip(chr(96))
    if not SHA.fullmatch(head):
        errors.append("retificacao: HEAD auditado deve ser SHA completo")
    previous_fields = {}
    if "## Retificacao do parecer" in canonical_sections(old_lines):
        previous_fields = revision_fields(old_lines)
        expected_digest = hashlib.sha256(previous_text.encode("utf-8")).hexdigest()
        if fields.get("SHA-256 do parecer anterior") != [expected_digest]:
            errors.append("retificacao: SHA-256 do parecer anterior ausente ou divergente")
    errors.extend(validate_reclassification_proofs(fields, changed_items, previous_fields))
    return errors


def validate_decision(verdict, summary, merge, validity):
    errors = []
    blockers = int(summary.group(2)) if summary else None
    if blockers is not None:
        if verdict == "REPROVADA" and blockers == 0:
            errors.append("reprovada exige ao menos um achado bloqueante")
        if verdict != "REPROVADA" and blockers != 0:
            errors.append("achados bloqueantes exigem resultado REPROVADA")
    if validity:
        independent = validity.group(1) == "Independente"
        if verdict in ("APROVADA", "APROVADA COM RESSALVAS") and not independent:
            errors.append("aprovacao definitiva exige validade independente")
        if verdict == "APROVADA INTERNAMENTE" and independent:
            errors.append("aprovacao interna nao pode declarar independencia")
    if merge:
        allowed = verdict in ("APROVADA", "APROVADA COM RESSALVAS") and bool(validity and validity.group(1) == "Independente")
        if merge.group(1) == "SIM" and not allowed:
            errors.append("merge liberado sem aprovacao independente")
        if not allowed and merge.group(1) != "NAO":
            errors.append("merge deveria estar bloqueado")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path, help="parecer humano em Markdown, nao o template")
    parser.add_argument("--previous", type=Path, help="parecer anterior para retificacao")
    parser.add_argument("--revision", action="store_true", help="exigir comparacao com parecer anterior")
    args = parser.parse_args()
    current = args.report.read_text(encoding="utf-8")
    errors = validate(current)
    if args.revision and not args.previous:
        errors.append("modo --revision exige --previous para comparar o parecer anterior")
    if "## Retificacao do parecer" in canonical_sections(current.splitlines()) and not args.previous:
        errors.append("retificacao exige --previous para confrontar parecer anterior")
    if not errors and args.previous:
        errors.extend(validate_revision(current, args.previous.read_text(encoding="utf-8")))
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("PASS: cabecalho, corpo e triagem de auditoria validos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
