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
    text = report("APROVADA", sections="## Evidencias complementares\n" + indent + record)
    errors = module.validate(text)
    assert errors
    assert any(identifier in error and "fora da secao" in error for error in errors)


@pytest.mark.parametrize("separator", ["  ", "\t"])
def test_atx_whitespace_and_closing_hashes_do_not_hide_blockers(separator):
    record = blocker().replace("### [ALTO] ", "###" + separator + "[ALTO] ", 1)
    record = record.replace("Falha confirmada no candidato\n", "Falha confirmada no candidato ###\n", 1)
    text = report("APROVADA", sections="## Evidencias complementares\n" + record)
    errors = module.validate(text)
    assert any("A-001" in error and "fora da secao" in error for error in errors)


@pytest.mark.parametrize("indent", [" ", "  ", "   "])
def test_indented_canonical_section_and_record_are_counted(indent):
    sections = indent + "## Achados bloqueantes\n" + indent + blocker()
    text = report("REPROVADA", blockers=1, merge="NAO", sections=sections)
    assert module.validate(text) == []


def test_tab_separator_in_canonical_heading_does_not_hide_record():
    text = report("REPROVADA", blockers=1, merge="NAO",
                  sections="##\tAchados bloqueantes\n" + blocker().replace("### ", "###\t", 1))
    assert module.validate(text) == []


def test_four_space_indented_code_remains_inert():
    text = report("APROVADA", sections="## Referencias\n    ### A-001 — exemplo de codigo\n")
    assert module.validate(text) == []


def test_indented_revision_section_is_verified_against_previous(tmp_path):
    import subprocess
    import sys

    old = report("REPROVADA", blockers=1, merge="NAO", limitations=1)
    new = report("INCONCLUSIVA", merge="NAO", limitations=1)
    # A top-level H1 closes the preceding list. Without it the indented H2
    # would remain inside the last list item and cannot be canonical.
    current = new + (
        "\n# Encerramento do bloco anterior\n\n  ## Retificacao do parecer\n"
        "- **Veredito anterior:** REPROVADA\n"
        "- **Veredito atual:** INCONCLUSIVA\n"
        "- **Motivo da retificacao:** teste externo demonstrou a causa diferente\n"
        "- **Nova evidencia:** services/workout.py:104; evidencia adicional reproduzida\n"
        "- **HEAD auditado:** " + "a" * 40 + "\n"
        "- **Prova de reclassificacao A-001:** services/workout.py:104; leitura confirmou origem distinta\n"
    )
    assert module.validate_revision(current, old) == []
    path = tmp_path / "changed.md"
    path.write_text(current, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), str(path)],
                          capture_output=True, text=True, check=False)
    assert proc.returncode != 0
    assert "--previous" in proc.stdout


@pytest.mark.parametrize("container", [
    "> ", "- ", "* ", "+ ", "1. ", "> - ",
])
def test_nested_visible_records_do_not_escape_the_count(container):
    text = report("APROVADA", sections="## Evidencia complementar\n" + container + blocker())
    errors = module.validate(text)
    assert any("A-001" in error and "aninhado" in error for error in errors)


def test_indented_code_fence_cannot_hide_real_heading():
    # A fence indented four spaces is a code line, not a Markdown fence.
    fence = chr(96) * 3
    text = report("APROVADA", sections=(
        "## Evidencia complementar\n"
        "    " + fence + "\n"
        "### A-001 — Registro visivel posterior\n"
        "    " + fence + "\n"
    ))
    errors = module.validate(text)
    assert any("A-001" in error and "fora da secao" in error for error in errors)


def test_nested_record_in_correct_section_is_still_invalid():
    text = report("APROVADA", sections="## Achados bloqueantes\n> " + blocker())
    errors = module.validate(text)
    assert any("A-001" in error and "aninhado" in error for error in errors)


