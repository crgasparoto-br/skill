#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from audit_artifact_io import load_json_artifact
from risk_inference import (
    CANONICAL_RISK_FAMILIES,
    SEMANTIC_IDENTITY_DIVERGENCE_RE,
    SEMANTIC_IDENTITY_PERSISTENCE_RE,
    coverage_requirement_ids_from_closure,
    derive_families_from_obligation,
    derive_families_from_text,
    identity_fields,
    required_test_cases_from_texts,
    requires_benchmark_path_fidelity,
    requires_quantitative_evidence,
    retention_tiers_from_closure,
)
from risk_inference import (
    derive_surfaces as derive_source_surfaces,
)

HIGH_RISK = {
    "authorization", "tenant-isolation", "public-boundary", "reference-liveness",
    "temporal-destination", "concurrency-atomicity", "idempotency", "rollback",
    "historical-immutability",
}
CONTROL_TYPES = {"test", "gate", "scenario", "procedure"}
EVIDENCE_KINDS = {"behavioral", "structural", "quantitative", "documentation"}
SHA_RE = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
SURFACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


GENERIC_TEXT_PATTERNS = (
    re.compile(r"^wrong shortcut keeps (?:the )?happy path\.?$", re.IGNORECASE),
    re.compile(r"^silent contract break\.?$", re.IGNORECASE),
    re.compile(r"^run (?:the )?exact[- ]head control\.?$", re.IGNORECASE),
    re.compile(r"^contract holds\.?$", re.IGNORECASE),
    re.compile(r"^observed pass(?:ed)?\.?$", re.IGNORECASE),
    re.compile(r"^(?:the )?test pass(?:es|ed)?\.?$", re.IGNORECASE),
    re.compile(r"^works? as expected\.?$", re.IGNORECASE),
    re.compile(r"^material surface\.?$", re.IGNORECASE),
    re.compile(r"^exact[- ]head evidence passed\.?$", re.IGNORECASE),
)

PERFORMANCE_STAGE_RE = re.compile(
    r"\b(db_ms|context_ms|llm_ms|persist_ms|instrumenta[cç][aã]o|tempo gasto em banco|montagem de contexto|tempo de persist[eê]ncia|m[eé]tricas? por etapa|stage metrics?)\b",
    re.IGNORECASE,
)
PERFORMANCE_NECESSITY_RE = re.compile(
    r"\b(lat[eê]ncia|p50|p90|p95|percentil|caminho cr[ií]tico|critical path|opera[cç][oõ]es? n[aã]o essenciais|trabalho desnecess[aá]rio|lazy loading|redu[cç][aã]o de i/o)\b",
    re.IGNORECASE,
)
EVIDENCE_EFFECT_SCOPE_RE = re.compile(
    r"\b(relacionad\w*\s+(?:a|as)\s+evid[eê]ncias?|opera[cç][oõ]es?\s+afetad\w*|somente\s+(?:as\s+)?opera[cç][oõ]es?|escopo\s+(?:aprovad\w*|revisad\w*|autorizad\w*)|efeitos?\s+(?:autorizad\w*|permitid\w*)|affected operations|related to (?:the )?evidence|approved scope|authorized effects?)\b",
    re.IGNORECASE,
)
EXCEPTION_BRANCH_RE = re.compile(
    r"\b(emerg[eê]nc\w*|emergency|exce[cç][aã]o|exception|override|bypass|fallback|break[- ]glass)\b",
    re.IGNORECASE,
)
EVIDENCE_TERM_RE = re.compile(r"\b(evid[eê]nc\w*|review\w*|revis\w*|approval|approv\w*|aprova\w*|authorized scope|escopo autoriz\w*)\b", re.IGNORECASE)
EFFECT_TERM_RE = re.compile(r"\b(effect\w*|efeito\w*|opera[cç][aã]o|operations?|action|a[cç][aã]o|restriction|limita[cç][aã]o|mutation|muta[cç][aã]o|resource|recurso)\b", re.IGNORECASE)
MISMATCH_TERM_RE = re.compile(r"\b(unrelated|nao relacionad\w*|fora do escopo|different|divergent|mismatch|nao autorizad\w*|not authorized|rejeit\w*|reject\w*)\b", re.IGNORECASE)

RELATIONAL_DIVERGENCE_RE = re.compile(
    r"\b(incompat\w*|mismatch|different|distinct|divergent|conflict\w*|inconsisten\w*|"
    r"valores?\s+(?:diferent\w*|distint\w*|incompat\w*)|dimens(?:ion|a[oã])\s+(?:diferent\w*|incompat\w*))\b",
    re.IGNORECASE,
)
RELATIONAL_WRITE_BOUNDARY_RE = re.compile(
    r"\b(create|update|mutation|mutat\w*|write|writer|persist\w*|producer|produtor|entrypoint|"
    r"repository|reposit[oó]rio|domain\s+boundary|fronteira\s+de\s+dom[ií]nio|canonical\s+(?:write|path)|caminho\s+can[oô]nico)\b",
    re.IGNORECASE,
)
RELATIONAL_LINK_RE = re.compile(
    r"\b(linked|related|reference|refer[eê]ncia|parent|child|source|destination|origem|destino|owner|"
    r"record|registro|entity|entidade|foreign\s+key|rela[cç][aã]o|v[ií]nculo)\b",
    re.IGNORECASE,
)
RELATIONAL_OUTCOME_RE = re.compile(
    r"\b(reject\w*|rejeit\w*|fail[- ]closed|no\s+write|sem\s+(?:escrita|muta[cç][aã]o)|"
    r"explicit\s+conversion|convers[aã]o\s+expl[ií]cita|transform\w*|read\s*back|releitura|aggregate|agreg\w*|"
    r"consumer|consumidor|downstream|calculation|c[aá]lculo|projection|proje[cç][aã]o)\b",
    re.IGNORECASE,
)

TENANT_SCOPE_TERM_RE = re.compile(
    r"\b(tenant(?:s)?|perfil(?:es)?(?:\s+financeir[oa]s?)?|profile(?:s)?|organization(?:s)?|"
    r"organiza[cç][aã](?:o|oes|ões)|workspace(?:s)?)\b",
    re.IGNORECASE,
)
TENANT_DIVERGENCE_RE = re.compile(
    r"\b(outro|outra|another|different|distinct|divergent|cross[- ]tenant|segundo|segunda|two|dois|duas|"
    r"deliberat\w*|diferent\w*|distint\w*)\b",
    re.IGNORECASE,
)
TENANT_ISOLATION_OUTCOME_RE = re.compile(
    r"\b(isolad\w*|isolat\w*|segregad\w*|segregat\w*|sem\s+vazamento|n[aã]o\s+vaz\w*|"
    r"no\s+(?:data\s+)?leak\w*|exclu\w*|exclude\w*|omit\w*|reject\w*|rejeit\w*|"
    r"zero\s+(?:foreign|cross[- ]tenant|out[- ]of[- ]scope)|fora\s+do\s+escopo)\b",
    re.IGNORECASE,
)

