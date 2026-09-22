#!/usr/bin/env python3
from __future__ import annotations

import re
from collections.abc import Iterable

CANONICAL_RISK_FAMILIES = {
    "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
    "temporal-consistency", "temporal-destination", "concurrency-atomicity",
    "idempotency", "rollback", "historical-immutability", "structural-contract", "documentation",
}

FLAG_FAMILIES = {
    "isolation": {"tenant-isolation"},
    "temporal": {"temporal-consistency"},
    "temporal-destination": {"temporal-destination"},
    "freshness": {"reference-liveness"},
    "reference-liveness": {"reference-liveness"},
    # The extractor flag is intentionally not mapped directly: it can mean
    # transaction/concurrency, deduplication, or merely one canonical source.
    # Derive the concrete family from source text instead of over-claiming concurrency.
    "atomicity": set(),
    "structural": {"structural-contract"},
    "forbidden-implementation": {"structural-contract"},
    "canonical-path": {"structural-contract"},
    "precedence": {"structural-contract"},
}

EVIDENCE_EFFECT_SCOPE_RE = re.compile(
    r"\b(relacionad\w*\s+(?:a|as)\s+evid[eê]ncias?|opera[cç][oõ]es?\s+afetad\w*|somente\s+(?:as\s+)?opera[cç][oõ]es?|escopo\s+(?:aprovad\w*|revisad\w*|autorizad\w*)|efeitos?\s+(?:autorizad\w*|permitid\w*)|affected operations|related to (?:the )?evidence|approved scope|authorized effects?)\b",
    re.I,
)

IDEMPOTENCY_RE = re.compile(
    r"\b(idempot\w*|retry|retries|callback\w*|webhook\w*|reprocess\w*|same[- ]key|mesma\s+chave|"
    r"n[aã]o\s+duplic\w*|sem\s+duplic\w*|duplicat\w*|duplicad\w*|repetir\s+exatamente|segunda\s+libera[cç][aã]o)\b",
    re.I,
)

QUANTITATIVE_RE = re.compile(
    r"(?:\b(?:p(?:50|75|90|95|99)|percentil\w*|percentile\w*|lat[eê]ncia|latency|throughput|benchmark|"
    r"dura[cç][aã]o|duration|tempo\s+m[eé]dio|average\s+time|custos?|costs?|contagem|count|counts|"
    r"quantidade|quantity|cardinalidade|cardinality|m[eé]dia\s+m[oó]vel|moving\s+average|"
    r"proje[cç][aã]o|projection|percentual|percentage|ratio|taxa|rate)\b|\b\d+(?:[.,]\d+)?\s*%)",
    re.I,
)

TEMPORAL_COVERAGE_RE = re.compile(
    r"\b(cobertura|coverage|qualidade\s+(?:dos\s+)?dados|data\s+quality|dispon[ií]vel|available(?:from|to)?|"
    r"janela|window|reten[cç][aã]o|retention|truncad\w*|truncat\w*|"
    r"hist[oó]rico\s+dispon[ií]vel|available\s+history)\b",
    re.I,
)

# A bare word such as "complete" can be a product code or an ordinary adjective.
# It only becomes reporting coverage when a reporting/availability context is also present.
REPORTING_COVERAGE_LABEL_RE = re.compile(
    r"\b(cobertura|coverage|qualidade\s+(?:dos\s+)?dados|data\s+quality|availablefrom|availableto|"
    r"available\s+from|available\s+to|janela\s+dispon[ií]vel|available\s+history)\b",
    re.I,
)
REPORTING_CONTEXT_RE = re.compile(
    r"\b(relat[oó]ri\w*|report\w*|cobertura|coverage|available|dispon[ií]vel|janela|window|reten[cç][aã]o|retention|hist[oó]ric\w*)\b",
    re.I,
)
COVERAGE_STATE_RE = re.compile(r"\b(complete|completed|completo|completa|partial|parcial)\b", re.I)