def test_real_fenced_code_keeps_embedded_indented_records_inert():
    fence = chr(96) * 3
    text = report("APROVADA", sections=(
        "## Referencias\n"
        "  " + fence + "markdown\n"
        "   ### A-001 — Codigo, nao achado\n"
        "  " + fence + "\n"
    ))
    assert module.validate(text) == []


def test_h1_closes_canonical_evidence_section():
    text = report(
        "REPROVADA", blockers=1, merge="NAO",
        sections="## Achados bloqueantes\n# Contexto diferente\n" + blocker(),
    )
    errors = module.validate(text)
    assert any("A-001" in error and "fora da secao" in error for error in errors)
    assert any("contagem declarada 1, itens verificaveis 0" in error for error in errors)


def test_h1_excludes_extra_record_after_valid_blocker():
    text = report(
        "REPROVADA", blockers=1, merge="NAO",
        sections="## Achados bloqueantes\n" + blocker()
        + "# Novo capitulo\n" + blocker("A-002"),
    )
    errors = module.validate(text)
    assert any("A-002" in error and "fora da secao" in error for error in errors)


@pytest.mark.parametrize("container,continuation", [
    ("> ", "> "),
    ("> - ", ">   "),
    ("- ", "  "),
])
def test_fenced_examples_inside_markdown_containers_are_inert(container, continuation):
    fence = chr(96) * 3
    sections = (
        "## Achados bloqueantes\n" + blocker()
        + container + fence + "markdown\n"
        + continuation + "### A-002 — Codigo de exemplo, nao um achado\n"
        + continuation + fence + "\n"
    )
    assert module.validate(report(
        "REPROVADA", blockers=1, merge="NAO", sections=sections,
    )) == []


def test_nested_list_continuation_is_not_a_canonical_finding():
    text = report(
        "APROVADA",
        sections="## Evidencia adicional\n- Registro de exemplo\n"
        "  ### A-001 — Finding aninhado e indevido\n",
    )
    assert any("A-001" in error and "aninhado" in error for error in module.validate(text))


@pytest.mark.parametrize("unanchored", [
    "pytest nao foi executado, sem artefato verificavel para o achado",
    "python -m pytest foi somente mencionado, sem parametros nem saida do teste",
    "git show foi mencionado, sem commit ou arquivo especificado como prova",
    "CI run citado sem numero, URL, arquivo ou resultado reproduzivel",
    "pytest -q tests/test_workout.py sem execucao ou resultado registrado",
])
def test_generic_tool_mentions_do_not_qualify_as_evidence(unanchored):
    entry = blocker().replace(
        "services/workout.py:104 e teste de regressao reproduzivel no SHA fixo",
        unanchored,
    )
    text = report(
        "REPROVADA", blockers=1, merge="NAO",
        sections="## Achados bloqueantes\n" + entry,
    )
    assert any("evidencia sem artefato" in error for error in module.validate(text))


@pytest.mark.parametrize("anchored", [
    "services/workout.py:104 demonstra caminho incorreto no commit auditado",
    "CI run #39802655582 registra teste falho no SHA completo da entrega",
    "pytest -q tests/test_workout.py -> 2 failed no checkout auditado",
])
def test_specific_reproducible_anchors_remain_valid(anchored):
    entry = blocker().replace(
        "services/workout.py:104 e teste de regressao reproduzivel no SHA fixo",
        anchored,
    )
    text = report(
        "REPROVADA", blockers=1, merge="NAO",
        sections="## Achados bloqueantes\n" + entry,
    )
    assert module.validate(text) == []


@pytest.mark.parametrize("container", ["> ", "- "])
@pytest.mark.parametrize("category", ["A", "RISK", "LIM"])
def test_escaped_container_fence_cannot_hide_visible_triage_item(container, category):
    # An uncontained ATX heading terminates the quoted/list fenced example.
    record = {"A": blocker(), "RISK": risk(), "LIM": limitation()}[category]
    text = report(
        "APROVADA",
        sections="## Evidencias complementares\n" + container + chr(96)*3 + "markdown\n" + record,
    )
    errors = module.validate(text)
    assert errors
    assert any(category + "-001" in error and "fora da secao" in error for error in errors)


