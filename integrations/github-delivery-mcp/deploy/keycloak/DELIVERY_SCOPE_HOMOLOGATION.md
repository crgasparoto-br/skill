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

## 2.1. Mandatory object descriptions and traceability (Issue #88)

Whenever a new Keycloak object is created for the delivery workflow,
specify its **exact technical name, description, intended permissions and
issue reference before instructing an operator to save it**. If a Keycloak
object type does not expose a Description field, its documented purpose
is still mandatory. A screenshot without a description input must not
be interpreted as an incomplete administrative operation if Keycloak
does not support that metadata.

| Object | Exact name | Description or documented purpose | Where to record it |
| --- | --- | --- | --- |
| Realm Role | `solverit-delivery-operator` | **Issue #88 — Autoriza operadores aprovados a executar entregas controladas de issues via MCP, com autenticação Keycloak, execução isolada na VPS e auditoria independente. Não concede acesso administrativo nem autorização de merge.** | Role **Description** field and this table |
| Client Scope | `solverit:deliver` | **Issue #88 — Escopo OAuth opcional e restrito à role solverit-delivery-operator. Permite solicitar operações de entrega controlada pelo MCP, sujeitas à validação do token, identidade autorizada e políticas de segurança do servidor.** | Client Scope **Description** field (when available) and this table |
| Audience Mapper | `solverit-delivery-mcp-audience` | **Issue #88 — Inclui a audiência do recurso MCP SolverIT no access token emitido pelo Keycloak, permitindo que o servidor valide o destinatário do token antes de autorizar operações de entrega.** | This table: the Keycloak Audience Mapper form **does not expose a Description field**; enter the technical name in its mandatory **Name** field |
| Existing OAuth Client (reference, not a new object) | `solverit-chatgpt-mcp` | **Issue #88 — Cliente OAuth público do ChatGPT para acesso autenticado ao MCP SolverIT, com PKCE S256 e escopos opcionais autorizados pelo servidor.** | Documentation only unless its existing Description may be safely edited after independent review |

Rules: descriptions express **intended authorization**, not proof of
provisioning or active access. Do not claim a role, scope or mapper has
been saved until confirmed in the Keycloak administration console.
Never put user identifiers, access tokens, passwords or PEM keys in
descriptions. Existing `solverit:read` and auditor permissions remain
unchanged.

### Step A: dedicated authorization role FIRST

1. Open **Realm roles** and create an isolated role named
   `solverit-delivery-operator`. Fill its **Description** with the exact
   Issue #88 text in the table above. If already present, review its existing
   members before reusing it; do not overwrite previously documented metadata blindly.
2. Assign that role **only** to the explicitly approved delivery operator(s)
   under **Users > [approved user] > Role mapping > Assign role**.
   Do not assign it as a default realm role or to broad groups.
3. Keep a reviewed record of the approved users' immutable Keycloak user IDs
   (the JWT `sub`). Never use email, display name or a tool-provided actor
   instead of the cryptographically verified `sub`.

### Step B: OIDC client scope and enforceable role constraint

1. Open **Client scopes > Create client scope** and create exactly
   `solverit:deliver` using **OpenID Connect**. Fill its **Description**
   with the exact Issue #88 text in the table above when Keycloak provides the
   field. Set **Include in token scope** to **ON**. Do not edit the existing
   `solverit:read` scope.
2. Open the new `solverit:deliver` client scope's **Scope** tab and
   **assign the Realm Role `solverit-delivery-operator` to its role scope
   mappings**. This is security-critical: Keycloak permits every user to
   use a client scope when it has *no* role scope mappings; the role
   intersection restricts the scope to users possessing the role.
3. Under **Mappers > Configure a new mapper > Audience**, set
   name `solverit-delivery-mcp-audience`, **Included Custom Audience**
   `https://mcp.solveritconsultoria.com.br/mcp`,
   **Add to access token ON**, **Add to ID token OFF**. Leave **Included Client
   Audience** empty and **Add to lightweight access token OFF** (as shown
   in the operator screenshot). The mapper form has no Description field:
   use the Name exactly as specified and record the purpose in the table above.
   Do not substitute the client ID for the exact MCP resource audience.
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

