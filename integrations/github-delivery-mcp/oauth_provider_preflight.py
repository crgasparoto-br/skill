"""Validate OAuth AS discovery metadata before enabling the MCP service.

Reads a locally saved JSON discovery document. Does not access the network,
provision infrastructure, accept secrets or enable the service.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit


def _https_url(value: object, *, allow_query: bool = False) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
        and not parts.fragment
        and (allow_query or not parts.query)
    )


def validate_authorization_server_metadata(metadata: object, *, expected_issuer: str, pre_registered_client: bool = False) -> list[str]:
    """Fail closed on missing OAuth 2.1/MCP-interoperability prerequisites."""
    errors: list[str] = []
    if not _https_url(expected_issuer):
        return ["expected issuer must be a public HTTPS URL"]
    if not isinstance(metadata, dict):
        return ["authorization server metadata must be a JSON object"]
    if metadata.get("issuer") != expected_issuer:
        errors.append("issuer mismatch")
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not _https_url(metadata.get(name)):
            errors.append(f"{name} must be an HTTPS URL")
    for field in ("grant_types_supported", "response_types_supported", "code_challenge_methods_supported"):
        if not isinstance(metadata.get(field), list) or not all(isinstance(v, str) for v in metadata[field]):
            return [f"{field} must be an array of strings"]
    if "authorization_code" not in metadata.get("grant_types_supported", []):
        errors.append("authorization_code grant not advertised")
    if "refresh_token" not in metadata.get("grant_types_supported", []):
        errors.append("refresh_token grant not advertised")
    if "code" not in metadata.get("response_types_supported", []):
        errors.append("code response type not advertised")
    if "S256" not in metadata.get("code_challenge_methods_supported", []):
        errors.append("PKCE S256 not advertised")
    if not (metadata.get("client_id_metadata_document_supported") is True
            or _https_url(metadata.get("registration_endpoint"))
            or pre_registered_client):
        errors.append("no declared client registration strategy")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issuer", required=True, help="configured HTTPS OAuth issuer URL")
    parser.add_argument("--metadata-json", required=True, type=Path, help="locally saved sanitized discovery JSON")
    parser.add_argument("--pre-registered-client", action="store_true", help="operator confirms a client was registered at the AS")
    args = parser.parse_args()
    try:
        data = json.loads(args.metadata_json.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"OAuth metadata unavailable or invalid: {type(exc).__name__}")
        return 1
    errors = validate_authorization_server_metadata(data, expected_issuer=args.issuer, pre_registered_client=args.pre_registered_client)
    for error in errors:
        print(f"BLOCKED: {error}")
    if errors:
        return 1
    print("OAuth metadata static preflight OK; live authorization flow still required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