@pytest.mark.parametrize("category", ["A", "RISK", "LIM"])
def test_blank_line_does_not_promote_list_continuation_to_canonical_item(category):
    record = {"A": blocker(), "RISK": risk(), "LIM": limitation()}[category]
    section = {
        "A": "## Achados bloqueantes",
        "RISK": "## Riscos inferidos nao confirmados",
        "LIM": "## Limitacoes exclusivas do auditor",
    }[category]
    # CommonMark keeps the indented heading inside the list, even after a blank.
    sections = section + "\n- Item de exemplo\n\n  " + record
    text = report(
        "REPROVADA" if category == "A" else "INCONCLUSIVA" if category == "LIM" else "APROVADA",
        blockers=1 if category == "A" else 0,
        merge="NAO" if category != "RISK" else "SIM",
        risks=1 if category == "RISK" else 0,
        limitations=1 if category == "LIM" else 0,
        sections=sections,
    )
    errors = module.validate(text)
    assert any(category + "-001" in error and "aninhado" in error for error in errors)
    assert any("itens verificaveis 0" in error for error in errors)


@pytest.mark.parametrize("container,continuation", [
    ("> ", "> "),
    ("- ", "  "),
    ("> - ", ">   "),
])
def test_nested_fence_remains_inert_in_its_own_container(container, continuation):
    text = report("APROVADA", sections=(
        "## Exemplos\n" + container + chr(96)*3 + "markdown\n"
        + continuation + "### A-001 — texto apenas ilustrativo\n"
        + continuation + chr(96)*3 + "\n"
    ))
    assert module.validate(text) == []


def test_html_comment_is_inert_and_following_real_heading_is_visible():
    inert = report("APROVADA", sections=(
        "## Exemplos\n<!--\n" + blocker() + "-->\n"
    ))
    assert module.validate(inert) == []
    active = report("APROVADA", sections=(
        "## Exemplos\n<!--\n" + blocker() + "-->\n" + blocker()
    ))
    assert any("A-001" in error and "fora da secao" in error for error in module.validate(active))


def test_short_or_generic_revision_reason_is_not_substantiation():
    old = report("REPROVADA", blockers=1, merge="NAO", limitations=1)
    new = report("INCONCLUSIVA", merge="NAO", limitations=1)
    fragment = (
        "\n## Retificacao do parecer\n"
        "- **Veredito anterior:** REPROVADA\n"
        "- **Veredito atual:** INCONCLUSIVA\n"
        "- **Motivo da retificacao:** ok\n"
        "- **Nova evidencia:** services/workout.py:104; teste discriminante reproduzido\n"
        "- **HEAD auditado:** " + "a" * 40 + "\n"
        "- **Prova de reclassificacao A-001:** services/workout.py:104; reanalise documentou a origem\n"
    )
    errors = module.validate_revision(new + fragment, old)
    assert any("motivo sem fundamentacao contextual" in error for error in errors)
    context = fragment.replace(
        "- **Motivo da retificacao:** ok\n",
        "- **Motivo da retificacao:** novo controle demonstrou que o achado nao pertence ao candidato\n",
    )
    assert module.validate_revision(new + context, old) == []


def test_list_nested_section_cannot_authorize_outside_blocker():
    # H2 is inside the list; H3 is a real heading outside that list.
    text = report("REPROVADA", blockers=1, merge="NAO", sections=(
        "## Exemplos\n- agrupamento\n\n"
        "  ## Achados bloqueantes\n" + blocker()
    ))
    errors = module.validate(text)
    assert any("A-001" in error and "fora da secao" in error for error in errors)
    assert any("contagem declarada 1, itens verificaveis 0" in error for error in errors)


def test_list_nested_h1_does_not_close_its_outer_canonical_section():
    text = report("REPROVADA", blockers=1, merge="NAO", sections=(
        "## Achados bloqueantes\n- agrupamento\n\n"
        "  # Titulo dentro da lista\n" + blocker()
    ))
    assert module.validate(text) == []