AUTHENTICATED_SESSION_RE = re.compile(
    r"\b(sess[aã]o\s+autenticad\w*|authenticated\s+session|usu[aá]rio\s+autenticad\w*|authenticated\s+user)\b",
    re.I,
)
TARGET_BINDING_RE = re.compile(
    r"\b(contractid|contract\s*id|contrato\s+alvo|target\s+contract|tenant\s+alvo|target\s+tenant)\b",
    re.I,
)
BODY_TARGET_OVERRIDE_RE = re.compile(
    r"\b(body|request|payload|cliente|client)\b.*\b(n[aã]o\s+pode|cannot|must\s+not|sobrescrev\w*|override|escolh\w*|choose)\b.*\b(alvo|target|contractid|contract\s*id|tenant)\b|"
    r"\b(alvo|target|contractid|contract\s*id|tenant)\b.*\b(n[aã]o\s+pode|cannot|must\s+not|sobrescrev\w*|override)\b.*\b(body|request|payload|cliente|client)\b",
    re.I,
)
TENANT_SCOPE_ISOLATION_RE = re.compile(
    r"(?:\b(?:tenant(?:s)?|perfil(?:es)?(?:\s+financeir[oa]s?)?|profile(?:s)?|organization(?:s)?|"
    r"organiza[cç][aã](?:o|oes|ões)|workspace(?:s)?)\b.{0,120}"
    r"\b(?:isolad\w*|isolat\w*|segregad\w*|segregat\w*|separad\w*|separat\w*|"
    r"sem\s+vazamento|n[aã]o\s+vaz\w*|no\s+(?:data\s+)?leak\w*)\b|"
    r"\b(?:isolad\w*|isolat\w*|segregad\w*|segregat\w*|separad\w*|separat\w*|"
    r"sem\s+vazamento|n[aã]o\s+vaz\w*|no\s+(?:data\s+)?leak\w*)\b.{0,120}"
    r"\b(?:tenant(?:s)?|perfil(?:es)?(?:\s+financeir[oa]s?)?|profile(?:s)?|organization(?:s)?|"
    r"organiza[cç][aã](?:o|oes|ões)|workspace(?:s)?)\b|"
    r"\b(?:cross[- ]tenant|outro\s+tenant|another\s+tenant|different\s+tenant|"
    r"tenant[- ]scoped|profile[- ]scoped|organization[- ]scoped)\b)",
    re.I | re.S,
)
CANONICAL_SOURCE_RE = re.compile(
    r"\b(fonte\s+[uú]nica|fonte\s+can[oô]nica|cat[aá]logo\s+can[oô]nic\w*|defini[cç][aã]o\s+can[oô]nic\w*|"
    r"mesma\s+fonte\s+l[oó]gica|n[aã]o\s+manter\s+(?:uma\s+)?segunda\s+lista|single[- ]source\s+of\s+truth|"
    r"canonical\s+(?:source|catalog|definition)|same\s+logical\s+source|shared\s+canonical\s+source)\b",
    re.I,
)
TEST_COVERAGE_LEAD_RE = re.compile(
    r"\b(?:testes?|tests?)\s+(?:cobrem|cobre|devem\s+cobrir|deve\s+cobrir|cover|covers|must\s+cover)\b",
    re.I,
)
RETENTION_CONTEXT_RE = re.compile(
    r"\b(retenc[cç][aã]o|retention|retid[oa]s?|retained|permanece(?:m)?|remain(?:s|ed)?|"
    r"\d+\s*(?:mes(?:es)?|months?|anos?|years?))\b",
    re.I,
)
RETENTION_TIER_PATTERNS = {
    "detail": re.compile(r"\b(eventos?\s+detalhad\w*|detailed\s+(?:usage\s+)?events?|event\s+detail)\b", re.I),
    "hourly": re.compile(r"\b(agrega[cç][aã]o(?:es|ões)?\s+hor[aá]ri\w*|hourly\s+aggregates?)\b", re.I),
    "daily": re.compile(r"\b(agrega[cç][aã]o(?:es|ões)?\s+di[aá]ri\w*|daily\s+aggregates?)\b", re.I),
    "monthly": re.compile(r"\b(agrega[cç][aã]o(?:es|ões)?\s+mensal\w*|agrega[cç][aã]o(?:es|ões)?\s+mensais|monthly\s+aggregates?)\b", re.I),
    "yearly": re.compile(r"\b(agrega[cç][aã]o(?:es|ões)?\s+anual\w*|yearly\s+aggregates?|annual\s+aggregates?)\b", re.I),
}
RETENTION_TIER_GRANULARITY = {
    "detail": "instant",
    "hourly": "hour",
    "daily": "day",
    "monthly": "month",
    "yearly": "year",
}

