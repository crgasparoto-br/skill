"""Validate redacted, independently collected live release evidence.

Usage: python verify_release_evidence.py /path/to/redacted-evidence.json <exact-pr-head> <lockfile> <observed-deployed-image-digest>
The JSON is supplied by the operator; this script never logs in or manufactures evidence.
"""
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

CASES = (
    "authorized_develop", "authorized_main", "unauthorized_discovery",
    "unauthorized_all_tools", "unauthorized_zero_github_calls",
    "blocked_repository", "blocked_branch", "restart_authorized",
    "restart_unauthorized", "token_expiry", "credential_rotation",
)
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
FORBIDDEN_KEYS = re.compile(r"(secret|password|private.key|authorization|access.token|refresh.token|oauth.code|client.secret)", re.IGNORECASE)


def validate(document, expected_head, *, lock_path=None, deployed_image_digest=None):
    errors = []
    if not SHA.fullmatch(expected_head):
        return ["expected HEAD must be a full 40-character lowercase SHA"]
    if not isinstance(document, dict):
        return ["evidence must be a JSON object"]
    if document.get("pr_head") != expected_head:
        errors.append("evidence HEAD differs from expected PR HEAD")
    digest = document.get("image_digest")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        errors.append("image_digest must be a sha256 digest")
    if not isinstance(document.get("dependency_lock_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", document["dependency_lock_sha256"]):
        errors.append("dependency_lock_sha256 must be a 64-character lowercase hex hash")
    if lock_path is not None:
        try:
            actual_lock_hash = hashlib.sha256(Path(lock_path).read_bytes()).hexdigest()
        except OSError:
            errors.append("dependency lock file is unreadable")
        else:
            if document.get("dependency_lock_sha256") != actual_lock_hash:
                errors.append("dependency lock hash differs from audited file")
    if deployed_image_digest is not None:
        if not DIGEST.fullmatch(deployed_image_digest):
            errors.append("deployed image digest argument must be sha256:<64-hex>")
        elif digest != deployed_image_digest:
            errors.append("deployed image digest differs from evidence")
    cases = document.get("cases")
    if not isinstance(cases, dict):
        errors.append("cases must be an object")
        cases = {}
    for name in CASES:
        item = cases.get(name)
        if not isinstance(item, dict) or item.get("result") != "PASS" or item.get("kind") != "LIVE":
            errors.append(f"{name}: required LIVE PASS evidence missing")
            continue
        if not isinstance(item.get("timestamp_utc"), str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", item["timestamp_utc"]):
            errors.append(f"{name}: timestamp_utc must be RFC3339 UTC seconds")
        if isinstance(item.get("timestamp_utc"), str):
            try:
                observed_time = datetime.strptime(item["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
                if observed_time > datetime.now(UTC):
                    errors.append(f"{name}: timestamp cannot be in the future")
            except ValueError:
                errors.append(f"{name}: timestamp is not a valid UTC date")
        if not isinstance(item.get("evidence_reference"), str) or not item["evidence_reference"].strip():
            errors.append(f"{name}: evidence_reference required")
    def inspect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if FORBIDDEN_KEYS.search(str(key)):
                    errors.append("credential-related field is forbidden in evidence")
                inspect(child)
        elif isinstance(value, list):
            for child in value:
                inspect(child)
    inspect(document)
    return errors


def main(argv):
    if len(argv) != 5:
        print("Usage: python verify_release_evidence.py evidence.json <40-char-pr-head> <lockfile-path> <deployed-image-digest>", file=sys.stderr)
        return 2
    try:
        data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Unable to load evidence: {type(exc).__name__}", file=sys.stderr)
        return 2
    errors = validate(data, argv[2], lock_path=argv[3], deployed_image_digest=argv[4])
    for error in errors:
        print("NOT VALIDATED:", error)
    if errors:
        return 1
    print("Evidence structure verified. Independent review and factual verification still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
