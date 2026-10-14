# Issue #88 — Keycloak delivery scope verification (do not activate writes)

**State: pending operator validation.** The existing `solverit:read` scope
and the read-only GitHub auditor MUST remain unchanged. This procedure is
for the new isolated Issue #88 delivery broker, not a declaration of
production readiness.

## Staging evidence (operator, 2026-10-14)

The VPS readiness check passed with `FAILED=0, PENDING=2`.
Controller UID 995, GitHub authenticator UID 997, rootless worker UID
1004, protected broker group GID 984; SQLite protected under UID 997 with
mode 0600. The authenticator can import the broker modules using the
real `/usr/bin/python3`. GitHub App key is readable only by its service
identity. Broker is stopped, and no socket is published.

**Still pending:** protected `broker.env` and authoritative Keycloak
`solverit:deliver` scope plus approved subject mapping.

## 1. Public protocol check (no admin credentials)

From the VPS, run the pinned
`ops/check-keycloak-public-readiness.py`. It checks exact issuer,
issuer-relative OAuth/JWKS endpoints, TLS, PKCE S256 and public RSA signing
keys. It never obtains tokens, reads internal secrets or edits Keycloak.
`scopes_supported` is informational only: a listed scope **does not**
prove user assignment or authorization, and an omitted value is not proof
that the scope doesn't exist.

## 2. Administrative Keycloak checks — operator in UI

Open the Keycloak administrative console for realm `solverit-delivery`
using the operator's existing login; do not copy credentials to a
terminal, chat, GitHub issue or logs.

1. **Client scopes**: verify a distinct optional OIDC client scope
   `solverit:deliver` exists. If missing, create it as **Optional**,
   not Default; do not modify `solverit:read`.
2. **Delivery scope audience mapper**: verify the access token receives
   custom audience `https://mcp.solveritconsultoria.com.br/mcp`.
   Ensure ID tokens are not used as API bearer tokens.
3. **Clients**: verify only the intended delivery OAuth client (pilot:
   `solverit-chatgpt-mcp`, after confirming the live client identity)
   permits requesting `solverit:deliver` as an optional client scope.
   Do not enable privileged scopes as defaults.
4. **Users**: find the specifically authorized operator and record the
   immutable Keycloak **user ID** (JWT `sub`) in the protected VPS
   configuration, not an email or display name. This subject is
   referenced only from the broker root-managed allowlist.
5. **Authorization**: a scoped token is not enough on its own. Restrict
   the privileged action with the server-side subject allowlist, repo
   allowlist and `solverit:deliver` JWT scope. A request by another
   subject, even if they obtain an access token with the scope, must
   be rejected. Before production, require an independent review of the
   corresponding user/group/role assignment and per-tool policy.
6. **Never treat UI settings as a completed E2E test**. Valid test:
   signed, unexpired **access** token, correct `iss`, `aud`,
   `sub`, `scope` including `solverit:deliver`; separate negative
   tests for read-only, wrong-subject, expired and wrong-audience
   tokens. Never print JWTs or secrets in reports.

If Keycloak does not implement this scope yet, **do not create
`broker.env` with invented subject values** or start the broker.
Changes to the realm require an explicit reviewed administrative action.

## 3. Protected broker environment (after user mapping reviewed)

Only AFTER steps 1–2 are validated, create root-owned
`/etc/solverit/issue-delivery/broker.env` with mode 0600. Ensure it
contains the correct public issuer, audience, JWKS URI, UIDs 995 and GID
984, and the reviewed comma-separated OIDC `sub` allowlist in
`SOLVERIT_MCP_DELIVERY_SUBJECTS`. Use
`systemd/broker.env.example` for schema, not for unverified values.

**Do not paste the environment contents into chat:** even though
the public endpoints are not secrets, the allowlist is operational
authorization data. Verify owner/mode by `stat` and test authorization
locally without printing credentials.

## 4. Activation gates remain closed

The previous VPS check shows only staging readiness. The controller
MCP with independently validated OAuth and per-action policy is not yet
operational; the CI verification broker does not publish code or PRs.
The privileged broker must remain inactive until the service unit,
real Keycloak token verification, protected job provenance, negative
Unix-socket identity tests and independent security review all pass.

No auto merge, no direct write to `develop` or `main`, no changes
to the existing read-only auditor.