TEXT_FAMILIES = (
    (re.compile(r"\b(permiss[aã]o|autoriz\w*|entitlement|perfil|authenticated|autenticad\w*)\b", re.I), "authorization"),
    (EVIDENCE_EFFECT_SCOPE_RE, "authorization"),
    (TENANT_SCOPE_ISOLATION_RE, "tenant-isolation"),
    (re.compile(r"\b(n[aã]o revelar|n[aã]o enumera|404 gen[eé]ric|payload p[uú]blico|fronteira p[uú]blica)\b", re.I), "public-boundary"),
    (IDEMPOTENCY_RE, "idempotency"),
    (re.compile(
        r"\b(concorr[eê]ncia|serializ|for update|lock)\b|"
        r"\b(opera[cç][oõ]es?|requisi[cç][oõ]es?|requests?|writes?|updates?|transa[cç][oõ]es?)\s+concorrentes?\b|"
        r"\bconcorrentes?\s+(opera[cç][oõ]es?|requisi[cç][oõ]es?|requests?|writes?|updates?|transa[cç][oõ]es?)\b",
        re.I,
    ), "concurrency-atomicity"),
    (re.compile(r"\b(rollback|estado parcial|transa[cç][aã]o)\b", re.I), "rollback"),
    (re.compile(r"\b(hist[oó]ric|imut[aá]vel|nova revis[aã]o|vers[aã]o anterior)\b", re.I), "historical-immutability"),
    (re.compile(r"\b(documenta[cç][aã]o|readme|adr|runbook)\b", re.I), "documentation"),
    (re.compile(r"\b(futuro|passad[oa]|semana|per[ií]odo|vig[eê]ncia|data alvo|workoutdate|weekstartdate)\b", re.I), "temporal-destination"),
    (TEMPORAL_COVERAGE_RE, "temporal-consistency"),
    (re.compile(r"\b(continua(?:m)? (?:v[aá]lid|acess[ií]vel)|revalid\w*|no momento d[aeo]|ap[oó]s aprova[cç][aã]o|antes de liberar|refer[eê]ncias? obrigat[oó]rias?)\b", re.I), "reference-liveness"),
    (re.compile(r"\b(lat[eê]ncia|p50|p90|p95|percentil|total_ms|db_ms|context_ms|llm_ms|persist_ms|throughput|benchmark|caminho cr[ií]tico|critical path|opera[cç][oõ]es? n[aã]o essenciais|lazy loading|redu[cç][aã]o de i/o)\b", re.I), "structural-contract"),
)

PERFORMANCE_STAGE_RE = re.compile(
    r"\b(db_ms|context_ms|llm_ms|persist_ms|instrumenta[cç][aã]o|tempo gasto em banco|montagem de contexto|tempo de persist[eê]ncia|m[eé]tricas? por etapa|stage metrics?)\b",
    re.I,
)
PERFORMANCE_NECESSITY_RE = re.compile(
    r"\b(lat[eê]ncia|p50|p90|p95|percentil|caminho cr[ií]tico|critical path|opera[cç][oõ]es? n[aã]o essenciais|trabalho desnecess[aá]rio|lazy loading|redu[cç][aã]o de i/o)\b",
    re.I,
)
PERFORMANCE_BENCHMARK_RE = re.compile(
    r"\b(benchmark|before/after|antes/depois|baseline|candidate|candidato|mesmo caminho produtivo|same productive path|production path|caminho produtivo|entrypoint produtivo|production entrypoint)\b",
    re.I,
)

IDENTITY_FIELD_PATTERNS = {
    "plan": re.compile(r"\b(plan(?:code)?|plano)\b", re.I),
    "product": re.compile(r"\b(product(?:code)?|produto)\b", re.I),
    "version": re.compile(r"\b(version(?:code)?|vers[aã]o)\b", re.I),
    "subscription": re.compile(r"\b(subscription(?:id)?|assinatura)\b", re.I),
    "billing-cycle": re.compile(r"\b(billing\s*cycle|billingcycle|ciclo\s+de\s+cobran[cç]a|ciclo)\b", re.I),
    "beneficiary": re.compile(r"\b(beneficiar\w*|beneficiary)\b", re.I),
    "sponsor": re.compile(r"\b(sponsor|patrocinador\w*)\b", re.I),
    "patient": re.compile(r"\b(patient|paciente)\b", re.I),
    "tenant": re.compile(r"\b(tenant|organization|organiza[cç][aã]o)\b", re.I),
}