## Progress reported by operator — 2026-10-14 23:53 UTC

The operator confirmed saving the **Audience mapper** configured on the
`solverit:deliver` client-scope screen, named
`solverit-delivery-mcp-audience` with custom audience
`https://mcp.solveritconsultoria.com.br/mcp`. This is **self-reported
configuration**, not an independent Keycloak admin API audit. The operator subsequently confirmed **creation** of the realm role
`solverit-delivery-operator` (2026-10-14 23:55 UTC). The operator also confirmed completing both role associations
(2026-10-14 23:58 UTC): (1) `solverit-delivery-operator` assigned to the
approved Keycloak user, and (2) the same role assigned under the
`solverit:deliver` client scope's role scope mappings. These are
**operator-reported administrative changes**, not independently validated
through the Keycloak admin API. **Still pending:** attach the scope as
**Optional** (not Default) to `solverit-chatgpt-mcp`; evaluate the scope for
both a permitted and a non-permitted user; verify signed access token scope,
audience, subject and negative authorization paths before any broker start. Keep the broker inactive and do not
create authorization allowlists from guesses.


## Operator checkpoint — 2026-10-15 00:01 UTC

The operator reported that the optional client scope `solverit:deliver` was
successfully attached to OAuth client `solverit-chatgpt-mcp` as
**Optional**, NOT Default. This is an operator confirmation, **not**
independent admin-API verification. The previous operator confirmations
also cover creation of the `solverit-delivery-operator` role, role
assignment to an approved user, role-scope mapping in `solverit:deliver`,
and the resource audience mapper.

### Next mandatory security acceptance: evaluate two distinct users

In Keycloak Admin Console: **Clients** -> `solverit-chatgpt-mcp` ->
**Client scopes** -> **Evaluate**. Explicitly select optional
`solverit:deliver`. Use the **User** selector for each test and inspect
the *simulated access token*, **without copying or sharing the raw token**.

| Test case | Required result |
| --- | --- |
| Approved user with `solverit-delivery-operator` | `scope` contains `solverit:deliver`, `aud` contains the exact MCP resource `https://mcp.solveritconsultoria.com.br/mcp` |
| Separate user without `solverit-delivery-operator` (including composite roles) | `scope` **does not** contain `solverit:deliver`; delivery-scope mapper must not grant the MCP audience through this scope |
| No optional `solverit:deliver` requested | Delivery scope must be absent from the resulting access token |

If the scope is granted to an unauthorized user, **STOP**: inspect the
role scope mappings, whether the role is assigned through a composite,
whether the scope is accidentally Default, and other client mappers.
Do not confuse the Evaluate preview with proof of real token signature
and expiry. Real JWT issuer, audience, subject, scope, peer-UID checks
and protected broker configuration remain activation blockers.


## Optional scope readiness -> protected broker policy stage (2026-10-15)

The operator confirmed on 2026-10-15 that `solverit:deliver` was
attached as an **Optional** scope to `solverit-chatgpt-mcp`. This does
**not** establish an approved `broker.env` or validate the two
distinct users. Before using the secure environment provisioner:

1. In **Clients -> solverit-chatgpt-mcp -> Client scopes -> Evaluate**,
   explicitly select `solverit:deliver` and choose the approved user.
   Its simulated **access token** must contain the delivery scope,
   `aud` must contain the exact MCP audience and `sub` must be the
   intended immutable Keycloak User ID.
2. Repeat for a **different user without** the delivery operator role:
   the **access token** MUST NOT include `solverit:deliver`.
   Also test without requesting the optional scope.
3. Record only PASS/FAIL of each case; do **not** copy any JWT or the
   approved user's Keycloak ID into GitHub or chat. If the unauthorized
   user is granted the scope, STOP and inspect Keycloak role scope
   mapping and client scope defaults.
