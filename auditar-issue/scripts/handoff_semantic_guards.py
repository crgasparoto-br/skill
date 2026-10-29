from __future__ import annotations

import re
from typing import Any

SHA40_RE = re.compile(r"\b[0-9a-f]{40}\b", re.IGNORECASE)
CURRENT_CLAIM_RE = re.compile(
    r"\b(?:active|current|candidate|material(?:\s+head)?|frozen|exact[- ]head|"
    r"subject_sha|candidateSha|revalidated_head_sha|atual|corrente|candidato|"
    r"head material|congelad[oa]|evid[eê]ncia ativa)\b",
    re.IGNORECASE,
)
HISTORICAL_CLAIM_RE = re.compile(
    r"\b(?:historical|historic|stale|ancestor|previous|prior|superseded|retired|"
    r"old|before|hist[oó]ric[oa]?|ancestral|anterior|obsolet[oa]|superseded|"
    r"substitu[ií]d[oa]|aposentad[oa])\b",
    re.IGNORECASE,
)
READ_MODEL_PATTERN = re.compile(
    r"\b(history|historical|timeline|version|versioning|pagination|authorship|origin|supersession|vigency|previous records|"
    r"hist[oó]ric\w*|linha do tempo|vers[aã]o|vers[oõ]es|pagina[cç][aã]o|autoria|origem|supersess[aã]o|vig[eê]ncia|registros anteriores)\b",
    re.IGNORECASE,
)
CANONICAL_PATTERN = re.compile(
    r"\b(canonical|source of truth|consistent|coherent|can[oô]nic\w*|fonte de verdade|consisten\w*|coeren\w*)\b",
    re.IGNORECASE,
)
DOC_TRANSITION_PATTERN = re.compile(
    r"\b(route|redirect|legacy|deprecated|retire|replace|rename|workspace|rota|redirecion\w*|legado|obsoleto|aposent\w*|substitu\w*|renome\w*|"
    r"authoriz\w*|permission\w*|role|capabilit\w*|entitlement\w*|allow|deny|default|preset|feature[ -]?flag|seed|provision\w*|trigger|"
    r"autoriz\w*|permiss\w*|papel|fun[cç][aã]o|capacidade|concess[aã]o|acesso|permit\w*|negad\w*|padr[aã]o|provision\w*|seme\w*|gatilho)\b",
    re.IGNORECASE,
)

TERMINAL_CLOSURE_GATES = (
    "structural_invariant_closures",
    "read_model_closures",
    "canonical_source_consistency",
    "documentation_consistency",
)
STRUCTURAL_FLAGS = {
    "structural", "forbidden-implementation", "canonical-path",
    "dependency-independence", "precedence",
}


def _terminal_gate_inference(closure: dict[str, Any]) -> dict[str, bool]:
    obligations = [item for item in closure.get("obligations") or [] if isinstance(item, dict)]
    obligation_text = "\n".join(str(item.get("source_text") or "") for item in obligations)
    structural = any(
        item.get("disposition") == "covered" and STRUCTURAL_FLAGS.intersection(item.get("flags") or [])
        for item in obligations
    )
    return {
        "structural_invariant_closures": structural,
        "read_model_closures": bool(READ_MODEL_PATTERN.search(obligation_text)),
        "canonical_source_consistency": bool(CANONICAL_PATTERN.search(obligation_text)),
        "documentation_consistency": bool(DOC_TRANSITION_PATTERN.search(obligation_text)),
    }


def validate_terminal_requirement_closure(closure: dict[str, Any], errors: list[str]) -> None:
    """Reject unfinished or unjustifiably bypassed semantic closure before handoff."""
    inferred = _terminal_gate_inference(closure)
    for key in TERMINAL_CLOSURE_GATES:
        gate = closure.get(key)
        if not isinstance(gate, dict):
            errors.append(f"{key} gate is missing from requirement closure")
            continue
        status = str(gate.get("status") or "").strip()
        reason = str(gate.get("applicability_reason") or "").strip()
        if status == "pending":
            errors.append(f"{key} gate is still pending")
        elif status == "not-applicable":
            if inferred.get(key) is True:
                errors.append(f"{key} gate cannot be not-applicable for the canonical contract")
            if len(reason) < 20:
                errors.append(f"{key} not-applicable decision requires an objective rationale")
        elif status == "passed":
            if len(reason) < 12:
                errors.append(f"{key} passed gate requires an applicability rationale")
        else:
            errors.append(f"{key} gate has invalid terminal status {status or '<empty>'}")

    scope = closure.get("scope_reduction_review")
    if not isinstance(scope, dict):
        errors.append("scope_reduction_review gate is missing from requirement closure")
    elif scope.get("status") != "passed":
        errors.append("scope_reduction_review is not passed")

    pass_c = closure.get("pass_c")
    if not isinstance(pass_c, dict):
        errors.append("pass_c gate is missing from requirement closure")
    elif pass_c.get("status") != "passed":
        errors.append("pass_c is not passed")


def conflicting_current_sha_claims(text: object, expected_sha: str) -> list[str]:
    """Return non-current SHAs asserted as current/exact-head facts in narrative evidence."""
    raw = str(text or "")
    expected = str(expected_sha or "").lower()
    if not expected or not SHA40_RE.fullmatch(expected):
        return []

    clause_split = re.compile(
        r"[;\n]|(?<=[.!?])\s+|,?\s+(?:but|however|whereas|while|mas|por[eé]m|contudo|enquanto)\s+",
        re.IGNORECASE,
    )
    conflicts: list[str] = []
    segments = [segment.strip() for segment in clause_split.split(raw) if segment.strip()]
    for segment in segments:
        shas = {match.group(0).lower() for match in SHA40_RE.finditer(segment)}
        foreign = sorted(sha for sha in shas if sha != expected)
        if not foreign:
            continue
        if CURRENT_CLAIM_RE.search(segment) and not HISTORICAL_CLAIM_RE.search(segment):
            conflicts.extend(foreign)
    return sorted(set(conflicts))