SEMANTIC_IDENTITY_DIVERGENCE_RE = re.compile(
    r"\b(distinct|different|divergent|mismatch|deliberat\w*|valores?\s+distint\w*|diferent\w*|divergent\w*|deliberadamente)\b",
    re.I,
)
SEMANTIC_IDENTITY_PERSISTENCE_RE = re.compile(
    r"\b(persist\w*|repository|reposit[oó]rio|payload|field|campo|argument|argumento|writer|produtor|producer|entrypoint|adaptador|adapter|mapping|mapeamento|ledger|store|storage)\b",
    re.I,
)

SEMANTIC_DIMENSION_RE = re.compile(
    r"\b(currency|currencies|moeda|moedas|unit|units|unidade|unidades|locale|timezone|fuso|scope|escopo|tenant)\b",
    re.I,
)
SINGLE_SOURCE_RE = re.compile(
    r"\b(must_be_single_source|single[- ]source(?: of truth)?|fonte\s+[uú]nica|fonte\s+can[oô]nica|"
    r"cat[aá]logo\s+can[oô]nic\w*|defini[cç][aã]o\s+can[oô]nic\w*|mesma\s+fonte\s+l[oó]gica|"
    r"n[aã]o\s+manter\s+(?:uma\s+)?segunda\s+lista|canonical\s+(?:source|catalog|definition))\b",
    re.I,
)
SEMANTIC_SOURCE_DERIVATION_RE = re.compile(
    r"\b(deve\s+vir|devem\s+vir|must\s+come|must\s+originate|comes?\s+from|derive\w*\s+from|"
    r"derivad\w*\s+de|fonte\s+do\s+c[aá]lculo|source\s+of\s+(?:the\s+)?calculation|"
    r"formatter|label|r[oó]tulo|default|presentation|apresenta[cç][aã]o)\b",
    re.I,
)
SEMANTIC_NO_MIX_RE = re.compile(
    r"\b(n[aã]o\s+(?:somar|misturar|combinar|coalescer|reinterpretar)\w*|"
    r"cannot\s+(?:sum|mix|combine|coalesce|reinterpret)|must\s+not\s+(?:sum|mix|combine|coalesce)|"
    r"sem\s+convers[aã]o\s+expl[ií]cita|without\s+explicit\s+conversion|cross[- ]currency|mixed[- ]currency)\b",
    re.I,
)

FUTURE_CHARGE_RE = re.compile(
    r"\b(cobran[cç]a\s+futura|cobran[cç]a\s+por\s+consumo|future\s+charg\w*|overage|excedente|"
    r"cr[eé]ditos?|pacote\s+adicional|mudan[cç]a\s+autom[aá]tica\s+de\s+plano)\b",
    re.I,
)
AUTHORIZATION_EXPLICIT_RE = re.compile(
    r"\b(autoriz\w*|approval|aprova[cç][aã]o|administrator|administrador\w*)\b",
    re.I,
)
HISTORICAL_ATTRIBUTION_RE = re.compile(
    r"\b(mudan[cç]a\s+(?:posterior|futura)\s+de\s+plano|later\s+plan\s+change|"
    r"n[aã]o\s+reatribu\w*|does\s+not\s+reattribut\w*|atribui[cç][aã]o\s+hist[oó]ric\w*|historical\s+attribution)\b",
    re.I,
)
ECONOMIC_COMPETENCE_RE = re.compile(
    r"\b(compet[eê]ncia|reconhec\w*\s+receita|receita\s+reconhecid\w*|apropria[cç][aã]o|"
    r"per[ií]odo\s+de\s+presta[cç][aã]o|service\s+period|recogniz\w*\s+revenue|prorat\w*)\b",
    re.I,
)
TEMPORARY_LIMITATION_RE = re.compile(
    r"\b(limita[cç][aã]o\s+tempor[aá]ria|temporary\s+limitation|prote[cç][aã]o\s+emergencial|emergency\s+protection)\b",
    re.I,
)
LIMITATION_LIFECYCLE_RE = re.compile(
    r"\b(extens[aã]o\s+adicional|additional\s+extension|segundo\s+administrador|second\s+administrator|"
    r"reverter\s+imediatamente|revert\s+immediately|data\s+autom[aá]tica\s+de\s+t[eé]rmino|automatic\s+end\s+date)\b",
    re.I,
)
ROLLBACK_EFFECT_RE = re.compile(
    r"\b(rollback|desativa[cç][aã]o|revog\w*|revert\w*|reverter|revers[ií]vel|reversible)\b",
    re.I,
)