@pytest.mark.parametrize("container,continuation", [
    ("> ", "> "),
    ("- ", "  "),
])
def test_html_comment_stops_at_the_container_boundary(container, continuation):
    hidden = report("APROVADA", sections=(
        "## Exemplos\n" + container + "<!--\n"
        + continuation + blocker() + continuation + "-->\n"
    ))
    assert module.validate(hidden) == []
    exposed = report("APROVADA", sections=(
        "## Exemplos\n" + container + "<!--\n" + blocker()
    ))
    assert any("A-001" in error and "fora da secao" in error for error in module.validate(exposed))

@pytest.mark.parametrize("item", [
    "- A-001 — Bloqueador fora da secao canonica\n",
    "* RISK-001 — Risco ainda nao comprovado\n",
    "1. LIM-001 — Limitacao exclusiva do auditor\n",
    "> - A-001 — Bloqueador aninhado em citacao\n",
    "- - RISK-001 — Risco em sublista visivel\n",
    "A-001 — Registro em paragrafo simples\n",
    "- **LIM-001** — Registro com identificador em negrito\n",
])
def test_issue110_plain_visible_records_rejected_even_when_declared_zero(item):
    errors = module.validate(report("APROVADA", sections="## Evidencias extras\n" + item))
    assert any("formato nao canonico" in error for error in errors)


@pytest.mark.parametrize("inert", [
    "- Consulte A-001 na revisao anterior\n",
    "- **Prova de reclassificacao A-001:** ver arquivo.py:123\n",
    "- `A-001 — exemplo inline`\n",
    "    - A-001 — trecho indentado como codigo\n",
    "```markdown\n- A-001 — exemplo cercado\n```\n",
    "<pre>\n- A-001 — exemplo HTML\n</pre>\n",
])
def test_issue110_plain_id_references_and_inert_examples_not_findings(inert):
    assert module.validate(report("APROVADA", sections="## Exemplos\n" + inert)) == []


def test_issue110_plain_list_extra_record_rejected_with_correct_count():
    sections = ("## Achados bloqueantes\n" + blocker()
                + "## Evidencias complementares\n- A-002 — Achado extra nao contabilizado\n")
    errors = module.validate(report("REPROVADA", blockers=1, merge="NAO", sections=sections))
    assert any("A-002" in error and "formato nao canonico" in error for error in errors)


@pytest.mark.parametrize("item", [
    "#### A-001 — Bloqueador oculto sob H4\n",
    "##### RISK-001 — Risco oculto sob H5\n",
    "###### LIM-001 — Limitacao oculta sob H6\n",
    "- **A-001 — Bloqueador oculto em lista**\n",
    "1. **RISK-001 — Risco oculto em lista numerada**\n",
    "**LIM-001 — Limitacao oculta em negrito**\n",
])
def test_issue110_visible_noncanonical_records_never_escape_zero_count(item):
    errors = module.validate(report("APROVADA", sections="## Evidencia adicional\n" + item))
    assert errors
    assert any("formato nao canonico" in error for error in errors)


@pytest.mark.parametrize("tag", ["pre", "script", "style", "textarea"])
def test_issue110_raw_html_headings_are_not_a_confirmed_blocker(tag):
    example = f"<{tag}>\n" + blocker() + f"</{tag}>\n"
    text = report("REPROVADA", blockers=1, merge="NAO",
                  sections="## Achados bloqueantes\n" + example)
    assert any("itens verificaveis 0" in error for error in module.validate(text))
    assert module.validate(report("APROVADA", sections="## Exemplos\n" + example)) == []


def test_issue110_raw_html_container_does_not_hide_following_real_finding():
    text = report("APROVADA", sections="## Exemplos\n<pre>\n"
                  + blocker() + "</pre>\n" + blocker())
    assert any("A-001" in error and "fora da secao" in error
               for error in module.validate(text))


