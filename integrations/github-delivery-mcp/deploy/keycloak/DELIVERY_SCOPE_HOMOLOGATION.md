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

## 2. Administrative Keycloak configuration — operator in UI

The operator verified that `solverit:deliver` **does not yet exist**
(2026-10-14). Create it as follows in realm `solverit-delivery`
using an authorized Keycloak administrator. These administrative changes
are not performed by public OIDC checks.

### Step A: dedicated authorization role FIRST

1. Open **Realm roles** and create an isolated role named
   `solverit-delivery-operator`. If already present, review its existing
   members before reusing it.
2. Assign that role **only** to the explicitly approved delivery operator(s)
   under **Users > [approved user] > Role mapping > Assign role**.
   Do not assign it as a default realm role or to broad groups.
3. Keep a reviewed record of the approved users' immutable Keycloak user IDs
   (the JWT `sub`). Never use email, display name or a tool-provided actor
   instead of the cryptographically verified `sub`.

### Step B: OIDC client scope and enforceable role constraint

1. Open **Client scopes > Create client scope** and create exactly
   `solverit:deliver` using **OpenID Connect**. Set **Include in token
   scope** to **ON**. Do not edit the existing `solverit:read` scope.
2. Open the new `solverit:deliver` client scope's **Scope** tab and
   **assign the Realm Role `solverit-delivery-operator` to its role scope
   mappings**. This is security-critical: Keycloak permits every user to
   use a client scope when it has *no* role scope mappings; the role
   intersection restricts the scope to users possessing the role.
3. Under **Mappers > Configure a new mapper > Audience**, set
   name `solverit-delivery-mcp-audience`, **Included Custom Audience**
   `https://mcp.solveritconsultoria.com.br/mcp`,
   **Add to access token ON**, **Add to ID token OFF**. Do not substitute
   the client ID for the exact MCP resource audience.
4. Open **Clients > solverit-chatgpt-mcp > Client scopes** after confirming
   this is the real ChatGPT OAuth client. Attach `solverit:deliver` as
   **Optional**, **never Default**; the privilege is requested explicitly
   by `scope=openid solverit:deliver`, not granted on every login.
   Do not add it to realm defaults or other clients.

### Step C: verify the *actual* user authorization

Use **Clients > solverit-chatgpt-mcp > Client scopes > Evaluate**
with `solverit:deliver` selected. Evaluate at least an approved user
(with `solverit-delivery-operator`) and a different, unapproved user.
Check the simulated *access* token's `scope` and `aud`. The approved
user should have `solverit:deliver`, the unapproved user MUST NOT;
if the unapproved user receives it, stop and correct the role mapping.
The user `sub` must later match the private broker allowlist.
No complete positive test is established until a real, signed,
unexpired access token passes issuer, audience, scope and allowlist
checks in the actual broker; these checks do not depend on the
public discovery `scopes_supported` field.

**Defense in depth:** even when Keycloak rejects unauthorized users,
the broker must independently require the signed `solverit:deliver`
scope, immutable subject allowlist, repository policy, peer UID and
job ownership. The existing read-only MCP and auditor stay unchanged.

Do not paste OAuth tokens, client secrets, passwords or private keys into
GitHub issues, PRs, chat or logs. Never activate the broker before negative
tests (read-only, wrong user, wrong audience, expired token and worker IPC).

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