def compact_source_texts(source_texts: Iterable[str]) -> str:
    return "\n".join(str(value) for value in source_texts if str(value).strip())


def identity_fields(text: str) -> set[str]:
    return {name for name, pattern in IDENTITY_FIELD_PATTERNS.items() if pattern.search(text)}


def requires_semantic_identity_propagation(source_texts: Iterable[str]) -> bool:
    return len(identity_fields(compact_source_texts(source_texts))) >= 2


def requires_relational_semantic_integrity(source_texts: Iterable[str]) -> bool:
    text = compact_source_texts(source_texts)
    if SINGLE_SOURCE_RE.search(text):
        return True
    return bool(
        SEMANTIC_DIMENSION_RE.search(text)
        and (SEMANTIC_SOURCE_DERIVATION_RE.search(text) or SEMANTIC_NO_MIX_RE.search(text))
    )


def requires_quantitative_evidence(source_texts: Iterable[str]) -> bool:
    return bool(QUANTITATIVE_RE.search(compact_source_texts(source_texts)))


def requires_benchmark_path_fidelity(source_texts: Iterable[str]) -> bool:
    return bool(PERFORMANCE_BENCHMARK_RE.search(compact_source_texts(source_texts)))


def requires_reporting_coverage(source_texts: Iterable[str]) -> bool:
    text = compact_source_texts(source_texts)
    return bool(
        REPORTING_COVERAGE_LABEL_RE.search(text)
        or (REPORTING_CONTEXT_RE.search(text) and COVERAGE_STATE_RE.search(text))
    )


def required_test_cases_from_texts(source_texts: Iterable[str]) -> list[str]:
    """Extract explicitly enumerated scenarios from clauses such as 'Tests cover A, B and C'.

    This is deliberately conservative: it only parses the tail of an explicit test-coverage
    clause and preserves the source phrases so the attack matrix cannot silently drop siblings.
    """
    cases: list[str] = []
    seen: set[str] = set()
    for raw in source_texts:
        text = str(raw).strip()
        match = TEST_COVERAGE_LEAD_RE.search(text)
        if not match:
            continue
        tail = text[match.end():].strip(" :-.")
        if not tail:
            continue
        # Normalize the final conjunction into the same delimiter used by comma lists.
        tail = re.sub(r"\s+(?:e|and)\s+(?=[^,;]+$)", ", ", tail, flags=re.I)
        for part in re.split(r"[,;]", tail):
            case = re.sub(r"\s+", " ", part).strip(" .")
            if len(case) < 3:
                continue
            key = case.casefold()
            if key not in seen:
                seen.add(key)
                cases.append(case)
    return cases


def retention_tiers_from_closure(closure: dict) -> list[dict]:
    """Infer retained data tiers without coupling the rule to a product or issue.

    A tier is inferred only when one atomic source text contains both a tier label
    and a retention/duration signal. This keeps unrelated mentions of daily or
    monthly reporting from becoming retention obligations.
    """
    tiers: dict[str, dict] = {}
    for obligation in closure.get("obligations") or []:
        if not isinstance(obligation, dict) or obligation.get("disposition") != "covered":
            continue
        text = str(obligation.get("source_text") or "").strip()
        if not text or not RETENTION_CONTEXT_RE.search(text):
            continue
        for tier, pattern in RETENTION_TIER_PATTERNS.items():
            if pattern.search(text):
                tiers[tier] = {"tier": tier, "granularity": RETENTION_TIER_GRANULARITY[tier]}
    return [tiers[key] for key in sorted(tiers)]


def coverage_requirement_ids_from_closure(closure: dict) -> set[str]:
    result: set[str] = set()
    for obligation in closure.get("obligations") or []:
        if not isinstance(obligation, dict) or obligation.get("disposition") != "covered":
            continue
        text = str(obligation.get("source_text") or "").strip()
        if not text or not REPORTING_COVERAGE_LABEL_RE.search(text):
            continue
        result.update(str(value) for value in obligation.get("requirement_ids") or [])
    return result