def test_issue110_second_revision_preserves_historical_proofs_and_hash():
    import hashlib

    original = report("REPROVADA", blockers=1, merge="NAO", limitations=1)
    no_blocker = report("INCONCLUSIVA", merge="NAO", limitations=1)
    proof = "services/workout.py:104; leitura independente demonstrou causa externa ao candidato"
    first = no_blocker + (
        "\n## Retificacao do parecer\n"
        "- **Veredito anterior:** REPROVADA\n"
        "- **Veredito atual:** INCONCLUSIVA\n"
        "- **Motivo da retificacao:** nova execucao demonstrou que a falha nao esta no candidato\n"
        "- **Nova evidencia:** services/workout.py:104; resultado reproduzido no SHA imutavel\n"
        "- **HEAD auditado:** " + "a" * 40 + "\n"
        "- **Prova de reclassificacao A-001:** " + proof + "\n"
    )
    assert module.validate_revision(first, original) == []

    digest = hashlib.sha256(first.encode("utf-8")).hexdigest()
    second = no_blocker + (
        "\n## Retificacao do parecer\n"
        "- **Veredito anterior:** INCONCLUSIVA\n"
        "- **Veredito atual:** INCONCLUSIVA\n"
        "- **Motivo da retificacao:** revisao de contexto apos verificacao independente do gate\n"
        "- **Nova evidencia:** services/workout.py:104; exame complementar do mesmo SHA\n"
        "- **HEAD auditado:** " + "a" * 40 + "\n"
        "- **Prova de reclassificacao A-001:** " + proof + "\n"
        "- **SHA-256 do parecer anterior:** " + digest + "\n"
    )
    assert module.validate_revision(second, first) == []
    assert any("historico de A-001 perdido" in error for error in
               module.validate_revision(second.replace(
                   "- **Prova de reclassificacao A-001:** " + proof + "\n", ""), first))
    assert any("historico de A-001 perdido" in error for error in
               module.validate_revision(second.replace(proof, proof + " adulterado"), first))
    assert any("SHA-256 do parecer anterior" in error for error in
               module.validate_revision(second.replace(digest, "0" * 64), first))
    assert any("SHA-256 do parecer anterior" in error for error in
               module.validate_revision(second.replace(
                   "- **SHA-256 do parecer anterior:** " + digest + "\n", ""), first))


@pytest.mark.parametrize("identifier,entry", [
    ("A-001", blocker()),
    ("RISK-001", risk()),
    ("LIM-001", limitation()),
])
@pytest.mark.parametrize("emphasis", ["**", "*", "__", "_", chr(96)])
@pytest.mark.parametrize("prefix", ["### ", "#### ", "- ", "> ### ", "1. "])
def test_issue110_styled_visible_identifiers_cannot_escape_triage(identifier, entry, emphasis, prefix):
    first_line = entry.splitlines()[0]
    first_line = first_line.replace(identifier, emphasis + identifier + emphasis)
    first_line = first_line.replace("### ", prefix, 1)
    errors = module.validate(report("APROVADA", sections="## Evidencias extras\n" + first_line + "\n"))
    assert any(identifier in error for error in errors), (first_line, errors)


@pytest.mark.parametrize("tag", [
    "div", "section", "article", "table", "blockquote", "ul",
    "main", "footer", "aside", "figure", "form", "details",
])
@pytest.mark.parametrize("kind,entry,section,verdict,counts", [
    ("A", blocker(), "## Achados bloqueantes", "REPROVADA", (1, 0, 0)),
    ("RISK", risk(), "## Riscos inferidos nao confirmados", "APROVADA", (0, 1, 0)),
    ("LIM", limitation(), "## Limitacoes exclusivas do auditor", "INCONCLUSIVA", (0, 0, 1)),
])
def test_issue110_commonmark_type6_html_does_not_supply_evidence(
    tag, kind, entry, section, verdict, counts,
):
    html = f"<{tag}>\n{entry}</{tag}>\n"
    assert module.validate(report("APROVADA", sections="## Exemplos\n" + html)) == []
    declared = report(
        verdict, blockers=counts[0], risks=counts[1], limitations=counts[2],
        merge="SIM" if verdict == "APROVADA" else "NAO",
        sections=section + "\n" + html,
    )
    assert any("itens verificaveis 0" in error for error in module.validate(declared))


