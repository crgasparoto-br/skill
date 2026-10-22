"""Regression tests for the audit report verdict and evidence triage."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "auditar-issue/scripts/validate_verdict_header.py"
spec = importlib.util.spec_from_file_location("verdict_header", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def blocker(identifier="A-001"):
    return (
        f"### [ALTO] {identifier} — Falha confirmada no candidato\n"
        "- **Requisitos afetados:** REQ-399-01\n"
        "- **Origem comprovada:** candidato\n"
        "- **Evidência:** services/workout.py:104 e teste de regressao reproduzivel no SHA fixo\n"
    )


def risk(identifier="RISK-001"):
    return (
        f"### {identifier} — Risco ainda nao confirmado\n"
        "- **Cenário hipotético:** falha em estado legado incomum\n"
        "- **Base da inferência:** trecho estatico nao exercitado pelo teste existente\n"
        "- **Grau de certeza:** baixo\n"
        "- **Prova discriminante pendente:** executar caso legado com fixture de regressao\n"
    )


def limitation(identifier="LIM-001"):
    return (
        f"### {identifier} — Checkout indisponivel somente para o auditor\n"
        "- **Recurso indisponível:** Git checkout local do commit imutavel\n"
        "- **Gate obrigatório afetado:** validate_audit_completeness.py com diff Git confiavel\n"
        "- **Tentativas e fallbacks:** clone DNS falhou; Git Bundle do CI nao foi disponibilizado\n"
        "- **Prova indisponível:** comparacao independente de base e HEAD por objeto Git\n"
    )


def report(verdict="APROVADA", summary=None, blockers=0, merge="SIM",
           validity="Independente", confirmed=None, risks=0, limitations=0,
           sections=None):
    confirmed = blockers if confirmed is None else confirmed
    if sections is None:
        sections = (
            ("## Achados bloqueantes\n" + "".join(blocker(f"A-{i+1:03}") for i in range(blockers))
             if blockers else "")
            + ("## Riscos inferidos nao confirmados\n"
               + "".join(risk(f"RISK-{i+1:03}") for i in range(risks))
               if risks else "")
            + ("## Limitacoes exclusivas do auditor\n"
               + "".join(limitation(f"LIM-{i+1:03}") for i in range(limitations))
               if limitations else "")
        )
    reason = (
        "Uma prova obrigatoria nao pode ser executada no ambiente do auditor."
        if verdict == "INCONCLUSIVA" else
        "Achado de codigo comprovado impede aprovacao." if verdict == "REPROVADA" else
        "Evidencias e gates obrigatorios foram verificados."
    )
    return (
        f"# RESULTADO: {verdict}\n\n"
        "> **Conclusao:** " + chr(96) + f"{summary or verdict}" + chr(96)
        + " — achados bloqueantes: " + chr(96) + f"{blockers}" + chr(96)
        + " — recomendacoes opcionais: " + chr(96) + "0" + chr(96) + "\n"
        f"> **Motivo determinante:** {reason}\n"
        f"> **Libera merge/release:** {merge}\n\n"
        f"**Validade:** {validity}\n"
        f"**Triagem:** bloqueadores comprovados: " + chr(96) + f"{confirmed}" + chr(96)
        + " | riscos inferidos: " + chr(96) + f"{risks}" + chr(96)
        + " | limitacoes do auditor: " + chr(96) + f"{limitations}" + chr(96)
        + f"\n\n## Evidencias\nCaso sintetico para verificar apenas a estrutura de prova.\n{sections}"
    )


@pytest.mark.parametrize("verdict,blockers,merge,validity,limitations", [
    ("APROVADA", 0, "SIM", "Independente", 0),
    ("APROVADA COM RESSALVAS", 0, "SIM", "Independente", 0),
    ("APROVADA INTERNAMENTE", 0, "NAO", "Controller-adversarial", 0),
    ("INCONCLUSIVA", 0, "NAO", "Pre-auditoria", 1),
    ("REPROVADA", 1, "NAO", "Independente", 0),
])
def test_valid_reports(verdict, blockers, merge, validity, limitations):
    text = report(verdict, blockers=blockers, merge=merge, validity=validity, limitations=limitations)
    assert module.validate(text) == []


@pytest.mark.parametrize("bad", [
    "\n" + report(),
    "Auditoria\n" + report(),
    report().replace("# RESULTADO:", "RESULTADO:", 1),
    report().replace("# RESULTADO:", "## RESULTADO:", 1),
    report().replace("APROVADA" + chr(96) + " — achados", "REPROVADA" + chr(96) + " — achados", 1),
    report().replace("bloqueantes: " + chr(96) + "0" + chr(96),
                     "bloqueantes: " + chr(96) + "1" + chr(96), 1),
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
    report("INCONCLUSIVA", merge="NAO", risks=1, limitations=1),
    report("REPROVADA", blockers=1, merge="NAO", limitations=1),
    report("APROVADA", risks=1),
])
def test_independent_categories_do_not_change_precedence(case):
    assert module.validate(case) == []


@pytest.mark.parametrize("case", [
    report("INCONCLUSIVA", blockers=1, merge="NAO", limitations=1),
    report("INCONCLUSIVA", merge="NAO"),
    report("REPROVADA", blockers=1, confirmed=0, merge="NAO", limitations=1),
    report("REPROVADA", blockers=1, confirmed=0, merge="NAO"),
    report("APROVADA", limitations=1),
    report("APROVADA COM RESSALVAS", limitations=1),
    report("APROVADA INTERNAMENTE", merge="NAO",
           validity="Controller-adversarial", limitations=1),
    report().replace("**Triagem:** bloqueadores comprovados:", "**Sem triagem:**", 1),
    report("INCONCLUSIVA", merge="NAO", limitations=1).replace(
        "## Limitacoes exclusivas do auditor", "## Outro titulo"),
    report("APROVADA", risks=1).replace("## Riscos inferidos nao confirmados", "## Outro titulo"),
    report("REPROVADA", blockers=1, merge="NAO").replace(
        "## Achados bloqueantes", "## Outro titulo"),
])
def test_reject_triage_inconsistencies(case):
    assert module.validate(case)


@pytest.mark.parametrize("case", [
    report("REPROVADA", blockers=1, merge="NAO", sections="## Achados bloqueantes\nTexto qualquer\n"),
    report("REPROVADA", blockers=2, merge="NAO", sections="## Achados bloqueantes\n" + blocker()),
    report("REPROVADA", blockers=2, merge="NAO",
           sections="## Achados bloqueantes\n" + blocker() + blocker()),
    report("REPROVADA", blockers=1, merge="NAO",
           sections="## Achados bloqueantes\n" + blocker().replace(
               "- **Evidência:** services/workout.py:104 e teste de regressao reproduzivel no SHA fixo\n", "")),
    report("REPROVADA", blockers=1, merge="NAO",
           sections="## Achados bloqueantes\n" + blocker().replace(
               "services/workout.py:104 e teste de regressao reproduzivel no SHA fixo", "[...]")),
    report("REPROVADA", blockers=1, merge="NAO",
           sections="## Achados bloqueantes\n" + blocker().replace("candidato\n", "auditor\n")),
    report("APROVADA", sections="## Achados bloqueantes\n" + blocker()),
    report("APROVADA", sections="## Riscos inferidos nao confirmados\n" + risk()),
    report("APROVADA", sections="## Limitacoes exclusivas do auditor\n" + limitation()),
    report("APROVADA", risks=1, sections="## Riscos inferidos nao confirmados\n" +
           risk().replace("- **Grau de certeza:** baixo\n", "")),
    report("INCONCLUSIVA", merge="NAO", limitations=1,
           sections="## Limitacoes exclusivas do auditor\n" +
           limitation().replace("- **Tentativas e fallbacks:** clone DNS falhou; Git Bundle do CI nao foi disponibilizado\n", "")),
    report("INCONCLUSIVA", merge="NAO", limitations=1,
           sections="## Limitacoes exclusivas do auditor\n" +
           limitation().replace("- **Gate obrigatório afetado:** validate_audit_completeness.py com diff Git confiavel\n", "")),
    report("REPROVADA", blockers=1, merge="NAO",
           sections="## Achados bloqueantes\n" + chr(96) * 3 + "\n" + blocker() + chr(96) * 3),
])
def test_reject_fake_or_incomplete_body_records(case):
    assert module.validate(case)


def revision(previous, current, with_proof=True):
    fragment = (
        "\n## Retificacao do parecer\n"
        "- **Veredito anterior:** REPROVADA\n"
        "- **Veredito atual:** INCONCLUSIVA\n"
        "- **Motivo da retificacao:** analise externa eliminou o achado anterior\n"
        "- **Nova evidencia:** services/workout.py:104; resultado reproduzido no mesmo SHA\n"
        "- **HEAD auditado:** " + "a" * 40 + "\n"
    )
    if with_proof:
        fragment += "- **Prova de reclassificacao A-001:** services/workout.py:104; leitura confirmou caminho inacessivel\n"
    return module.validate_revision(current + fragment, previous)


def test_revision_demands_documented_reclassification():
    old = report("REPROVADA", blockers=1, merge="NAO", limitations=1)
    new = report("INCONCLUSIVA", merge="NAO", limitations=1)
    assert module.validate_revision(new, old)  # header changes alone are not enough
    assert revision(old, new, with_proof=False)
    assert revision(old, new, with_proof=True) == []


def test_same_verdict_and_records_do_not_require_revision_section():
    old = report("INCONCLUSIVA", merge="NAO", limitations=1)
    assert module.validate_revision(old, old) == []


@pytest.mark.parametrize("case", [
    report("APROVADA", sections="## Achados bloqueantes\n"),
    report("APROVADA", sections="## Riscos inferidos nao confirmados\n"),
    report("APROVADA", sections="## Limitacoes exclusivas do auditor\n"),
    report("REPROVADA", blockers=1, merge="NAO",
           sections="## Achados bloqueantes\n" + blocker().replace(
               "services/workout.py:104 e teste de regressao reproduzivel no SHA fixo",
               "Nenhuma evidencia")),
    report("REPROVADA", blockers=1, merge="NAO",
           sections="## Achados bloqueantes\n" + blocker().replace(
               "services/workout.py:104 e teste de regressao reproduzivel no SHA fixo",
               "prova de codigo sem localizacao verificavel")),
    report("APROVADA", risks=1, sections="## Riscos inferidos nao confirmados\n"
           + risk().replace("trecho estatico nao exercitado pelo teste existente", "texto")),
    report("INCONCLUSIVA", merge="NAO", limitations=1,
           sections="## Limitacoes exclusivas do auditor\n"
           + limitation().replace(
               "clone DNS falhou; Git Bundle do CI nao foi disponibilizado", "tentamos resolver")),
])
def test_reject_empty_sections_and_non_contextual_evidence(case):
    assert module.validate(case)


def test_zero_count_can_explicitly_say_none():
    assert module.validate(report("APROVADA", sections="## Achados bloqueantes\nNenhum\n")) == []


def test_revision_demands_proof_even_when_blocker_id_and_count_are_unchanged():
    old = report("REPROVADA", blockers=1, merge="NAO")
    new = old.replace("services/workout.py:104", "services/workout.py:105")
    assert module.validate(new) == []
    assert module.validate_revision(new, old)
    assert module.validate_revision(new + "\n## Retificacao do parecer\n", old)


def test_revision_checks_current_body_and_other_category_reclassifications():
    old = report("INCONCLUSIVA", merge="NAO", risks=1, limitations=1)
    new = old.replace("RISK-001", "RISK-002")
    assert module.validate(new) == []
    assert module.validate_revision(new, old)
    invalid = old.replace("Git checkout local do commit imutavel", "TODO")
    assert module.validate_revision(invalid, old)


def test_revision_requires_previous_file_on_cli(tmp_path):
    import subprocess
    import sys

    old = report("REPROVADA", blockers=1, merge="NAO", limitations=1)
    new = report("INCONCLUSIVA", merge="NAO", limitations=1)
    assert revision(old, new, with_proof=True) == []
    path = tmp_path / "revised.md"
    path.write_text(new + "\n## Retificacao do parecer\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), str(path)],
                          capture_output=True, text=True, check=False)
    assert proc.returncode != 0
    assert "--previous" in proc.stdout


@pytest.mark.parametrize("hidden", [
    blocker(), risk(), limitation(),
    "## Achados bloqueantes\nNenhum\n## Outra secao\n" + blocker(),
])
def test_stray_structured_records_never_hide_under_zero_counts(hidden):
    text = report("APROVADA", sections="## Evidencia complementar\n" + hidden)
    assert module.validate(text), "every triage item must be in its own counted section"


def test_misplaced_extra_record_cannot_hide_behind_correct_blocker_count():
    sections = ("## Achados bloqueantes\n" + blocker()
                + "## Evidencias adicionais\n" + blocker("A-002"))
    text = report("REPROVADA", blockers=1, merge="NAO", sections=sections)
    assert module.validate(text)


def test_duplicate_id_outside_its_section_is_rejected():
    sections = ("## Achados bloqueantes\n" + blocker()
                + "## Evidencias adicionais\n" + blocker())
    text = report("REPROVADA", blockers=1, merge="NAO", sections=sections)
    assert module.validate(text)


def test_fenced_example_outside_sections_does_not_count_as_a_finding():
    text = report("APROVADA", sections="## Referencias\n" + chr(96)*3
                  + "\n" + blocker() + chr(96)*3 + "\n")
    assert module.validate(text) == []


def test_same_id_title_change_requires_revision_and_individual_proof():
    old = report("REPROVADA", blockers=1, merge="NAO")
    new = old.replace("Falha confirmada no candidato", "Falha de outra natureza")
    assert module.validate(new) == []
    assert module.validate_revision(new, old)
    rectification = (
        "\n## Retificacao do parecer\n"
        "- **Veredito anterior:** REPROVADA\n"
        "- **Veredito atual:** REPROVADA\n"
        "- **Motivo da retificacao:** o achado foi reavaliado sob novo contexto\n"
        "- **Nova evidencia:** services/workout.py:104 demonstra o contexto adicional\n"
        "- **HEAD auditado:** " + "a" * 40 + "\n"
    )
    assert module.validate_revision(new + rectification, old)
    assert module.validate_revision(
        new + rectification
        + "- **Prova de reclassificacao A-001:** services/workout.py:104 e teste discriminante do novo titulo\n",
        old,
    ) == []


def test_reason_only_change_also_requires_revision():
    old = report("APROVADA")
    new = old.replace(
        "Evidencias e gates obrigatorios foram verificados.",
        "Nova analise examinou evidencias adicionais sobre a mesma entrega.",
    )
    assert module.validate(new) == []
    assert module.validate_revision(new, old)


def test_explicit_revision_flag_fails_closed_without_previous(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "report.md"
    path.write_text(report("APROVADA"), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(path), "--revision"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode != 0
    assert "--previous" in proc.stdout


@pytest.mark.parametrize("indent", [" ", "  ", "   "])
@pytest.mark.parametrize("identifier,record", [
    ("A-001", blocker()),
    ("RISK-001", risk()),
    ("LIM-001", limitation()),
])
def test_indented_visible_records_cannot_hide_outside_canonical_sections(indent, identifier, record):
    # CommonMark permits up to three spaces before an ATX heading.
    text = report("APROVADA", sections="## Evidencias complementares\\n" + indent + record)
    errors = module.validate(text)
    assert errors
    assert any(identifier in error and "fora da secao" in error for error in errors)


@pytest.mark.parametrize("separator", ["  ", "\\t"])
def test_atx_whitespace_and_closing_hashes_do_not_hide_blockers(separator):
    record = blocker().replace("### [ALTO] ", "###" + separator + "[ALTO] ", 1)
    record = record.replace("Falha confirmada no candidato\\n", "Falha confirmada no candidato ###\\n", 1)
    text = report("APROVADA", sections="## Evidencias complementares\\n" + record)
    errors = module.validate(text)
    assert any("A-001" in error and "fora da secao" in error for error in errors)


@pytest.mark.parametrize("indent", [" ", "  ", "   "])
def test_indented_canonical_section_and_record_are_counted(indent):
    sections = indent + "## Achados bloqueantes\\n" + indent + blocker()
    text = report("REPROVADA", blockers=1, merge="NAO", sections=sections)
    assert module.validate(text) == []


def test_tab_separator_in_canonical_heading_does_not_hide_record():
    text = report("REPROVADA", blockers=1, merge="NAO",
                  sections="##\\tAchados bloqueantes\\n" + blocker().replace("### ", "###\\t", 1))
    assert module.validate(text) == []


def test_four_space_indented_code_remains_inert():
    text = report("APROVADA", sections="## Referencias\\n    ### A-001 — exemplo de codigo\\n")
    assert module.validate(text) == []


def test_indented_revision_section_is_verified_against_previous(tmp_path):
    import subprocess
    import sys

    old = report("REPROVADA", blockers=1, merge="NAO", limitations=1)
    new = report("INCONCLUSIVA", merge="NAO", limitations=1)
    current = new + (
        "\\n  ## Retificacao do parecer\\n"
        "- **Veredito anterior:** REPROVADA\\n"
        "- **Veredito atual:** INCONCLUSIVA\\n"
        "- **Motivo da retificacao:** teste externo demonstrou a causa diferente\\n"
        "- **Nova evidencia:** services/workout.py:104; evidencia adicional reproduzida\\n"
        "- **HEAD auditado:** " + "a" * 40 + "\\n"
        "- **Prova de reclassificacao A-001:** services/workout.py:104; leitura confirmou origem distinta\\n"
    )
    assert module.validate_revision(current, old) == []
    path = tmp_path / "changed.md"
    path.write_text(current, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), str(path)],
                          capture_output=True, text=True, check=False)
    assert proc.returncode != 0
    assert "--previous" in proc.stdout