def derive_families_from_text(text: str, flags: Iterable[object] = ()) -> set[str]:
    families: set[str] = set()
    for flag in flags:
        families.update(FLAG_FAMILIES.get(str(flag), set()))
    for pattern, family in TEXT_FAMILIES:
        if pattern.search(text):
            families.add(family)
    if PERFORMANCE_BENCHMARK_RE.search(text):
        families.add("structural-contract")
    if AUTHENTICATED_SESSION_RE.search(text) and TARGET_BINDING_RE.search(text):
        families.add("authorization")
    if BODY_TARGET_OVERRIDE_RE.search(text):
        families.update({"authorization", "public-boundary"})
    if CANONICAL_SOURCE_RE.search(text) or TEST_COVERAGE_LEAD_RE.search(text):
        families.add("structural-contract")
    if len(identity_fields(text)) >= 2:
        families.add("structural-contract")
    if requires_relational_semantic_integrity([text]):
        families.add("structural-contract")
    if FUTURE_CHARGE_RE.search(text) and AUTHORIZATION_EXPLICIT_RE.search(text):
        families.add("authorization")
    if FUTURE_CHARGE_RE.search(text) and ROLLBACK_EFFECT_RE.search(text):
        families.add("rollback")
    if HISTORICAL_ATTRIBUTION_RE.search(text):
        families.add("historical-immutability")
    if ECONOMIC_COMPETENCE_RE.search(text) or TEMPORARY_LIMITATION_RE.search(text):
        families.add("temporal-consistency")
    if TEMPORARY_LIMITATION_RE.search(text) and LIMITATION_LIFECYCLE_RE.search(text):
        families.add("concurrency-atomicity")
    return families


def derive_families_from_obligation(obligation: dict) -> set[str]:
    text = str(obligation.get("source_text") or "")
    families = derive_families_from_text(text, obligation.get("flags") or [])
    if not families:
        families.add("semantic-effect")
    return families


