#!/usr/bin/env python3
"""Fail-closed validation of the user-visible audit verdict header."""
import argparse
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
    if confirmed and "## Achados bloqueantes" not in lines:
        errors.append("bloqueadores comprovados exigem secao de achados bloqueantes")
    if risks and "## Riscos inferidos nao confirmados" not in lines:
        errors.append("riscos inferidos exigem secao propria")
    if limitations and "## Limitacoes exclusivas do auditor" not in lines:
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


def visible_lines(lines):
    """Do not allow example records in fenced code blocks to satisfy evidence."""
    output = []
    fence = None
    for line in lines:
        marker = re.match(r"^\s*(~{3,}|"+chr(96)+r"{3,})", line)
        if marker:
            mark = marker.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence is None:
            output.append(line)
    return output


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
    return bool(re.search(
        r"(?:\b[\w./-]+:\d+\b|https?://\S+|\b[0-9a-f]{40}\b|"
        r"\b(?:git show|pytest|python -m|CI run)\b)",
        value, re.IGNORECASE,
    ))


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


def detect_misplaced_records(plain):
    """Reject records outside their canonical section, even with zero counts."""
    errors = []
    section_for_prefix = {prefix: section for section, (prefix, _) in CATEGORIES.items()}
    current_section = None
    all_ids = set()
    for line in plain:
        if line.startswith("## "):
            current_section = line
        if not line.startswith("### "):
            continue
        # Detect candidate records across the *entire* visible body, not only
        # inside a canonical section. A misplaced record must never hide at zero.
        match = re.match(r"^###\s+(?:\[[^\]]+\]\s+)?((?:A|RISK|LIM)-[0-9]{3,})\b", line)
        if not match:
            continue
        identifier = match.group(1)
        prefix = identifier.split("-", 1)[0]
        if current_section != section_for_prefix[prefix]:
            errors.append(f"{identifier}: item fora da secao {section_for_prefix[prefix]}")
        if identifier in all_ids:
            errors.append(f"ID duplicado na triagem: {identifier}")
        all_ids.add(identifier)
    return errors


def parse_evidence(lines, expected_counts):
    """Reconcile declared triage with structured, evidence-bearing body records."""
    errors = []
    plain = visible_lines(lines)
    items = {}
    sections = [(index, line) for index, line in enumerate(plain) if line.startswith("## ")]
    errors.extend(detect_misplaced_records(plain))
    for section, (prefix, required) in CATEGORIES.items():
        found = [index for index, name in sections if name == section]
        entries = {}
        if len(found) > 1:
            errors.append(f"secao de triagem repetida: {section}")
        if found:
            start = found[0]
            end = next((index for index, _ in sections if index > start), len(plain))
            content = plain[start + 1:end]
            headers = [(index, line) for index, line in enumerate(content) if line.startswith("### ")]
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


def validate_reclassification_proofs(fields, changed_items):
    errors = []
    if fields.get("Nova evidencia") and (
        not contextual_detail(fields["Nova evidencia"][0], minimum=28)
        or not source_anchor(fields["Nova evidencia"][0])
    ):
        errors.append("retificacao: nova evidencia sem fonte verificavel")
    for identifier in sorted(changed_items):
        values = fields.get(f"Prova de reclassificacao {identifier}", [])
        if (len(values) != 1 or not contextual_detail(values[0], minimum=28)
                or not source_anchor(values[0])):
            errors.append(f"retificacao: item {identifier} alterado/retirado sem prova contextual")
    return errors


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
    if section not in plain:
        return ["mudanca de veredito/triagem exige Retificacao do parecer"]
    start = plain.index(section)
    end = next((index for index in range(start + 1, len(plain)) if plain[index].startswith("## ")), len(plain))
    fields = {}
    for line in plain[start + 1:end]:
        match = re.fullmatch(r"- \*\*(.+?):\*\*\s*(.*)", line)
        if match:
            fields.setdefault(match.group(1), []).append(match.group(2))
    errors = []
    for key in ("Veredito anterior", "Veredito atual", "Motivo da retificacao", "Nova evidencia", "HEAD auditado"):
        values = fields.get(key, [])
        if len(values) != 1 or not non_placeholder(values[0]):
            errors.append(f"retificacao sem {key}")
    if fields.get("Veredito anterior") != [old_lines[0].removeprefix("# RESULTADO: ")]:
        errors.append("retificacao: veredito anterior divergente")
    if fields.get("Veredito atual") != [new_lines[0].removeprefix("# RESULTADO: ")]:
        errors.append("retificacao: veredito atual divergente")
    head = fields.get("HEAD auditado", [""])[0].strip(chr(96))
    if not SHA.fullmatch(head):
        errors.append("retificacao: HEAD auditado deve ser SHA completo")
    errors.extend(validate_reclassification_proofs(fields, changed_items))
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
    if "## Retificacao do parecer" in visible_lines(current.splitlines()) and not args.previous:
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