def test_issue110_raw_html_type6_closes_on_blank_line_not_closing_tag():
    content = (
        "## Evidencia adicional\n<div>\n### A-001 — exemplo em HTML\n"
        "</div>\n### A-002 — ainda dentro de bloco HTML\n"
        "\n### A-003 — registro externo real\n"
    )
    errors = module.validate(report("APROVADA", sections=content))
    assert any("A-003" in error and "fora da secao" in error for error in errors)
    assert all("A-001" not in error and "A-002" not in error for error in errors)


def test_issue110_real_record_after_raw_html_blank_line_still_counts():
    content = (
        "## Achados bloqueantes\n<div>\n### A-002 — exemplo HTML inerte\n"
        "</div>\n\n" + blocker()
    )
    assert module.validate(report("REPROVADA", blockers=1, merge="NAO", sections=content)) == []


@pytest.mark.parametrize("reference", [
    "- Consulte A-001 na revisao anterior\n",
    "- **Prova de reclassificacao A-001:** arquivo.py:123\n",
    "- "+chr(96)+"A-001 — exemplo inline"+chr(96)+"\n",
    "### Exemplo mencionando RISK-001 sem declarar item\n",
])
def test_issue110_styled_ids_are_not_inferred_from_incidental_references(reference):
    assert module.validate(report("APROVADA", sections="## Exemplos\n" + reference)) == []


@pytest.mark.parametrize("record_id", ["A-123", "RISK-123", "LIM-123"])
@pytest.mark.parametrize("nested", [
    "- Lista de exemplos\n    - {record_id} — item presente no corpo\n",
    "- Lista de exemplos\n      - {record_id} — item presente no corpo\n",
    "- Lista de exemplos\n  - Sublista\n    - **{record_id}** — item presente no corpo\n",
    "1. Lista numerada\n    1. {record_id} — item presente no corpo\n",
])
def test_nested_list_records_must_not_hide_under_zero_triage(record_id, nested):
    text = report("APROVADA", sections="## Evidencias adicionais\n"
                  + nested.format(record_id=record_id))
    assert module.validate(text), "visible nested evidence must not evade reconciliation"


@pytest.mark.parametrize("tag", [
    "<audit-example>",
    '<audit-example data-mode="sample">',
    "<audit-example />",
    "</audit-example>",
])
def test_custom_type7_html_is_inert_until_blank_line(tag):
    text = report("APROVADA", sections=(
        "## Referencias\n" + tag
        + "\n### A-123 — exemplo inerte em bloco HTML\n"
        + "</audit-example>\n"
    ))
    assert module.validate(text) == []


def test_type7_html_ends_at_blank_line_and_following_finding_is_visible():
    text = report("APROVADA", sections=(
        "## Referencias\n"
        "<audit-example>\n"
        "### A-123 — ainda inerte no HTML\n\n"
        "### A-124 — achado visivel depois da linha vazia\n"
    ))
    assert module.validate(text)


def test_inline_html_with_trailing_content_does_not_hide_visible_records():
    text = report("APROVADA", sections=(
        "## Referencias\n"
        "<audit-example>texto inline\n"
        "### A-123 — achado que continua visivel\n"
    ))
    assert module.validate(text)


@pytest.mark.parametrize("code_example", [
    "    - A-123 — codigo indentado no nivel raiz\n",
    "- Item da lista\n\n      - A-123 — codigo indentado dentro da lista\n",
    "- Item da lista\n  - Item interno\n\n        - RISK-123 — codigo indentado dentro da sublista\n",
])
def test_indented_code_example_is_not_misclassified_as_evidence(code_example):
    assert module.validate(report("APROVADA", sections=(
        "## Exemplos inertes\n" + code_example
    ))) == []