PERFORMANCE_SURFACE_KEYWORDS = {
    "stage-attribution-completeness": {
        "timer", "span", "operation", "operations", "operacao", "operacoes", "query", "queries",
        "database", "banco", "parallel", "paralelo", "transitive", "transitivo", "boundary", "fronteira",
        "call", "calls", "chamada", "chamadas", "metric", "metrica",
    },
    "critical-path-necessity": {
        "zero", "unused", "desnecessario", "desnecessaria", "consumed", "consumido", "consumida",
        "invoked", "invocado", "invocada", "called", "chamado", "chamada", "loader", "helper", "query",
        "branch", "ramo", "critical", "critico", "path", "caminho", "count", "contagem",
    },
    "benchmark-path-fidelity": {
        "benchmark", "production", "productive", "produtivo", "entrypoint", "harness", "worker",
        "omitted", "omitido", "bridged", "ponte", "wrapper", "operation", "operacao", "path", "caminho",
    },
    "evidence-effect-scope": {
        "evidence", "evidencia", "review", "approval", "scope", "escopo", "effect", "efeito",
        "operation", "operacao", "unrelated", "divergent", "authorized", "autorizado", "reject", "rejeitar",
    },
    "session-target-binding": {
        "session", "sessao", "authenticated", "autenticado", "target", "alvo", "contract", "contrato", "tenant",
    },
    "request-target-override": {
        "body", "request", "payload", "client", "cliente", "target", "alvo", "override", "contract", "tenant",
    },
    "canonical-source-consistency": {
        "canonical", "canonico", "catalog", "catalogo", "source", "fonte", "definition", "definicao", "runtime", "seed", "drift",
    },
    "specified-test-matrix": {
        "test", "tests", "teste", "testes", "scenario", "cenario", "case", "caso", "coverage", "cobertura", "matrix", "matriz",
    },
}

SURFACE_HINTS = {
    "environment": (
        "process.env", "extraenv", "environment variable", "environment variables",
        "env var", "env vars", "child environment",
    ),
    "filesystem": (
        "filesystem", "file system", "private key", "signing key", "read file",
        "readable file", "path sibling", "sibling path",
    ),
    "persistent-credential-store": (
        "codex_home", "codex home", "auth.json", "credential cache", "persistent home",
        "persistent credential", "refresh token",
    ),
    "artifact-export": (
        "artifact upload", "upload artifact", "run artifact", "forensic state", "exported run",
    ),
    "process-identity": (
        "same user", "same uid", "process isolation", "container", "virtual machine",
        "mount namespace", "runner user",
    ),
}