def derive_surfaces(source_texts: list[str]) -> list[dict]:
    text = compact_source_texts(source_texts)
    surfaces: list[dict] = []
    if PERFORMANCE_STAGE_RE.search(text):
        surfaces.append({
            "risk_family": "structural-contract",
            "surface": "stage-attribution-completeness",
            "reason": "Stage metrics can under-report transitive or parallel operations that execute outside the declared timing boundary.",
        })
    if PERFORMANCE_NECESSITY_RE.search(text):
        surfaces.append({
            "risk_family": "structural-contract",
            "surface": "critical-path-necessity",
            "reason": "Latency can improve while expensive operations remain on the productive path even when their outputs are not consumed by the selected branch.",
        })
    if PERFORMANCE_BENCHMARK_RE.search(text):
        surfaces.append({
            "risk_family": "structural-contract",
            "surface": "benchmark-path-fidelity",
            "reason": "A benchmark can improve while bypassing productive wrappers or operations that still execute in the real application path.",
        })
    if EVIDENCE_EFFECT_SCOPE_RE.search(text):
        surfaces.append({
            "risk_family": "authorization",
            "surface": "evidence-effect-scope",
            "reason": "A valid evidence or approval can exist while a later branch applies an effect outside the scope authorized by that source.",
        })
    if IDEMPOTENCY_RE.search(text):
        surfaces.append({
            "risk_family": "idempotency",
            "surface": "duplicate-processing",
            "reason": "Retry, callback duplication, replay or reprocessing can execute the same logical operation more than once.",
        })
    if requires_reporting_coverage(source_texts):
        surfaces.append({
            "risk_family": "temporal-consistency",
            "surface": "reporting-availability-window",
            "reason": "A report can label a requested window complete even when retention or source availability makes only a suffix of that window observable.",
        })
    if AUTHENTICATED_SESSION_RE.search(text) and TARGET_BINDING_RE.search(text):
        surfaces.append({
            "risk_family": "authorization",
            "surface": "session-target-binding",
            "reason": "A request can be authenticated yet still apply an operation to a client-selected target instead of the target bound to the authenticated session.",
        })
    if BODY_TARGET_OVERRIDE_RE.search(text):
        surfaces.append({
            "risk_family": "public-boundary",
            "surface": "request-target-override",
            "reason": "An untrusted request body can attempt to choose or overwrite the protected target while the ordinary request path still succeeds.",
        })
    if TENANT_SCOPE_ISOLATION_RE.search(text):
        surfaces.append({
            "risk_family": "tenant-isolation",
            "surface": "tenant-scope-isolation",
            "reason": "A happy path scoped to one tenant/profile can still leak or mix records from another scope unless divergent tenant/profile identities are exercised.",
        })
    if CANONICAL_SOURCE_RE.search(text):
        surfaces.append({
            "risk_family": "structural-contract",
            "surface": "canonical-source-consistency",
            "reason": "Equivalent runtime, seed, import or maintenance paths can drift when they do not consume the same canonical product definition.",
        })
    if TEST_COVERAGE_LEAD_RE.search(text):
        surfaces.append({
            "risk_family": "structural-contract",
            "surface": "specified-test-matrix",
            "reason": "A subset of green tests can satisfy the happy path while explicitly required sibling scenarios remain unexecuted.",
        })
    if FUTURE_CHARGE_RE.search(text) and AUTHORIZATION_EXPLICIT_RE.search(text):
        surfaces.append({
            "risk_family": "authorization",
            "surface": "future-charge-authorization",
            "reason": "A measured threshold or technical state can be mistaken for authorization to create a future charge or commercial effect.",
        })
    if FUTURE_CHARGE_RE.search(text) and ROLLBACK_EFFECT_RE.search(text):
        surfaces.append({
            "risk_family": "rollback",
            "surface": "future-charge-rollback",
            "reason": "A future commercial effect can become active without a verified reversible rollback or deactivation contract.",
        })
    if HISTORICAL_ATTRIBUTION_RE.search(text):
        surfaces.append({
            "risk_family": "historical-immutability",
            "surface": "usage-attribution-history",
            "reason": "A later commercial-state change can silently reattribute already recorded historical usage while current-state outputs still look valid.",
        })
    if ECONOMIC_COMPETENCE_RE.search(text):
        surfaces.append({
            "risk_family": "temporal-consistency",
            "surface": "economic-competence",
            "reason": "Economic recognition can use receipt or mutation time instead of the service competence period while totals still appear plausible.",
        })
    if TEMPORARY_LIMITATION_RE.search(text):
        surfaces.append({
            "risk_family": "temporal-consistency",
            "surface": "temporary-limitation-duration",
            "reason": "A temporary or emergency limitation can exceed its contractual duration even when the limitation itself is otherwise valid.",
        })
    if TEMPORARY_LIMITATION_RE.search(text) and LIMITATION_LIFECYCLE_RE.search(text):
        surfaces.append({
            "risk_family": "concurrency-atomicity",
            "surface": "limitation-lifecycle",
            "reason": "Concurrent initial, extension, expiry or reversal decisions can create overlapping or contradictory limitation lifecycle state.",
        })
    if requires_semantic_identity_propagation(source_texts):
        fields = sorted(identity_fields(text))
        surfaces.append({
            "risk_family": "structural-contract",
            "surface": "semantic-identity-propagation",
            "reason": "Adjacent identity fields can be swapped, omitted or conflated while the happy path still produces a valid-looking record; fields=" + ",".join(fields),
        })
    if requires_relational_semantic_integrity(source_texts):
        surfaces.append({
            "risk_family": "structural-contract",
            "surface": "relational-semantic-integrity",
            "reason": "A calculation can look correctly partitioned while linked records carry incompatible semantic dimensions because the canonical write path never enforces their relation.",
        })
    return surfaces


def required_canonical_families_from_closure(closure: dict) -> set[str]:
    required: set[str] = set()
    for obligation in closure.get("obligations") or []:
        if not isinstance(obligation, dict) or obligation.get("disposition") != "covered":
            continue
        required.update(derive_families_from_obligation(obligation) & CANONICAL_RISK_FAMILIES)
    return required


def required_canonical_surfaces_from_closure(closure: dict) -> set[tuple[str, str]]:
    required: set[tuple[str, str]] = set()
    for obligation in closure.get("obligations") or []:
        if not isinstance(obligation, dict) or obligation.get("disposition") != "covered":
            continue
        source_text = str(obligation.get("source_text") or "").strip()
        if not source_text:
            continue
        for entry in derive_surfaces([source_text]):
            family = str(entry.get("risk_family") or "").strip()
            surface = str(entry.get("surface") or "").strip()
            if family in CANONICAL_RISK_FAMILIES and surface:
                required.add((family, surface))
    return required