4. From the reviewed PR HEAD, run the offline unit test
   `test_broker_env_provision.py` and the provisioner in default
   **readiness-only mode** on the VPS (requires root, no password prompts).
   The default invocation changes nothing.
5. After both evaluations PASS, execute
   `sudo -n /usr/bin/python3 ops/provision-broker-env.py --apply`
   **from the reviewed immutable checkout**. At the interactive prompt,
   type `CONFIRMADO` only if the operator actually reviewed both
   cases. Enter the approved immutable Keycloak User ID (`sub`) via
   the hidden prompt; do not provide a username, email, JWT or password.
   The utility rejects pre-existing env files and writes only a
   root-owned `0600` file with fixed issuer/audience/JWKS,
   controller UID 995, broker group GID 984 and one approved `sub`.
   It does not start systemd, reach Keycloak or issue GitHub tokens.

**Security limits:** `--apply` records operator attestation rather
than cryptographic access-token evidence. Never interpret successful
env creation as authorization approval. Real signed-token positive and
negative tests, IPC credential checks, effective controller RBAC,
integration CI and independent audit must still pass before service
activation. Preserve the existing read-only auditor and leave
`solverit-issue88-github-broker.service` inactive.


## VPS broker.env preflight — 2026-10-15, operator evidence

The operator ran the pinned `ops/provision-broker-env.py` in its
**non-mutating default mode**, after the isolated unit test command, and
reported `OK` plus these exact conditions:

- `PASS: root-owned directory, separate identities, env absent`.
- `PENDING: positive and negative Keycloak Evaluate evidence`.
- `PENDING: --apply with the approved Keycloak immutable user ID`.
- `Broker remains stopped; no files modified`.
- Shell outcome: `RC=0`; terminal preserved.

**Decision: staging preflight PASSED; privileged environment NOT provisioned.**
This evidence is not a green light to run `--apply`: first inspect two
distinct Keycloak users in Client scopes > Evaluate and establish the
positive and negative outcomes documented above. No user identity,
token, credential or environment value was disclosed.

After both Evaluate cases are confirmed, the operator may execute the
version-pinned, audited `--apply` mode under `sudo -n` using the hidden
OIDC `sub` input, and must validate file ownership/mode without printing
its contents. Actual broker startup and CI/audit E2E remain blocked.


## Keycloak two-user screenshots — 2026-10-15 (operator evidence)

The operator provided Keycloak Admin Console screenshots of two **enabled**
users in realm `solverit-delivery`:

- `solverit-mcp` (intended positive case): `Role mapping` visibly
  includes `solverit-delivery-operator` and
  `default-roles-solverit-delivery`.
- `solverit-mcp-test` (intended negative case): `Role mapping` visibly
  lists `default-roles-solverit-delivery` only; there is **no direct
  delivery role visible**.

**Important caveat:** `Hide inherited roles` was **checked** in both
screenshots. They do NOT establish that the negative test user lacks the
role by inheritance from a composite role or group. Before claiming
authorization failure works, uncheck `Hide inherited roles` on the
negative user, inspect the `Groups` tab and the full effective role
mapping, and ensure `solverit-delivery-operator` is absent.

Perform **Clients -> solverit-chatgpt-mcp -> Client scopes -> Evaluate**,
explicitly selecting `solverit:deliver` as optional:

1. `solverit-mcp`: `scope` must include `solverit:deliver`; `aud`
   must contain exact `https://mcp.solveritconsultoria.com.br/mcp`.
2. `solverit-mcp-test`: `scope` **must not** include `solverit:deliver`
   (no delivery role, including inherited); the additional audience
   mapping must not be granted through the delivery scope.
3. Repeat without requesting the optional scope; the delivery scope must
   be absent. Record each result as PASS/FAIL without copying any token,
   user-ID, account secret or token claim payload into GitHub.

**Status: screenshots verify visible direct role mapping only. The
positive/negative access-token evaluations remain PENDING.**
Do not run `ops/provision-broker-env.py --apply`, start broker or
declare Issue #88 approved before both authorization checks pass.