def load(path: Path) -> dict:
    try:
        value = load_json_artifact(path)
    except Exception as exc:
        raise SystemExit(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def compact_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(compact_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(compact_text(v) for v in value)
    return str(value)


def normalize_words(value: object) -> set[str]:
    raw = compact_text(value).lower()
    normalized = "".join(
        char for char in raw
        if char.isalnum() or char in {"_", "-", " ", "/"}
    )
    return {token for token in re.split(r"[^a-z0-9_/-]+", normalized) if len(token) >= 3}


def is_generic_text(value: object) -> bool:
    raw = compact_text(value).strip()
    if not raw:
        return False
    return any(pattern.fullmatch(raw) for pattern in GENERIC_TEXT_PATTERNS)


def validate_meaningful_text(value: object, label: str, errors: list[str]) -> None:
    raw = compact_text(value).strip()
    if is_generic_text(raw):
        errors.append(f"{label} is generic/tautological rather than reproducible evidence")


def source_required_families(item: dict) -> set[str]:
    source_text = "\n".join(str(value) for value in item.get("source_texts") or [])
    return derive_families_from_text(source_text) & CANONICAL_RISK_FAMILIES


def source_required_surfaces(item: dict) -> set[tuple[str, str]]:
    return {
        (str(entry.get("risk_family") or ""), str(entry.get("surface") or ""))
        for entry in derive_source_surfaces([str(value) for value in item.get("source_texts") or []])
        if isinstance(entry, dict) and entry.get("risk_family") and entry.get("surface")
    }


def validate_semantic_identity_control(control: dict, item: dict, label: str, errors: list[str]) -> None:
    combined = compact_text({
        "failure_mode": control.get("failure_mode"),
        "plausible_wrong_implementation": control.get("plausible_wrong_implementation"),
        "procedure": control.get("procedure"),
        "expected": control.get("expected"),
        "observed": control.get("observed"),
    })
    if not SEMANTIC_IDENTITY_DIVERGENCE_RE.search(combined):
        errors.append(f"{label} semantic identity control does not use deliberately distinct/divergent identity values")
    if not SEMANTIC_IDENTITY_PERSISTENCE_RE.search(combined):
        errors.append(f"{label} semantic identity control does not observe the mapping/persistence boundary")
    required_fields = identity_fields("\n".join(str(value) for value in item.get("source_texts") or []))
    mentioned_fields = identity_fields(combined)
    if len(required_fields) >= 2 and len(required_fields & mentioned_fields) < 2:
        errors.append(f"{label} semantic identity control does not name at least two source identity fields")


def validate_tenant_scope_isolation_control(control: dict, label: str, errors: list[str]) -> None:
    combined = compact_text({
        "failure_mode": control.get("failure_mode"),
        "plausible_wrong_implementation": control.get("plausible_wrong_implementation"),
        "procedure": control.get("procedure"),
        "expected": control.get("expected"),
        "observed": control.get("observed"),
    })
    if not TENANT_SCOPE_TERM_RE.search(combined):
        errors.append(f"{label} tenant isolation control does not identify a tenant/profile/organization scope")
    if not TENANT_DIVERGENCE_RE.search(combined):
        errors.append(f"{label} tenant isolation control does not use deliberately distinct scopes")
    if not TENANT_ISOLATION_OUTCOME_RE.search(combined):
        errors.append(f"{label} tenant isolation control does not prove exclusion/no-leak behavior")


def validate_relational_semantic_integrity_control(
    control: dict, label: str, errors: list[str]
) -> None:
    combined = compact_text({
        "failure_mode": control.get("failure_mode"),
        "plausible_wrong_implementation": control.get("plausible_wrong_implementation"),
        "procedure": control.get("procedure"),
        "expected": control.get("expected"),
        "observed": control.get("observed"),
    })
    if not RELATIONAL_DIVERGENCE_RE.search(combined):
        errors.append(f"{label} relational semantic control does not use deliberately incompatible/divergent linked values")
    if not RELATIONAL_WRITE_BOUNDARY_RE.search(combined):
        errors.append(f"{label} relational semantic control does not traverse the canonical mutation/producer boundary")
    if not RELATIONAL_LINK_RE.search(combined):
        errors.append(f"{label} relational semantic control does not identify linked/related records or references")
    if not RELATIONAL_OUTCOME_RE.search(combined):
        errors.append(f"{label} relational semantic control does not prove rejection/transformation or downstream absence of the invalid relation")
    siblings = [case for case in control.get("sibling_cases") or [] if isinstance(case, dict)]
    dimensions = {str(case.get("dimension") or "").strip() for case in siblings if str(case.get("dimension") or "").strip()}
    if len(siblings) < 2 or len(dimensions) < 2:
        errors.append(f"{label} relational semantic control requires at least two distinct sibling dimensions")


def validate_quantitative_requirement(
    item: dict,
    rid: str,
    provenance_available: bool,
    errors: list[str],
) -> None:
    if not requires_quantitative_evidence([str(value) for value in item.get("source_texts") or []]):
        return
    positive = item.get("positive_control")
    if not isinstance(positive, dict) or str(positive.get("evidence_kind") or "") != "quantitative":
        errors.append(f"requirement {rid} quantitative source requires quantitative positive control")
        return
    if not str(positive.get("evidence_id") or "").strip():
        errors.append(f"requirement {rid} quantitative positive control lacks evidence_id")
    if not provenance_available:
        errors.append(f"requirement {rid} quantitative source requires evidence-provenance.json")


def required_performance_surfaces(item: dict) -> set[tuple[str, str]]:
    source_texts = [str(value) for value in item.get("source_texts") or []]
    source_text = "\n".join(source_texts)
    required: set[tuple[str, str]] = set()
    if PERFORMANCE_STAGE_RE.search(source_text):
        required.add(("structural-contract", "stage-attribution-completeness"))
    if PERFORMANCE_NECESSITY_RE.search(source_text):
        required.add(("structural-contract", "critical-path-necessity"))
    if requires_benchmark_path_fidelity(source_texts):
        required.add(("structural-contract", "benchmark-path-fidelity"))
    return required


PERFORMANCE_STAGE_METRICS = {
    "db": "db_ms",
    "context": "context_ms",
    "llm": "llm_ms",
    "persist": "persist_ms",
}
PERFORMANCE_OPERATION_STAGES = set(PERFORMANCE_STAGE_METRICS) | {"delivery", "network", "cpu", "other"}


def validate_exact_head_evidence(value: object, label: str, head_sha: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{label} is missing")
        return
    if value.get("status") != "passed":
        errors.append(f"{label} is not passed")
    if str(value.get("head_sha") or "") != head_sha:
        errors.append(f"{label} head_sha does not match attack matrix head")
    if not str(value.get("evidence") or value.get("evidence_path") or "").strip():
        errors.append(f"{label} lacks evidence")
    if not SHA256_RE.match(str(value.get("evidence_sha256") or "").strip()):
        errors.append(f"{label} lacks valid evidence_sha256")
    procedure = str(value.get("procedure") or "").strip()
    observed = str(value.get("observed") or "").strip()
    if len(procedure) < 12:
        errors.append(f"{label} lacks procedure")
    if len(observed) < 8:
        errors.append(f"{label} lacks observed")
    validate_meaningful_text(procedure, f"{label} procedure", errors)
    validate_meaningful_text(observed, f"{label} observed", errors)


def validate_performance_contract(
    item: dict,
    rid: str,
    head_sha: str,
    required_surfaces: set[tuple[str, str]],
    errors: list[str],
) -> None:
    if not required_surfaces:
        return
    contract = item.get("performance_contract")
    if not isinstance(contract, dict):
        errors.append(f"requirement {rid} performance surfaces require performance_contract inventory")
        return

    production_entrypoint = str(contract.get("production_entrypoint") or "").strip()
    terminal_boundary = str(contract.get("terminal_boundary") or "").strip()
    if len(production_entrypoint) < 5:
        errors.append(f"requirement {rid} performance_contract lacks production_entrypoint")
    if len(terminal_boundary) < 5:
        errors.append(f"requirement {rid} performance_contract lacks terminal_boundary")
    validate_exact_head_evidence(
        contract.get("inventory_evidence"),
        f"requirement {rid} performance_contract inventory_evidence",
        head_sha,
        errors,
    )

    raw_operations = contract.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        errors.append(f"requirement {rid} performance_contract operations inventory is empty")
        return

    operations: dict[str, dict] = {}
    before_terminal_ids: set[str] = set()
    for index, operation in enumerate(raw_operations):
        label = f"requirement {rid} performance operation {index}"
        if not isinstance(operation, dict):
            errors.append(f"{label} is invalid")
            continue
        oid = str(operation.get("id") or "").strip()
        source = str(operation.get("source") or "").strip()
        stage = str(operation.get("stage") or "").strip()
        metric = operation.get("metric")
        before_terminal = operation.get("before_terminal")
        required_for_contract = operation.get("required_for_contract")
        if len(oid) < 3:
            errors.append(f"{label} lacks id")
            continue
        if oid in operations:
            errors.append(f"requirement {rid} performance operation id {oid} is duplicated")
            continue
        operations[oid] = operation
        if len(source) < 5:
            errors.append(f"{label} lacks source path/symbol")
        if stage not in PERFORMANCE_OPERATION_STAGES:
            errors.append(f"{label} has invalid stage {stage or '?'}")
        if not isinstance(before_terminal, bool):
            errors.append(f"{label} before_terminal must be boolean")
        elif before_terminal:
            before_terminal_ids.add(oid)
        if not isinstance(required_for_contract, bool):
            errors.append(f"{label} required_for_contract must be boolean")
        expected_metric = PERFORMANCE_STAGE_METRICS.get(stage)
        if before_terminal is True and expected_metric and metric != expected_metric:
            errors.append(
                f"{label} stage {stage} must be attributed to {expected_metric}; observed metric={metric!r}"
            )

    if ("structural-contract", "critical-path-necessity") in required_surfaces:
        branches = contract.get("optimized_branches")
        if not isinstance(branches, list) or not branches:
            errors.append(f"requirement {rid} critical-path-necessity requires optimized_branches inventory")
        else:
            zero_proofs = 0
            for index, branch in enumerate(branches):
                label = f"requirement {rid} optimized branch {index}"
                if not isinstance(branch, dict):
                    errors.append(f"{label} is invalid")
                    continue
                branch_id = str(branch.get("id") or "").strip()
                if len(branch_id) < 3:
                    errors.append(f"{label} lacks id")
                entries = branch.get("operations")
                if not isinstance(entries, list):
                    errors.append(f"{label} operations must be an array")
                    continue
                seen: set[str] = set()
                for entry_index, entry in enumerate(entries):
                    elabel = f"{label} operation {entry_index}"
                    if not isinstance(entry, dict):
                        errors.append(f"{elabel} is invalid")
                        continue
                    oid = str(entry.get("operation_id") or "").strip()
                    if oid not in operations:
                        errors.append(f"{elabel} references unknown operation {oid or '?'}")
                        continue
                    seen.add(oid)
                    needed = entry.get("needed")
                    status = entry.get("status")
                    expected_invocations = entry.get("expected_invocations")
                    observed_invocations = entry.get("observed_invocations")
                    if not isinstance(needed, bool):
                        errors.append(f"{elabel} needed must be boolean")
                        continue
                    if needed is False and operations[oid].get("required_for_contract") is False:
                        if status != "passed" or expected_invocations != 0 or observed_invocations != 0:
                            errors.append(
                                f"{elabel} unused non-required operation must prove zero invocations with passed status"
                            )
                        else:
                            zero_proofs += 1
                missing = sorted(before_terminal_ids - seen)
                if missing:
                    errors.append(f"{label} omits before-terminal operations from branch decision: {missing}")
            if zero_proofs == 0:
                errors.append(f"requirement {rid} critical-path-necessity has no zero-invocation proof for unused work")

    if ("structural-contract", "benchmark-path-fidelity") in required_surfaces:
        benchmark = contract.get("benchmark")
        if not isinstance(benchmark, dict):
            errors.append(f"requirement {rid} benchmark-path-fidelity requires benchmark contract")
            return
        mode = str(benchmark.get("mode") or "").strip()
        benchmark_production = str(benchmark.get("production_entrypoint") or "").strip()
        harness_entrypoint = str(benchmark.get("harness_entrypoint") or "").strip()
        if benchmark_production != production_entrypoint:
            errors.append(f"requirement {rid} benchmark production_entrypoint differs from performance_contract")
        if len(harness_entrypoint) < 5:
            errors.append(f"requirement {rid} benchmark lacks harness_entrypoint")
        if mode not in {"production-direct", "bridged"}:
            errors.append(f"requirement {rid} benchmark mode must be production-direct or bridged")
        covered = {str(value).strip() for value in benchmark.get("covered_operation_ids") or [] if str(value).strip()}
        bridged = {str(value).strip() for value in benchmark.get("bridged_operation_ids") or [] if str(value).strip()}
        omitted = {str(value).strip() for value in benchmark.get("omitted_operation_ids") or [] if str(value).strip()}
        unknown = sorted((covered | bridged | omitted) - set(operations))
        if unknown:
            errors.append(f"requirement {rid} benchmark references unknown operation ids: {unknown}")
        if omitted:
            errors.append(f"requirement {rid} benchmark omits productive operations: {sorted(omitted)}")
        missing = sorted(before_terminal_ids - covered - bridged)
        if missing:
            errors.append(f"requirement {rid} benchmark does not cover or bridge productive operations: {missing}")
        if mode == "production-direct":
            if harness_entrypoint != production_entrypoint:
                errors.append(f"requirement {rid} production-direct benchmark must start at production_entrypoint")
            if bridged:
                errors.append(f"requirement {rid} production-direct benchmark must not declare bridged operations")
        if mode == "bridged":
            if not bridged:
                errors.append(f"requirement {rid} bridged benchmark has no bridged operations")
            validate_exact_head_evidence(
                benchmark.get("bridge_evidence"),
                f"requirement {rid} benchmark bridge_evidence",
                head_sha,
                errors,
            )


def required_evidence_effect_surface(item: dict) -> bool:
    source_text = "\n".join(str(value) for value in item.get("source_texts") or [])
    return bool(EVIDENCE_EFFECT_SCOPE_RE.search(source_text))


def validate_evidence_effect_scope_controls(item: dict, errors: list[str], rid: str) -> None:
    source_text = "\n".join(str(value) for value in item.get("source_texts") or [])
    controls = [
        control for control in item.get("negative_controls") or []
        if isinstance(control, dict)
        and str(control.get("risk_family") or "") == "authorization"
        and str(control.get("surface") or "") == "evidence-effect-scope"
    ]
    if not controls:
        errors.append(f"requirement {rid} evidence-effect-scope lacks AUTH-EFFECT-SCOPE-001 style negative control")
        return
    combined = compact_text(controls)
    if not EVIDENCE_TERM_RE.search(combined) or not EFFECT_TERM_RE.search(combined) or not MISMATCH_TERM_RE.search(combined):
        errors.append(f"requirement {rid} evidence-effect-scope control does not prove a divergent evidence-to-effect rejection")
    if EXCEPTION_BRANCH_RE.search(source_text):
        sibling_text = compact_text([control.get("sibling_cases") or [] for control in controls])
        if not EXCEPTION_BRANCH_RE.search(sibling_text):
            errors.append(f"requirement {rid} evidence-effect-scope omits exception/emergency branch sibling")


def validate_surface_specific_control(control: dict, label: str, surface: str, errors: list[str]) -> None:
    keywords = PERFORMANCE_SURFACE_KEYWORDS.get(surface)
    if not keywords:
        return
    words = normalize_words({
        "failure_mode": control.get("failure_mode"),
        "plausible_wrong_implementation": control.get("plausible_wrong_implementation"),
        "procedure": control.get("procedure"),
        "expected": control.get("expected"),
        "observed": control.get("observed"),
    })
    if not words.intersection(keywords):
        errors.append(f"{label} does not describe a concrete {surface} attack/observation")



def validate_obligation_control_map(
    item: dict,
    *,
    rid: str,
    expected_obligation_ids: set[str],
    obligation_by_id: dict[str, dict],
    negative_controls: list[object],
    errors: list[str],
) -> None:
    """Require one distinct primary adversarial control per canonical obligation.

    Aggregating source obligations into one requirement is allowed, but it cannot collapse
    their proof. The mapping is fail-closed so an omnibus requirement cannot use a handful
    of broad controls to claim coverage for unrelated acceptance criteria.
    """
    raw = item.get("obligation_control_map")
    if not isinstance(raw, list):
        errors.append(f"requirement {rid} with multiple obligations requires obligation_control_map")
        return
    entries = [entry for entry in raw if isinstance(entry, dict)]
    mapped_ids = [str(entry.get("obligation_id") or "").strip() for entry in entries]
    mapped_set = {value for value in mapped_ids if value}
    missing = sorted(expected_obligation_ids - mapped_set)
    extra = sorted(mapped_set - expected_obligation_ids)
    if missing:
        errors.append(f"requirement {rid} obligation_control_map omits obligations: {missing}")
    if extra:
        errors.append(f"requirement {rid} obligation_control_map references unrelated obligations: {extra}")
    duplicates = sorted({oid for oid in mapped_ids if oid and mapped_ids.count(oid) > 1})
    if duplicates:
        errors.append(f"requirement {rid} obligation_control_map duplicates obligations: {duplicates}")

    controls_by_id = {
        str(control.get("id") or "").strip(): control
        for control in negative_controls
        if isinstance(control, dict) and str(control.get("id") or "").strip()
    }
    for entry in entries:
        oid = str(entry.get("obligation_id") or "").strip()
        cid = str(entry.get("primary_negative_control_id") or "").strip()
        if not oid or oid not in expected_obligation_ids:
            continue
        if not cid:
            errors.append(f"requirement {rid} obligation {oid} lacks primary_negative_control_id")
            continue
        control = controls_by_id.get(cid)
        if not isinstance(control, dict):
            errors.append(f"requirement {rid} obligation {oid} references unknown primary negative control {cid}")
            continue
        obligation = obligation_by_id.get(oid) or {}
        canonical_families = derive_families_from_obligation(obligation) & CANONICAL_RISK_FAMILIES
        source_text = str(obligation.get("source_text") or "").strip()
        canonical_surfaces = {
            (str(surface.get("risk_family") or ""), str(surface.get("surface") or ""))
            for surface in derive_source_surfaces([source_text])
            if isinstance(surface, dict) and surface.get("risk_family") and surface.get("surface")
        }
        control_family = str(control.get("risk_family") or "").strip()
        control_surface = str(control.get("surface") or "").strip()
        if canonical_surfaces and (control_family, control_surface) not in canonical_surfaces:
            expected = sorted(f"{family}:{surface}" for family, surface in canonical_surfaces)
            errors.append(
                f"requirement {rid} obligation {oid} primary control {cid} does not target a source-derived surface; "
                f"expected one of {expected}, observed {control_family}:{control_surface}"
            )
        elif canonical_families and control_family not in canonical_families:
            errors.append(
                f"requirement {rid} obligation {oid} primary control {cid} family {control_family or '?'} "
                f"does not match source-derived families {sorted(canonical_families)}"
            )


def validate_test_coverage_contract(
    item: dict,
    *,
    rid: str,
    negative_controls: list[object],
    errors: list[str],
) -> None:
    expected_cases = required_test_cases_from_texts([str(value) for value in item.get("source_texts") or []])
    if not expected_cases:
        return
    contract = item.get("test_coverage_contract")
    if not isinstance(contract, dict):
        errors.append(f"requirement {rid} explicit test coverage clause requires test_coverage_contract")
        return
    cases = [case for case in contract.get("cases") or [] if isinstance(case, dict)]
    by_case = {str(case.get("case") or "").strip().casefold(): case for case in cases if str(case.get("case") or "").strip()}
    expected_by_key = {case.casefold(): case for case in expected_cases}
    missing = [expected_by_key[key] for key in expected_by_key.keys() - by_case.keys()]
    extra = [str(by_case[key].get("case") or "") for key in by_case.keys() - expected_by_key.keys()]
    if missing:
        errors.append(f"requirement {rid} test_coverage_contract omits specified cases: {missing}")
    if extra:
        errors.append(f"requirement {rid} test_coverage_contract contains cases not specified by source: {extra}")

    controls_by_id = {
        str(control.get("id") or "").strip(): control
        for control in negative_controls
        if isinstance(control, dict) and str(control.get("id") or "").strip()
    }
    used_ids: set[str] = set()
    for key, source_case in expected_by_key.items():
        case = by_case.get(key)
        if not isinstance(case, dict):
            continue
        cid = str(case.get("control_id") or "").strip()
        if case.get("status") != "passed":
            errors.append(f"requirement {rid} specified test case {source_case!r} is not passed")
        if not str(case.get("evidence") or "").strip():
            errors.append(f"requirement {rid} specified test case {source_case!r} lacks evidence")
        if not cid:
            errors.append(f"requirement {rid} specified test case {source_case!r} lacks control_id")
            continue
        if cid in used_ids:
            errors.append(f"requirement {rid} test coverage reuses control {cid}; each specified case requires a distinct test control")
            continue
        used_ids.add(cid)
        control = controls_by_id.get(cid)
        if not isinstance(control, dict):
            errors.append(f"requirement {rid} specified test case {source_case!r} references unknown control {cid}")
            continue
        if str(control.get("control_type") or "") != "test":
            errors.append(f"requirement {rid} specified test case {source_case!r} control {cid} must have control_type=test")
        if (str(control.get("risk_family") or ""), str(control.get("surface") or "")) != (
            "structural-contract", "specified-test-matrix"
        ):
            errors.append(
                f"requirement {rid} specified test case {source_case!r} control {cid} must target "
                "structural-contract:specified-test-matrix"
            )


COVERAGE_GRANULARITIES = {"instant", "hour", "day", "month", "year"}


def parse_aware_datetime(value: object, label: str, errors: list[str]) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        errors.append(f"{label} is missing")
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        errors.append(f"{label} is not an ISO datetime")
        return None
    if parsed.tzinfo is None:
        errors.append(f"{label} must include timezone/offset")
        return None
    return parsed


def normalize_coverage_boundary(value: datetime, granularity: str, tz: ZoneInfo) -> datetime:
    local = value.astimezone(tz)
    if granularity == "instant":
        normalized = local
    elif granularity == "hour":
        normalized = local.replace(minute=0, second=0, microsecond=0)
    elif granularity == "day":
        normalized = local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif granularity == "month":
        normalized = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif granularity == "year":
        normalized = local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        return value.astimezone(UTC)
    return normalized.astimezone(UTC)


def validate_coverage_boundary_probe(
    control: dict,
    *,
    tier: str,
    granularity: str,
    label: str,
    errors: list[str],
) -> None:
    probe = control.get("boundary_probe")
    if not isinstance(probe, dict):
        errors.append(f"{label} coverage tier {tier} lacks boundary_probe")
        return
    timezone_name = str(probe.get("timezone") or "").strip()
    if not timezone_name:
        errors.append(f"{label} coverage tier {tier} boundary_probe lacks timezone")
        return
    try:
        tz = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        errors.append(f"{label} coverage tier {tier} has unknown timezone {timezone_name!r}")
        return

    cutoff = parse_aware_datetime(probe.get("cutoff_input"), f"{label} cutoff_input", errors)
    requested = parse_aware_datetime(probe.get("requested_from"), f"{label} requested_from", errors)
    purge = parse_aware_datetime(probe.get("purge_boundary"), f"{label} purge_boundary", errors)
    query = parse_aware_datetime(probe.get("query_boundary"), f"{label} query_boundary", errors)
    reported = parse_aware_datetime(
        probe.get("reported_available_from"), f"{label} reported_available_from", errors
    )
    if None in {cutoff, requested, purge, query, reported}:
        return
    assert cutoff is not None and requested is not None and purge is not None and query is not None and reported is not None

    normalized = normalize_coverage_boundary(cutoff, granularity, tz)
    purge_utc = purge.astimezone(UTC)
    query_utc = query.astimezone(UTC)
    reported_utc = reported.astimezone(UTC)
    requested_utc = requested.astimezone(UTC)
    cutoff_utc = cutoff.astimezone(UTC)

    if purge_utc != normalized:
        errors.append(f"{label} coverage tier {tier} purge_boundary differs from normalized retention boundary")
    if query_utc != normalized:
        errors.append(f"{label} coverage tier {tier} query_boundary differs from normalized retention boundary")

    if granularity != "instant":
        if cutoff_utc == normalized:
            errors.append(f"{label} coverage tier {tier} boundary_probe must use an off-boundary cutoff_input")
        if requested_utc != normalized:
            errors.append(f"{label} coverage tier {tier} requested_from must equal the normalized retained bucket boundary")
        expected_available = normalized
        expected_state = "complete"
    else:
        expected_available = max(requested_utc, normalized)
        expected_state = "complete" if requested_utc >= normalized else "partial"

    if reported_utc != expected_available:
        errors.append(f"{label} coverage tier {tier} reported_available_from differs from effective retained/query boundary")
    state = str(probe.get("reported_state") or "").strip().lower()
    if state != expected_state:
        errors.append(
            f"{label} coverage tier {tier} reported_state must be {expected_state} for the discriminant boundary probe"
        )


def validate_reporting_coverage_contract(
    item: dict,
    *,
    rid: str,
    expected_tiers: list[dict],
    negative_controls: list[object],
    errors: list[str],
) -> None:
    contract = item.get("coverage_contract")
    if not isinstance(contract, dict):
        errors.append(f"requirement {rid} reporting coverage over retained data requires coverage_contract")
        return
    entrypoint = str(contract.get("reporting_entrypoint") or "").strip()
    if len(entrypoint) < 5:
        errors.append(f"requirement {rid} coverage_contract lacks reporting_entrypoint")

    entries = contract.get("retained_tiers")
    if not isinstance(entries, list):
        errors.append(f"requirement {rid} coverage_contract retained_tiers must be an array")
        return
    by_tier = {
        str(entry.get("tier") or "").strip(): entry
        for entry in entries if isinstance(entry, dict) and str(entry.get("tier") or "").strip()
    }
    expected_by_tier = {str(entry["tier"]): str(entry["granularity"]) for entry in expected_tiers}
    missing = sorted(set(expected_by_tier) - set(by_tier))
    if missing:
        errors.append(f"requirement {rid} coverage_contract omits retained tiers: {missing}")

    controls_by_id = {
        str(control.get("id") or "").strip(): control
        for control in negative_controls
        if isinstance(control, dict) and str(control.get("id") or "").strip()
    }
    used_control_ids: set[str] = set()
    used_count = 0
    for tier, expected_granularity in expected_by_tier.items():
        entry = by_tier.get(tier)
        if not isinstance(entry, dict):
            continue
        granularity = str(entry.get("granularity") or "").strip()
        if granularity not in COVERAGE_GRANULARITIES:
            errors.append(f"requirement {rid} coverage tier {tier} has invalid granularity {granularity or '?'}")
        elif granularity != expected_granularity:
            errors.append(
                f"requirement {rid} coverage tier {tier} granularity differs from retention source: "
                f"expected {expected_granularity}, observed {granularity}"
            )
        applicability = str(entry.get("applicability") or "").strip()
        reason = str(entry.get("reason") or "").strip()
        if applicability not in {"used", "not-used"}:
            errors.append(f"requirement {rid} coverage tier {tier} applicability must be used or not-used")
            continue
        if len(reason) < 12:
            errors.append(f"requirement {rid} coverage tier {tier} lacks applicability reason")
        validate_meaningful_text(reason, f"requirement {rid} coverage tier {tier} reason", errors)
        control_id = str(entry.get("control_id") or "").strip()
        if applicability == "not-used":
            if control_id:
                errors.append(f"requirement {rid} unused coverage tier {tier} must not declare control_id")
            continue

        used_count += 1
        if not control_id:
            errors.append(f"requirement {rid} used coverage tier {tier} lacks dedicated control_id")
            continue
        if control_id in used_control_ids:
            errors.append(f"requirement {rid} coverage tiers reuse control_id {control_id}; each tier requires a dedicated control")
            continue
        used_control_ids.add(control_id)
        control = controls_by_id.get(control_id)
        if not isinstance(control, dict):
            errors.append(f"requirement {rid} coverage tier {tier} references unknown control_id {control_id}")
            continue
        if str(control.get("risk_family") or "") != "temporal-consistency" or str(control.get("surface") or "") != "reporting-availability-window":
            errors.append(f"requirement {rid} coverage tier {tier} control must target temporal-consistency:reporting-availability-window")
        if str(control.get("coverage_tier") or "").strip() != tier:
            errors.append(f"requirement {rid} coverage tier {tier} control must declare coverage_tier={tier}")
        if str(control.get("boundary_granularity") or "").strip() != granularity:
            errors.append(f"requirement {rid} coverage tier {tier} control boundary_granularity must be {granularity}")
        validate_coverage_boundary_probe(
            control, tier=tier, granularity=granularity,
            label=f"requirement {rid} control {control_id}", errors=errors,
        )
    if used_count == 0:
        errors.append(f"requirement {rid} coverage_contract marks every retained tier not-used")


def declared_surfaces(item: dict, families: set[str], errors: list[str], rid: str) -> set[tuple[str, str]]:
    raw = item.get("risk_surfaces") or []
    result: set[tuple[str, str]] = set()
    for index, entry in enumerate(raw):
        if isinstance(entry, str):
            if len(families) != 1:
                errors.append(f"requirement {rid} risk surface {index} must name risk_family when multiple families apply")
                continue
            family = next(iter(families))
            surface = entry.strip()
        elif isinstance(entry, dict):
            family = str(entry.get("risk_family") or entry.get("family") or "").strip()
            surface = str(entry.get("surface") or "").strip()
            reason = str(entry.get("reason") or "").strip()
            if len(reason) < 8:
                errors.append(f"requirement {rid} risk surface {index} lacks reason")
            validate_meaningful_text(reason, f"requirement {rid} risk surface {index} reason", errors)
        else:
            errors.append(f"requirement {rid} risk surface {index} is invalid")
            continue
        if family not in families:
            errors.append(f"requirement {rid} risk surface {index} references non-applicable family {family or '?'}")
        if not SURFACE_RE.match(surface):
            errors.append(f"requirement {rid} risk surface {index} has invalid surface {surface or '?'}")
        if family and surface:
            result.add((family, surface))
    return result


def inferred_surfaces(item: dict, families: set[str]) -> set[str]:
    if "authorization" not in families:
        return set()
    text = compact_text({
        "plausible_wrong_implementation": item.get("plausible_wrong_implementation"),
        "negative_controls": [
            {
                "failure_mode": c.get("failure_mode"),
                "plausible_wrong_implementation": c.get("plausible_wrong_implementation"),
                "procedure": c.get("procedure"),
            }
            for c in item.get("negative_controls") or [] if isinstance(c, dict)
        ],
    }).lower()
    return {
        surface
        for surface, hints in SURFACE_HINTS.items()
        if any(hint in text for hint in hints)
    }


def provenance_index(payload: dict | None, head_sha: str, errors: list[str]) -> dict[str, dict]:
    if payload is None:
        return {}
    if payload.get("schema_version") != 1:
        errors.append("evidence provenance schema_version must be 1")
    if str(payload.get("material_head_sha") or "") != head_sha:
        errors.append("evidence provenance material_head_sha does not match attack matrix head")
    items = payload.get("evidence")
    if not isinstance(items, list):
        errors.append("evidence provenance evidence must be an array")
        return {}
    result: dict[str, dict] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"evidence provenance entry {index} is invalid")
            continue
        evidence_id = str(item.get("evidence_id") or "").strip()
        if not evidence_id:
            errors.append(f"evidence provenance entry {index} lacks evidence_id")
            continue
        if evidence_id in result:
            errors.append(f"duplicate evidence provenance id {evidence_id}")
            continue
        result[evidence_id] = item
    return result


def validate_control_provenance(
    control: dict,
    head_sha: str,
    label: str,
    provenance: dict[str, dict],
    provenance_available: bool,
    errors: list[str],
) -> None:
    kind = str(control.get("evidence_kind") or "").strip()
    evidence_id = str(control.get("evidence_id") or "").strip()
    if kind and kind not in EVIDENCE_KINDS:
        errors.append(f"{label} has invalid evidence_kind")
        return
    if not kind and not evidence_id:
        return
    if evidence_id and not kind:
        errors.append(f"{label} has evidence_id without evidence_kind")
        return
    if kind == "quantitative" and not evidence_id:
        errors.append(f"{label} quantitative evidence lacks evidence_id")
        return
    if not evidence_id:
        return
    if not provenance_available:
        errors.append(f"{label} references evidence provenance but no evidence-provenance.json was supplied")
        return
    entry = provenance.get(evidence_id)
    if not entry:
        errors.append(f"{label} references unknown evidence_id {evidence_id}")
        return
    if str(entry.get("kind") or "") != kind:
        errors.append(f"{label} evidence_kind does not match provenance entry {evidence_id}")
    if entry.get("status") != "passed":
        errors.append(f"{label} provenance entry {evidence_id} is not passed")
    control_path = str(control.get("evidence_path") or control.get("evidence") or "").strip()
    provenance_path = str(entry.get("path") or "").strip()
    if control_path and provenance_path and control_path != provenance_path:
        errors.append(f"{label} evidence path does not match provenance entry {evidence_id}")
    control_sha = str(control.get("evidence_sha256") or "").strip()
    provenance_sha = str(entry.get("sha256") or "").strip()
    if kind == "quantitative":
        if not SHA256_RE.match(control_sha):
            errors.append(f"{label} quantitative evidence lacks valid evidence_sha256")
        elif control_sha != provenance_sha:
            errors.append(f"{label} evidence_sha256 does not match provenance entry {evidence_id}")
        if str(entry.get("freshness_policy") or "") != "exact-material-head":
            errors.append(f"{label} quantitative evidence is not exact-material-head")
        if str(entry.get("subject_sha") or "") != head_sha:
            errors.append(f"{label} quantitative evidence is stale for the attack matrix head")


def validate_basic_control(
    control: object,
    head_sha: str,
    label: str,
    errors: list[str],
    provenance: dict[str, dict],
    provenance_available: bool,
) -> bool:
    if not isinstance(control, dict):
        errors.append(f"{label} is missing")
        return False
    if control.get("status") != "passed":
        errors.append(f"{label} is not passed")
    if str(control.get("head_sha") or "") != head_sha:
        errors.append(f"{label} head_sha does not match attack matrix head")
    evidence = str(control.get("evidence") or control.get("evidence_path") or "").strip()
    if not evidence:
        errors.append(f"{label} lacks evidence")
    validate_control_provenance(control, head_sha, label, provenance, provenance_available, errors)
    return True


def validate_negative_control(
    control: object,
    head_sha: str,
    label: str,
    families: set[str],
    surfaces: set[tuple[str, str]],
    errors: list[str],
    require_siblings: int,
    provenance: dict[str, dict],
    provenance_available: bool,
) -> set[tuple[str, str, str]]:
    covered: set[tuple[str, str, str]] = set()
    if not validate_basic_control(control, head_sha, label, errors, provenance, provenance_available) or not isinstance(control, dict):
        return covered

    cid = str(control.get("id") or "").strip()
    family = str(control.get("risk_family") or "").strip()
    surface = str(control.get("surface") or "").strip()
    dimension = str(control.get("dimension") or "").strip()
    if not cid:
        errors.append(f"{label} lacks id")
    if family not in families:
        errors.append(f"{label} risk_family is not declared by the requirement")
    if (family, surface) not in surfaces:
        errors.append(f"{label} surface {surface or '?'} is not declared in requirement risk_surfaces")
    if len(dimension) < 3:
        errors.append(f"{label} lacks discriminant dimension")
    for key, minimum in (
        ("failure_mode", 12),
        ("plausible_wrong_implementation", 20),
        ("procedure", 12),
        ("expected", 8),
        ("observed", 8),
    ):
        value = str(control.get(key) or "").strip()
        if len(value) < minimum:
            errors.append(f"{label} lacks {key}")
        validate_meaningful_text(value, f"{label} {key}", errors)
    validate_surface_specific_control(control, label, surface, errors)
    if str(control.get("control_type") or "") not in CONTROL_TYPES:
        errors.append(f"{label} has invalid control_type")
    evidence_sha = str(control.get("evidence_sha256") or "").strip()
    if not SHA256_RE.match(evidence_sha):
        errors.append(f"{label} lacks valid evidence_sha256")

    if family and surface and dimension:
        covered.add((family, surface, dimension))

    siblings = control.get("sibling_cases") or []
    if len(siblings) < require_siblings:
        errors.append(f"{label} has fewer than {require_siblings} sibling cases")
    sibling_pairs: set[tuple[str, str]] = set()
    for index, case in enumerate(siblings):
        slabel = f"{label} sibling {index}"
        if not isinstance(case, dict):
            errors.append(f"{slabel} is invalid")
            continue
        if case.get("status") != "passed":
            errors.append(f"{slabel} is not passed")
        sid = str(case.get("id") or "").strip()
        ssurface = str(case.get("surface") or "").strip()
        sdimension = str(case.get("dimension") or "").strip()
        if not sid:
            errors.append(f"{slabel} lacks id")
        if (family, ssurface) not in surfaces:
            errors.append(f"{slabel} surface {ssurface or '?'} is not declared in requirement risk_surfaces")
        if len(sdimension) < 3:
            errors.append(f"{slabel} lacks dimension")
        if ssurface and sdimension:
            sibling_pairs.add((ssurface, sdimension))
            covered.add((family, ssurface, sdimension))
    if require_siblings and len(sibling_pairs) < require_siblings:
        errors.append(f"{label} sibling cases do not vary {require_siblings} distinct surface/dimension pairs")
    return covered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirement-closure", required=True)
    parser.add_argument("--attack-matrix", required=True)
    parser.add_argument("--evidence-provenance")
    args = parser.parse_args()

    closure = load(Path(args.requirement_closure))
    matrix = load(Path(args.attack_matrix))
    retention_tiers = retention_tiers_from_closure(closure)
    coverage_requirement_ids = coverage_requirement_ids_from_closure(closure)
    errors: list[str] = []
    head_sha = str(matrix.get("head_sha") or "")
    if matrix.get("schema_version") != 1:
        errors.append("attack matrix schema_version must be 1")
    if not SHA_RE.match(head_sha):
        errors.append("attack matrix head_sha is invalid")

    provenance_payload = load(Path(args.evidence_provenance)) if args.evidence_provenance else None
    provenance = provenance_index(provenance_payload, head_sha, errors)
    provenance_available = provenance_payload is not None

    required: set[str] = set()
    closure_source_texts: dict[str, list[str]] = {}
    for obligation in closure.get("obligations") or []:
        if not isinstance(obligation, dict) or obligation.get("disposition") != "covered":
            continue
        source_text = str(obligation.get("source_text") or "").strip()
        for value in obligation.get("requirement_ids") or []:
            rid = str(value)
            required.add(rid)
            if source_text:
                closure_source_texts.setdefault(rid, []).append(source_text)

    obligation_by_id = {
        str(obligation.get("id") or ""): obligation
        for obligation in closure.get("obligations") or []
        if isinstance(obligation, dict) and str(obligation.get("id") or "")
    }
    obligations_by_requirement: dict[str, set[str]] = {}
    for oid, obligation in obligation_by_id.items():
        if obligation.get("disposition") != "covered":
            continue
        for requirement_id in obligation.get("requirement_ids") or []:
            obligations_by_requirement.setdefault(str(requirement_id), set()).add(oid)

    entries = matrix.get("requirements") or []
    by_id = {str(item.get("requirement_id")): item for item in entries if isinstance(item, dict)}

    documentation = closure.get("documentation_consistency") or {}
    if documentation.get("status") == "passed":
        documentation_requirements = [
            item for item in entries
            if isinstance(item, dict)
            and str(item.get("requirement_id") or "") in required
            and "documentation" in {str(value) for value in item.get("risk_families") or []}
        ]
        if not documentation_requirements:
            errors.append("documentation consistency passed but attack matrix omits documentation risk family")
        else:
            documentation_surfaces = {
                str(surface.get("surface") or "").strip()
                for item in documentation_requirements
                for surface in item.get("risk_surfaces") or []
                if isinstance(surface, dict)
                and str(surface.get("risk_family") or surface.get("family") or "") == "documentation"
                and str(surface.get("surface") or "").strip()
            }
            if not documentation_surfaces:
                errors.append("documentation consistency passed but attack matrix has no documentation risk surface")

    missing = sorted(required - set(by_id))
    if missing:
        errors.append(f"attack matrix does not cover requirements: {missing}")
    if matrix.get("uncovered_requirements"):
        errors.append("attack matrix has uncovered_requirements")

    for rid in sorted(required & set(by_id)):
        item = by_id[rid]
        expected_obligation_ids = obligations_by_requirement.get(rid, set())
        declared_obligation_ids = {str(value) for value in item.get("obligation_ids") or []}
        if (len(expected_obligation_ids) > 1 or "obligation_ids" in item) and declared_obligation_ids != expected_obligation_ids:
            errors.append(
                f"requirement {rid} obligation_ids differ from requirement closure; "
                f"missing={sorted(expected_obligation_ids-declared_obligation_ids)}, "
                f"extra={sorted(declared_obligation_ids-expected_obligation_ids)}"
            )
        wrong = str(item.get("plausible_wrong_implementation") or "").strip()
        if len(wrong) < 20:
            errors.append(f"requirement {rid} lacks plausible wrong implementation")
        validate_meaningful_text(wrong, f"requirement {rid} plausible wrong implementation", errors)
        families = {str(value) for value in item.get("risk_families") or []}
        if not families:
            errors.append(f"requirement {rid} has no risk families")
        canonical_source_texts = closure_source_texts.get(rid) or [str(value) for value in item.get("source_texts") or []]
        source_item = {**item, "source_texts": canonical_source_texts}
        required_families = source_required_families(source_item)
        omitted_families = sorted(required_families - families)
        if omitted_families:
            errors.append(f"requirement {rid} omits risk families rederived from source text: {omitted_families}")

        surfaces = declared_surfaces(item, families, errors, rid)
        if not surfaces:
            errors.append(f"requirement {rid} has no risk_surfaces")
        required_from_source = source_required_surfaces(source_item)
        omitted_source_surfaces = sorted(f"{family}:{surface}" for family, surface in required_from_source - surfaces)
        if omitted_source_surfaces:
            errors.append(f"requirement {rid} omits risk surfaces rederived from source text: {omitted_source_surfaces}")
        declared_surface_names = {surface for _, surface in surfaces}
        detected = inferred_surfaces(item, families)
        omitted_detected = sorted(detected - declared_surface_names)
        if omitted_detected:
            errors.append(f"requirement {rid} omits inferred risk surfaces: {omitted_detected}")

        performance_required = required_performance_surfaces(source_item)
        if performance_required and "structural-contract" not in families:
            errors.append(f"requirement {rid} performance signals require structural-contract risk family")
        missing_performance = sorted(f"{family}:{surface}" for family, surface in performance_required - surfaces)
        if missing_performance:
            errors.append(f"requirement {rid} omits required performance risk surfaces: {missing_performance}")
        validate_performance_contract(source_item, rid, head_sha, performance_required, errors)

        if required_evidence_effect_surface(source_item):
            if "authorization" not in families:
                errors.append(f"requirement {rid} evidence-effect language requires authorization risk family")
            if ("authorization", "evidence-effect-scope") not in surfaces:
                errors.append(f"requirement {rid} omits required evidence-effect-scope risk surface")

        validate_quantitative_requirement(source_item, rid, provenance_available, errors)
        validate_basic_control(
            item.get("positive_control"), head_sha, f"requirement {rid} positive control", errors,
            provenance, provenance_available,
        )
        negative = item.get("negative_controls") or []
        if not negative:
            errors.append(f"requirement {rid} has no negative controls")
        sibling_min = 2 if HIGH_RISK.intersection(families) else 1
        covered: set[tuple[str, str, str]] = set()
        primary_surface_pairs: set[tuple[str, str]] = set()
        for index, control in enumerate(negative):
            covered.update(validate_negative_control(
                control, head_sha, f"requirement {rid} negative control {index}", families, surfaces,
                errors, sibling_min, provenance, provenance_available,
            ))
            if isinstance(control, dict):
                primary_surface_pairs.add((str(control.get("risk_family") or ""), str(control.get("surface") or "")))
                if (str(control.get("risk_family") or ""), str(control.get("surface") or "")) == ("tenant-isolation", "tenant-scope-isolation"):
                    validate_tenant_scope_isolation_control(control, f"requirement {rid} negative control {index}", errors)
                if (str(control.get("risk_family") or ""), str(control.get("surface") or "")) == ("structural-contract", "semantic-identity-propagation"):
                    validate_semantic_identity_control(control, source_item, f"requirement {rid} negative control {index}", errors)
                if (str(control.get("risk_family") or ""), str(control.get("surface") or "")) == ("structural-contract", "relational-semantic-integrity"):
                    validate_relational_semantic_integrity_control(control, f"requirement {rid} negative control {index}", errors)

        if len(expected_obligation_ids) > 1:
            validate_obligation_control_map(
                item, rid=rid, expected_obligation_ids=expected_obligation_ids,
                obligation_by_id=obligation_by_id, negative_controls=negative, errors=errors,
            )
        validate_test_coverage_contract(item, rid=rid, negative_controls=negative, errors=errors)

        missing_surfaces = sorted(f"{family}:{surface}" for family, surface in surfaces - primary_surface_pairs)
        if missing_surfaces:
            errors.append(f"requirement {rid} has risk surfaces without adversarial coverage: {missing_surfaces}")

        if rid in coverage_requirement_ids and retention_tiers:
            validate_reporting_coverage_contract(
                item, rid=rid, expected_tiers=retention_tiers,
                negative_controls=negative, errors=errors,
            )

        if HIGH_RISK.intersection(families) and len(surfaces) > 1:
            distinct_surfaces = {surface for _, surface, _ in covered}
            if len(distinct_surfaces) < 2:
                errors.append(f"requirement {rid} high-risk controls do not cross surfaces")

        if ("authorization", "evidence-effect-scope") in surfaces:
            validate_evidence_effect_scope_controls(source_item, errors, rid)

        regression = item.get("regression_controls") or []
        if not regression:
            errors.append(f"requirement {rid} has no regression controls")
        for index, control in enumerate(regression):
            validate_basic_control(
                control, head_sha, f"requirement {rid} regression control {index}", errors,
                provenance, provenance_available,
            )

    if errors:
        for error in errors:
            print(f"BLOCK: {error}")
        return 2
    print("READY: every covered requirement has cross-surface adversarial, regression, and evidence-provenance closure")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
