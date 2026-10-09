#!/usr/bin/env python3
"""Fail-closed validation of the user-visible audit verdict header."""
import argparse
import re
from pathlib import Path

VERDICTS = ("APROVADA", "APROVADA COM RESSALVAS", "APROVADA INTERNAMENTE", "INCONCLUSIVA", "REPROVADA")
HEADER = re.compile(r"^# RESULTADO: (APROVADA COM RESSALVAS|APROVADA INTERNAMENTE|APROVADA|INCONCLUSIVA|REPROVADA)$")
SUMMARY = re.compile(r"^> \*\*Conclusao:\*\* \`([^\`]+)\` — achados bloqueantes: \`(\d+)\` — recomendacoes opcionais: \`(\d+)\`$")
REASON = re.compile(r"^> \*\*Motivo determinante:\*\* \S.+$")
MERGE = re.compile(r"^> \*\*Libera merge/release:\*\* (SIM|NAO)$")
VALIDITY = re.compile(r"^\*\*Validade:\*\* (Independente|Controller-adversarial|Pre-auditoria)$")


def validate(text: str) -> list[str]:
    errors = []
    if text.startswith("\ufeff"):
        errors.append("BOM antes do veredito")
    lines = text.splitlines()
    if len(lines) < 6 or not (match := HEADER.fullmatch(lines[0])):
        return errors + ["primeira linha deve conter exatamente # RESULTADO: <veredito valido>"]
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
    args = parser.parse_args()
    errors = validate(args.report.read_text(encoding="utf-8"))
    for error in errors:
        print(f"FAIL: {error}")
    if errors:
        return 1
    print("PASS: cabecalho de auditoria valido")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