@pytest.mark.parametrize("identifier", ["A-901", "RISK-901", "LIM-901"])
@pytest.mark.parametrize("tag", [
    "<audit-example>",
    '<audit-example data-mode="sample">',
    "<audit-example />",
    "</audit-example>",
])
def test_type7_html_cannot_interrupt_an_existing_paragraph(identifier, tag):
    # CommonMark HTML block type 7 cannot interrupt a paragraph.
    # The following H3 is a real heading and must be rejected.
    sections = (
        "## Exemplos\n"
        "Paragrafo anterior permanece aberto\n"
        + tag + "\n"
        + f"### {identifier} — registro real fora da triagem\n"
    )
    errors = module.validate(report("APROVADA", sections=sections))
    assert any(identifier in error for error in errors), (tag, identifier, errors)


@pytest.mark.parametrize("tag", ["<audit-example>", "<audit-example />"])
def test_type7_html_after_blank_line_remains_inert(tag):
    sections = (
        "## Exemplos\n"
        "Paragrafo terminado\n\n"
        + tag + "\n"
        "### A-901 — exemplo dentro de HTML raw\n"
    )
    assert module.validate(report("APROVADA", sections=sections)) == []


@pytest.mark.parametrize("tag", ["<div>", "<pre>"])
def test_type1_and_type6_html_may_interrupt_paragraphs(tag):
    sections = (
        "## Exemplos\n"
        "Texto de contexto antes do bloco\n"
        + tag + "\n"
        "### A-901 — exemplo dentro de HTML raw\n"
    )
    assert module.validate(report("APROVADA", sections=sections)) == []


@pytest.mark.parametrize("identifier", ["A-901", "RISK-901", "LIM-901"])
@pytest.mark.parametrize("indent", ["    ", "      ", ">     "])
@pytest.mark.parametrize("lead", ["", "Paragrafo que nao declara um achado\n\n"])
def test_indented_code_is_inert_even_when_identifier_starts_without_list_marker(
    identifier, indent, lead,
):
    sections = "## Exemplos\n" + lead + indent + identifier + " — exemplo de codigo\n"
    assert module.validate(report("APROVADA", sections=sections)) == []


@pytest.mark.parametrize("identifier", ["A-901", "RISK-901", "LIM-901"])
def test_three_space_plain_record_is_visible_and_still_rejected(identifier):
    sections = "## Exemplos\n   " + identifier + " — registro real\n"
    errors = module.validate(report("APROVADA", sections=sections))
    assert any(identifier in error for error in errors), errors

@pytest.mark.parametrize("identifier", ["A-901", "RISK-901", "LIM-901"])
def test_type7_html_after_indented_paragraph_continuation_stays_visible(identifier):
    # Four-space indentation cannot interrupt an existing CommonMark paragraph.
    sections = (
        "## Exemplos\n"
        "Paragrafo aberto\n"
        "    continuacao da mesma frase\n"
        "<audit-example>\n"
        f"### {identifier} — registro externo realmente visivel\n"
    )
    errors = module.validate(report("APROVADA", sections=sections))
    assert any(identifier in error for error in errors), errors


@pytest.mark.parametrize("identifier", ["A-901", "RISK-901", "LIM-901"])
@pytest.mark.parametrize("formatting", [
    "{id}",
    "[{id}](https://github.com/crgasparoto-br/skill/issues/110)",
    "[{id}][finding]",
    "**[{id}](https://github.com/crgasparoto-br/skill/issues/110)**",
    "*[{id}](https://github.com/crgasparoto-br/skill/issues/110)*",
    "~~{id}~~",
    "<strong>{id}</strong>",
    '<a href="https://github.com/crgasparoto-br/skill/issues/110">{id}</a>',
    "<span>{id}</span>",
    "`{id}`",
])
@pytest.mark.parametrize("container", ["", "- ", "#### ", "> ", "1. "])
def test_issue110_rendered_inline_ids_cannot_hide_under_zero_counts(
    identifier, formatting, container,
):
    visible = formatting.format(id=identifier)
    references = ("\n[finding]: https://github.com/crgasparoto-br/skill/issues/110\n"
                  if "][finding]" in visible else "")
    text = report("APROVADA", sections=(
        "## Evidencias adicionais\n"
        + container + visible + " — registro comprovavel fora da triagem\n"
        + references
    ))
    errors = module.validate(text)
    assert any(identifier in error for error in errors), (container, visible, errors)


