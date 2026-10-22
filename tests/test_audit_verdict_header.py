"""Regression checks for audit verdict headers."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "auditar-issue/scripts/validate_verdict_header.py"
spec = importlib.util.spec_from_file_location("verdict_header", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def report(verdict="APROVADA", summary=None, blockers=0, merge="SIM", validity="Independente",
           confirmed=None, risks=0, limitations=0):
    confirmed = blockers if confirmed is None else confirmed
    sections = (
        ("## Achados bloqueantes\nProva do candidato\n" if confirmed else "")
        + ("## Riscos inferidos nao confirmados\nHipotese sem prova\n" if risks else "")
        + ("## Limitacoes exclusivas do auditor\nGate indisponivel no runtime\n" if limitations else "")
    )
    return (
        f"# RESULTADO: {verdict}\n\n"
        f"> **Conclusao:** `{summary or verdict}` — achados bloqueantes: `{blockers}` — recomendacoes opcionais: `0`\n"
        "> **Motivo determinante:** Evidencias e gates obrigatorios foram verificados.\n"
        f"> **Libera merge/release:** {merge}\n\n"
        f"**Validade:** {validity}\n"
        f"**Triagem:** bloqueadores comprovados: `{confirmed}` | riscos inferidos: `{risks}` | limitacoes do auditor: `{limitations}`\n"
        f"\n## Evidencias\nOK\n{sections}"
    )


@pytest.mark.parametrize("verdict,blockers,merge,validity,limitations", [
    ("APROVADA", 0, "SIM", "Independente", 0),
    ("APROVADA COM RESSALVAS", 0, "SIM", "Independente", 0),
    ("APROVADA INTERNAMENTE", 0, "NAO", "Controller-adversarial", 0),
    ("INCONCLUSIVA", 0, "NAO", "Pre-auditoria", 1),
    ("REPROVADA", 1, "NAO", "Independente", 0),
])
def test_valid_headers(verdict, blockers, merge, validity, limitations):
    assert module.validate(report(verdict, blockers=blockers, merge=merge,
                                  validity=validity, limitations=limitations)) == []


@pytest.mark.parametrize("bad", [
    "\n" + report(),
    "Auditoria\n" + report(),
    report().replace("# RESULTADO:", "RESULTADO:", 1),
    report().replace("# RESULTADO:", "## RESULTADO:", 1),
    report().replace("APROVADA` — achados", "REPROVADA` — achados", 1),
    report().replace("bloqueantes: `0`", "bloqueantes: `1`", 1),
    report("REPROVADA", blockers=0, merge="NAO"),
    report("REPROVADA", blockers=1, merge="SIM"),
    report("APROVADA INTERNAMENTE", merge="SIM", validity="Controller-adversarial"),
    report("APROVADA", validity="Pre-auditoria"),
    report().replace("> **Motivo determinante:** Evidencias e gates obrigatorios foram verificados.\n", ""),
    report().replace("**Validade:** Independente", "**Validade:** UNKNOWN"),
    report().replace("> **Libera merge/release:** SIM", "> **Libera merge/release:** TALVEZ"),
])
def test_reject_invalid_headers(bad):
    assert module.validate(bad), "invalid audit output must be rejected"


@pytest.mark.parametrize("case", [
    # Issue 399: the auditor cannot run the required offline gate, but no product defect is proved.
    report("INCONCLUSIVA", blockers=0, merge="NAO", risks=1, limitations=1),
    # A confirmed blocker takes precedence over an additional runtime-only limitation.
    report("REPROVADA", blockers=1, merge="NAO", limitations=1),
])
def test_issue_399_disjoint_diagnostics(case):
    assert module.validate(case) == []


@pytest.mark.parametrize("case", [
    report("INCONCLUSIVA", blockers=1, merge="NAO", limitations=1),
    report("INCONCLUSIVA", blockers=0, merge="NAO", limitations=0),
    report("REPROVADA", blockers=1, confirmed=0, merge="NAO", limitations=1),
    report("REPROVADA", blockers=1, confirmed=0, merge="NAO"),
    report("APROVADA", limitations=1),
    report("APROVADA COM RESSALVAS", limitations=1),
    report("APROVADA INTERNAMENTE", merge="NAO", validity="Controller-adversarial", limitations=1),
    report().replace("**Triagem:** bloqueadores comprovados: `0` | riscos inferidos: `0` | limitacoes do auditor: `0`\n", ""),
    report("INCONCLUSIVA", merge="NAO", limitations=1).replace("## Limitacoes exclusivas do auditor", "## Outro titulo"),
    report("APROVADA", risks=1).replace("## Riscos inferidos nao confirmados", "## Outro titulo"),
    report("REPROVADA", blockers=1, merge="NAO").replace("## Achados bloqueantes", "## Outro titulo"),
    # Conversation-only downgrade while retaining the original blockers/triage.
    report("REPROVADA", blockers=1, merge="NAO").replace("RESULTADO: REPROVADA", "RESULTADO: INCONCLUSIVA").replace("Conclusao:** `REPROVADA`", "Conclusao:** `INCONCLUSIVA`"),
])
def test_reject_triage_inconsistencies(case):
    assert module.validate(case)
