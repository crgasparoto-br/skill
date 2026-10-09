"""Regression checks for audit verdict headers."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "auditar-issue/scripts/validate_verdict_header.py"
spec = importlib.util.spec_from_file_location("verdict_header", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def report(verdict="APROVADA", summary=None, blockers=0, merge="SIM", validity="Independente"):
    return (
        f"# RESULTADO: {verdict}\n\n"
        f"> **Conclusao:** `{summary or verdict}` — achados bloqueantes: `{blockers}` — recomendacoes opcionais: `0`\n"
        "> **Motivo determinante:** Evidencias e gates obrigatorios foram verificados.\n"
        f"> **Libera merge/release:** {merge}\n\n"
        f"**Validade:** {validity}\n\n## Evidencias\nOK\n"
    )


@pytest.mark.parametrize("verdict,blockers,merge,validity", [
    ("APROVADA", 0, "SIM", "Independente"),
    ("APROVADA COM RESSALVAS", 0, "SIM", "Independente"),
    ("APROVADA INTERNAMENTE", 0, "NAO", "Controller-adversarial"),
    ("INCONCLUSIVA", 0, "NAO", "Pre-auditoria"),
    ("REPROVADA", 1, "NAO", "Independente"),
])
def test_valid_headers(verdict, blockers, merge, validity):
    assert module.validate(report(verdict, blockers=blockers, merge=merge, validity=validity)) == []


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