@pytest.mark.parametrize("identifier", ["A-902", "RISK-902", "LIM-902"])
def test_issue110_html_numeric_entity_identifier_is_not_hidden(identifier):
    encoded = f"&#{ord(identifier[0])};{identifier[1:]}"
    text = report("APROVADA", sections=(
        "## Evidencias adicionais\n"
        + encoded + " — registro com identificador renderizado\n"
    ))
    assert any(identifier in error for error in module.validate(text))


@pytest.mark.parametrize("identifier", ["A-903", "RISK-903", "LIM-903"])
def test_issue110_inline_rendered_id_inside_inert_fence_does_not_count(identifier):
    reference = f"[{identifier}](https://github.com/crgasparoto-br/skill/issues/110)"
    text = report("APROVADA", sections=(
        "## Exemplos\n\n```markdown\n"
        + reference + " — exemplo inerte\n```\n"
    ))
    assert module.validate(text) == []


def test_issue110_incidental_link_reference_is_not_a_record():
    text = report("APROVADA", sections=(
        "## Referencias\n"
        "Consulte [A-001](https://github.com/crgasparoto-br/skill/issues/110) "
        "para o historico da auditoria.\n"
    ))
    assert module.validate(text) == []

@pytest.mark.parametrize("identifier", ["A-904", "RISK-904", "LIM-904"])
@pytest.mark.parametrize("formatting", [
    "[{id}](https://example.com/foo(bar))",
    "[{id}](<https://example.com/a(b)>)",
    "**[{id}](https://example.com/a(b(c)))**",
    "~~[{id}](https://example.com/a(b))~~",
    "<mark>{id}</mark>",
    "<kbd>{id}</kbd>",
    '[{id}](https://example.com/item "title")',
    "[{id}](https://example.com) ",
])
def test_issue110_markup_variants_cannot_escape_triage(identifier, formatting):
    text = report("APROVADA", sections=(
        "## Evidencias adicionais\n\n"
        + formatting.format(id=identifier).rstrip() + " — registro visivel\n"
    ))
    assert any(identifier in error for error in module.validate(text))


@pytest.mark.parametrize("identifier", ["A-905", "RISK-905", "LIM-905"])
def test_issue110_escaped_hyphen_markdown_link_is_rendered_id(identifier):
    escaped = identifier.replace("-", r"\-")
    text = report("APROVADA", sections=(
        "## Evidencias adicionais\n"
        f"[{escaped}](https://example.com/issue) — registro visivel\n"
    ))
    assert any(identifier in error for error in module.validate(text))

@pytest.mark.parametrize("identifier", ["A-906", "RISK-906", "LIM-906"])
@pytest.mark.parametrize("formatting", [
    "[**{id}**](https://example.com/a(b))",
    "[*{id}*](https://example.com/a(b))",
    "[~~{id}~~](https://example.com/a(b))",
    "[<strong>{id}</strong>](https://example.com/a(b))",
    "*[**{id}**](https://example.com/a(b))*",
])
def test_issue110_decorated_link_labels_are_visible_evidence_identifiers(
    identifier, formatting,
):
    text = report("APROVADA", sections=(
        "## Evidencias adicionais\n\n"
        + formatting.format(id=identifier) + " — registro visivel\n"
    ))
    assert any(identifier in error for error in module.validate(text))
