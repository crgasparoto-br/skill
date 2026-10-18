"""Operator-run live operational MCP checks. No service lifecycle changes or token logging.

The operator MUST independently perform and document restart/rotation/expiry.
This tool checks fresh real sessions and optionally rejects a retired session.
"""
import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from probe_live_oauth import PROTOCOL, probe, rpc


def run_phase(endpoint, repository, allowed, denied, phase, retired=None):
    if not allowed or not denied or allowed == denied:
        raise ValueError("Two distinct MCP bearer sessions are required")
    if phase in ("post-expiry", "post-rotation") and (not retired or retired in (allowed, denied)):
        raise ValueError("A separate retired session is required for expiry/rotation")
    results = probe(endpoint, allowed, denied, repository)
    if phase in ("post-expiry", "post-rotation"):
        with httpx.Client(timeout=25.0, follow_redirects=False) as client:
            old = rpc(client, endpoint, retired, "initialize", {
                "protocolVersion": PROTOCOL, "capabilities": {},
                "clientInfo": {"name": "solverit-operational-check", "version": "1.0"},
            }, 1, {})
        # A transport authentication denial is the expected result for a retired
        # session. A JSON-RPC application error is NOT evidence of expiry/revocation.
        results["retired_session_transport_denied"] = old.get("denied") is True
    return {
        "phase": phase,
        "timestamp_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "result": "PASS" if results and all(results.values()) else "NOT_VALIDATED",
        "checks": results,
        "operator_confirmation_required": (
            "Verify independently that the named restart, expiration or credential "
            "rotation actually occurred and that denied requests generated zero "
            "GitHub installation API calls; this probe cannot certify those events."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=(
        "baseline", "post-restart", "post-expiry", "post-rotation"))
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--allowed-token-file", required=True, type=Path)
    parser.add_argument("--denied-token-file", required=True, type=Path)
    parser.add_argument("--retired-token-file", type=Path)
    args = parser.parse_args()
    if not args.endpoint.startswith("https://"):
        parser.error("HTTPS endpoint is required")
    try:
        allowed = args.allowed_token_file.read_text(encoding="utf-8").strip()
        denied = args.denied_token_file.read_text(encoding="utf-8").strip()
        retired = (args.retired_token_file.read_text(encoding="utf-8").strip()
                   if args.retired_token_file else None)
        result = run_phase(args.endpoint, args.repository, allowed, denied, args.phase, retired)
    except (OSError, ValueError, KeyError, httpx.HTTPError) as exc:
        print(json.dumps({"result": "NOT_VALIDATED", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
