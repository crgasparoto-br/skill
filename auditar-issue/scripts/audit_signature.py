from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

REJECTION_ID_RE = re.compile(r"^audit-rejection:[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
SOLO_ASSURANCE_MODE = "single-operator-separate-context"
SOLO_ISSUE_BODY_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
EXACT_REPOSITORY_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
SOLO_FIELDS = frozenset({"operator_github_id", "pull_request", "issue_body_sha256"})


def _parse_time(value: object, label: str, errors: list[str]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        errors.append(f"{label} is not a valid ISO-8601 timestamp")
        return None


def _assurance_mode_errors(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    assurance_mode = report.get("assurance_mode")
    if "assurance_mode" in report and assurance_mode != SOLO_ASSURANCE_MODE:
        errors.append("unknown assurance_mode")
    if assurance_mode == SOLO_ASSURANCE_MODE:
        if report.get("independent") is not False:
            errors.append("solo assurance mode must set independent=false")
        if report.get("same_conversation") is not False:
            errors.append("solo assurance mode must set same_conversation=false")
        for field in ("operator_github_id", "pull_request"):
            value = report.get(field)
            if type(value) is not int or value < 1:
                errors.append(f"solo {field} must be a positive integer")
        issue_body_sha256 = report.get("issue_body_sha256")
        if not isinstance(issue_body_sha256, str) or not SOLO_ISSUE_BODY_SHA256_RE.fullmatch(issue_body_sha256):
            errors.append("solo issue_body_sha256 must be lowercase SHA-256")
        if report.get("verdict") != "approved":
            errors.append("solo assurance mode requires an approved verdict")
        for field in ("findings", "recommendations", "limitations"):
            if report.get(field) != []:
                errors.append(f"solo assurance mode requires empty {field}")
    elif any(field in report for field in SOLO_FIELDS):
        errors.append("solo fields require assurance_mode=single-operator-separate-context")
    return errors


def _context_errors(report: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if report.get("audit_context_id") == report.get("implementation_context_id"):
        errors.append("audit context must differ from implementation context")
    proof = report.get("source_context_proof")
    if not isinstance(proof, dict):
        errors.append("source_context_proof is required")
        proof = {}
    if proof.get("value") != report.get("audit_context_id"):
        errors.append("source context proof must equal audit_context_id")
    return errors, proof


def _sha_lineage_errors(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("head_sha", "base_sha", "merge_preview_sha"):
        if report.get(field) != report.get(f"{field}_after"):
            errors.append(f"{field}_after must equal {field}")
    return errors


def _verdict_errors(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("verdict") == "approved" and (report.get("findings") or report.get("limitations")):
        errors.append("approved report cannot contain findings or limitations")
    rejection_id = report.get("rejection_id")
    if report.get("verdict") == "rejected":
        if not isinstance(rejection_id, str) or not REJECTION_ID_RE.fullmatch(rejection_id):
            errors.append("rejected independent audit requires stable rejection_id")
    elif rejection_id is not None:
        errors.append("non-rejected audit must not carry rejection_id")
    return errors


def _rejection_lineage_errors(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    rejection_id = report.get("rejection_id")
    lineage = report.get("rejection_lineage")
    if isinstance(lineage, dict):
        mode = lineage.get("mode")
        previous = lineage.get("previous_rejection_id")
        if mode == "continuation":
            if previous != rejection_id:
                errors.append("continued rejection must reuse previous_rejection_id as rejection_id")
            if not lineage.get("continued_finding_ids"):
                errors.append("continued rejection requires continued_finding_ids")
        elif mode == "new" and previous == rejection_id and previous is not None:
            errors.append("new rejection must not silently reuse previous_rejection_id")
    return errors


def _neutral_packet_errors(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    packet = report.get("neutral_packet")
    if not isinstance(packet, dict):
        errors.append("neutral_packet is required")
        return errors
    if packet.get("implementation_conclusions_included") is not False:
        errors.append("neutral packet must exclude implementation conclusions")
    if packet.get("implementation_narrative_included") is not False:
        errors.append("neutral packet must exclude implementation narrative")
    return errors


def _item_ids(items: object) -> list[Any]:
    return [item.get("id") for item in items if isinstance(item, dict)]


def _evidence_errors(report: dict[str, Any]) -> list[str]:
    evidence = report.get("evidence") or []
    evidence_ids = _item_ids(evidence)
    if len(evidence_ids) != len(set(evidence_ids)):
        return ["external audit evidence IDs must be unique"]
    return []


def _approval_finding_errors(report: dict[str, Any], findings: object) -> list[str]:
    errors: list[str] = []
    prior = report.get("prior_internal_approval")
    if isinstance(prior, dict) and prior.get("head_sha") == report.get("head_sha") and findings:
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("audit_escape") is not True:
                errors.append("findings against a previously internally approved SHA must be audit escapes")
                break
            mode = str(finding.get("remediation_mode") or "")
            if mode not in {"targeted-remediation", "systemic-remediation"}:
                errors.append("audit finding requires remediation_mode")
                break
            if mode == "systemic-remediation":
                if not finding.get("reusable_control_requirement"):
                    errors.append("systemic audit escape requires reusable_control_requirement")
                    break
                if len(finding.get("sibling_cases") or []) < 2:
                    errors.append("systemic audit escape requires at least two sibling cases")
                    break
    elif any(isinstance(finding, dict) and finding.get("audit_escape") is True for finding in findings):
        errors.append("audit_escape requires prior_internal_approval for the same head SHA")
    return errors


def _failed_gate_errors(findings: object) -> list[str]:
    errors: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        gate = finding.get("failed_gate")
        if gate is None:
            continue
        if not isinstance(gate, dict) or gate.get("deterministic") is not True:
            errors.append("failed_gate must describe a deterministic gate")
            break
        if not str(gate.get("command") or "").strip():
            errors.append("failed_gate requires the exact failing command")
            break
        if gate.get("observed_exit_code") == 0:
            errors.append("failed_gate observed_exit_code must be non-zero")
            break
        if not re.fullmatch(r"[0-9a-f]{64}", str(gate.get("evidence_sha256") or ""), re.IGNORECASE):
            errors.append("failed_gate requires evidence_sha256")
            break
    return errors


def _finding_recommendation_errors(findings: object, recommendations: object) -> list[str]:
    errors: list[str] = []
    finding_ids = _item_ids(findings)
    if len(finding_ids) != len(set(finding_ids)):
        errors.append("external audit finding IDs must be unique")
    recommendation_ids = _item_ids(recommendations)
    if len(recommendation_ids) != len(set(recommendation_ids)):
        errors.append("external audit recommendation IDs must be unique")
    overlap = set(finding_ids) & set(recommendation_ids)
    if overlap:
        errors.append("finding/recommendation IDs must be globally unique")
    for item in recommendations:
        if not isinstance(item, dict) or not isinstance(item.get("actionable"), bool):
            errors.append("audit recommendation requires actionable boolean")
            break
        if item.get("remediation_mode") not in {"targeted-remediation", "systemic-remediation"}:
            errors.append("audit recommendation requires remediation_mode")
            break
    return errors


def _timestamp_errors(
    report: dict[str, Any], proof: dict[str, Any]
) -> tuple[list[str], datetime | None]:
    errors: list[str] = []
    issued_at = _parse_time(report.get("issued_at"), "issued_at", errors)
    proof_issued_at = _parse_time(proof.get("issued_at"), "source_context_proof.issued_at", errors)
    if issued_at and proof_issued_at and proof_issued_at > issued_at:
        errors.append("source context proof cannot be issued after the audit report")
    return errors, issued_at


def _signature_semantic_errors(
    report: dict[str, Any], issued_at: datetime | None, *, require_signature: bool
) -> list[str]:
    errors: list[str] = []
    signature = report.get("signature")
    if require_signature and not isinstance(signature, dict):
        errors.append("signature is required")
    if isinstance(signature, dict):
        signed_at = _parse_time(signature.get("signed_at"), "signature.signed_at", errors)
        if issued_at and signed_at and signed_at < issued_at:
            errors.append("signature cannot predate the audit report")
    return errors


def report_semantic_errors(report: dict[str, Any], *, require_signature: bool) -> list[str]:
    errors: list[str] = []
    errors.extend(_assurance_mode_errors(report))
    context_errors, proof = _context_errors(report)
    errors.extend(context_errors)
    errors.extend(_sha_lineage_errors(report))
    errors.extend(_verdict_errors(report))
    errors.extend(_rejection_lineage_errors(report))
    errors.extend(_neutral_packet_errors(report))
    errors.extend(_evidence_errors(report))
    findings = report.get("findings") or []
    errors.extend(_approval_finding_errors(report, findings))
    errors.extend(_failed_gate_errors(findings))
    recommendations = report.get("recommendations") or []
    errors.extend(_finding_recommendation_errors(findings, recommendations))
    timestamp_errors, issued_at = _timestamp_errors(report, proof)
    errors.extend(timestamp_errors)
    errors.extend(_signature_semantic_errors(report, issued_at, require_signature=require_signature))
    return errors


def canonical_report_bytes(report: dict[str, Any]) -> bytes:
    payload = deepcopy(report)
    payload.pop("signature", None)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sign_report(report: dict[str, Any], private_key_pem: bytes, password: bytes | None, key_id: str, signed_at: str) -> None:
    private_key = serialization.load_pem_private_key(private_key_pem, password=password)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("private key must be Ed25519")
    canonical = canonical_report_bytes(report)
    signature = private_key.sign(canonical)
    report["signature"] = {
        "algorithm": "ed25519",
        "key_id": key_id,
        "signed_payload_sha256": sha256_bytes(canonical),
        "value_base64": base64.b64encode(signature).decode("ascii"),
        "signed_at": signed_at,
    }


def _registry_key_id_errors(registry: dict[str, Any]) -> list[str]:
    key_ids = [
        item.get("key_id")
        for item in registry.get("auditors", [])
        if isinstance(item, dict) and isinstance(item.get("key_id"), str)
    ]
    if len(key_ids) != len(set(key_ids)):
        return ["trusted auditor key IDs must be unique"]
    return []


def _enabled_auditor(registry: dict[str, Any], key_id: object) -> dict[str, Any] | None:
    return next(
        (
            item
            for item in registry.get("auditors", [])
            if isinstance(item, dict)
            and item.get("key_id") == key_id
            and item.get("enabled") is True
        ),
        None,
    )


def _exact_repository_errors(repository: str, repositories: object) -> list[str]:
    errors: list[str] = []
    if EXACT_REPOSITORY_RE.fullmatch(repository) is None:
        errors.append("exact repository authorization requires valid owner/repo syntax")
    if not isinstance(repositories, list) or not all(isinstance(pattern, str) for pattern in repositories):
        errors.append("trusted auditor repository scope is malformed")
    elif any(any(char in pattern for char in "*?[]") for pattern in repositories):
        errors.append("exact repository authorization forbids wildcard or glob entries")
    elif any(EXACT_REPOSITORY_RE.fullmatch(pattern) is None for pattern in repositories):
        errors.append("exact repository authorization requires literal owner/repo entries")
    elif len(repositories) != len(set(repositories)):
        errors.append("exact repository authorization has duplicate owner/repo entries")
    elif repository not in repositories:
        errors.append(f"auditor key is not authorized for repository {repository}")
    return errors


def _repository_authorization_errors(
    repository: str, repositories: object, *, exact_repository_only: bool
) -> list[str]:
    if exact_repository_only:
        return _exact_repository_errors(repository, repositories)
    if not any(pattern == "*" or fnmatch.fnmatchcase(repository, str(pattern)) for pattern in repositories):
        return [f"auditor key is not authorized for repository {repository}"]
    return []


def _payload_hash_errors(report: dict[str, Any], signature: dict[str, Any]) -> tuple[list[str], bytes]:
    canonical = canonical_report_bytes(report)
    if signature.get("signed_payload_sha256") != sha256_bytes(canonical):
        return ["signed_payload_sha256 mismatch"], canonical
    return [], canonical


def _cryptographic_signature_errors(
    signature: dict[str, Any], auditor: dict[str, Any], canonical: bytes
) -> list[str]:
    errors: list[str] = []
    if signature.get("algorithm") != "ed25519":
        errors.append("signature algorithm must be ed25519")
    try:
        raw = base64.b64decode(str(signature.get("value_base64") or ""), validate=True)
        public_key = serialization.load_pem_public_key(str(auditor.get("public_key_pem") or "").encode("utf-8"))
        if not isinstance(public_key, Ed25519PublicKey):
            errors.append("trusted public key must be Ed25519")
        else:
            public_key.verify(raw, canonical)
    except InvalidSignature:
        errors.append("signature verification failed")
    except Exception as exc:
        errors.append(f"invalid signature or public key: {exc}")
    return errors


def _fingerprint_errors(auditor: dict[str, Any]) -> list[str]:
    expected_fingerprint = auditor.get("public_key_sha256")
    actual_fingerprint = sha256_bytes(str(auditor.get("public_key_pem") or "").encode("utf-8"))
    if expected_fingerprint != actual_fingerprint:
        return ["public key fingerprint mismatch"]
    return []


def verify_report(
    report: dict[str, Any],
    registry: dict[str, Any],
    *,
    exact_repository_only: bool = False,
) -> list[str]:
    """Verify an Ed25519 report against a trusted registry.

    Wildcard repository entries remain compatible for existing callers.  The
    explicit exact mode is used by the solo adapter and rejects every
    non-exact or glob authorization entry for the selected key.
    """
    errors = _registry_key_id_errors(registry)
    signature = report.get("signature")
    if not isinstance(signature, dict):
        return ["signature is required"]
    key_id = signature.get("key_id")
    auditor = _enabled_auditor(registry, key_id)
    if not isinstance(auditor, dict):
        return [f"untrusted auditor key: {key_id}"]
    repository = str(report.get("repository") or "")
    repositories = auditor.get("repositories", [])
    errors.extend(
        _repository_authorization_errors(
            repository, repositories, exact_repository_only=exact_repository_only
        )
    )
    payload_hash_errors, canonical = _payload_hash_errors(report, signature)
    errors.extend(payload_hash_errors)
    errors.extend(_cryptographic_signature_errors(signature, auditor, canonical))
    errors.extend(_fingerprint_errors(auditor))
    return errors
