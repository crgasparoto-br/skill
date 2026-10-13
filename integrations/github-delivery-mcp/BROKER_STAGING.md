# Issue #88 — privileged local evidence broker (staging, 2026-10-13)

**Not deployed. Not production ready.** PR #89 targets `develop` and stays draft.
This is the **first security boundary**, not the completed `entregar-issue`
executor or an MCP write capability.

## OAuth identity binding (implemented in code, not deployed)

The broker requires **both** the actual controller Linux UID via
`SO_PEERCRED` and a cryptographically verified Keycloak **MCP access token**
containing scope `solverit:deliver`. `broker_oauth.py` uses the existing
`CachedJWKSVerifier` with a protected issuer, resource audience, JWKS URI and
subject allowlist; it fails closed when keys are unavailable, claims are
expired or cryptographically invalid, `scope` is only `solverit:read`, or the subject is not
allowlisted. The signed `sub` MUST equal the owner of the protected job.
The broker does not accept an actor, repository, required-check list or PR
number from the caller.

The internal request is protocol version 1, exactly:

```json
{"version":1,"operation":"verify_bound_ci","job_id":"00000000-0000-4000-8000-000000000000","mcp_access_token":"<short-lived Keycloak JWT>"}
```

The JWT above is a *placeholder*, not a real credential. The transport
carries the incoming Keycloak OAuth credential only within the protected
socket, never through logs or GitHub. The **GitHub App installation token**
is minted separately under UID 997 and never leaves the broker.
`controller_broker_client.py` validates broker `SO_PEERCRED` UID 997 and a
strict versioned success response. Neither module is an MCP tool endpoint;
public exposure must remain disabled.

Before enabling this mode, configure a distinct Keycloak
`solverit:deliver` scope and verify it is issued only to appropriately
authorized users/clients. Existing `solverit:read` users must not
implicitly gain delivery permissions. Do not change the existing read-only
auditor role/client. The broker environment, managed by root, must contain:

```text
SOLVERIT_BROKER_CONTROLLER_UID=<trusted-controller-uid>
SOLVERIT_BROKER_SOCKET_GID=<trusted-group-gid>
SOLVERIT_MCP_RESOURCE_URL=https://mcp.solveritconsultoria.com.br/mcp
SOLVERIT_OAUTH_ISSUER_URL=https://auth.solveritconsultoria.com.br/realms/solverit-delivery
SOLVERIT_OAUTH_JWKS_URI=https://auth.solveritconsultoria.com.br/realms/solverit-delivery/protocol/openid-connect/certs
SOLVERIT_MCP_DELIVERY_SUBJECTS=<allowlisted-oidc-sub-values>
```

The actual resource URL and issuer must match the deployed Keycloak and MCP
audience claims exactly; verify them rather than assuming the examples are
still current. Do not paste real JWTs, private keys or tokens into GitHub
issues, PRs, test output or chat.

### Integration prerequisites

1. Start a **separate trusted controller** running under the configured
   controller UID, distinct from worker (1004) and authenticator (997).
   The controller must independently validate HTTP bearer tokens, tool
   permissions, repo allowlists and rate limits before invoking IPC. It
   must pass the already received Keycloak access token; never accept
   identity fields as MCP tool parameters.
2. Restrict membership of the broker socket group; the worker must never
   traverse its directory or connect. The broker repeats OAuth validation
   even after the controller has authorized the user.
3. Only then test a protected real job→PR binding against a GitHub PR in an
   expressly authorized sandbox. A passing CI response does **not**
   authorize `succeeded`; independent audit and exact-HEAD completion
   remain unimplemented.

## What has been added

- `protected_broker_server.py`: Linux AF_UNIX server, checks actual
  `SO_PEERCRED` UID **before reading a request**, and only accepts
  the versioned `verify_bound_ci` request with a canonical job UUID and
  a signed Keycloak MCP access token. The broker verifies the subject matches
  the stored job owner.
  The JSON cannot override the verified OAuth actor, repository, PR, GitHub token,
  required checks, or permission profile. Every error returns
  `{"ok":false,"error":"denied"}` without detailed exceptions or secrets.
- Protected, read-only SQLite read (`mode=ro`, no implicit database
  creation), rejecting symlinks, worker-owned parents, writable parents,
  group-writable databases and world-readable databases. A prepared job
  with a persistent job→PR binding and a distinct immutable HEAD is required.
- Token minting is restricted to the authenticator process (UID 997)
  with `read-checks` for the allowlisted `training-system` repository.
  Its token is only passed in memory to the existing GitHub evidence reader;
  no MCP or Unix-socket response ever contains it.
- The only configured required check is `Validate repository`, from
  protected versioned code. The response explicitly says
  `audit_verified: false`; it never finalizes a job.
- `test_broker_oauth.py` and `test_controller_broker_client.py` cover
  issuer/audience/scope policies, invalid tokens, broker peer identity and
  response framing; `test_protected_broker_server.py` covers unauthorized peers, forbidden
  write operations, fabricated actor/token/PR/repo/checks, malformed IDs,
  framing limits, missing binding, unprepared jobs, HEAD mismatch,
  read-only SQLite and secret-safe failures.
- `systemd/solverit-issue88-github-broker.service` is a **staging-only**
  unit without an `[Install]` section; it must not be enabled as-is.

## VPS rollout prerequisites (NOT yet performed)

1. Reserve a **trusted controller UID**, distinct from the rootless worker
   UID 1004 and authenticator UID 997. That controller must verify Keycloak
   JWTs, enforce server-side per-user, per-repository and per-action policy,
   and never execute untrusted repository code under its UID. Never trust
   an `actor` field from an MCP request.
2. Provision a root-managed group `solverit-delivery-control` for the
   broker socket, with membership restricted to the controller and
   authenticator. Do not add `solverit-worker`. Keep
   `solverit-app-key` restricted to the authenticator.
3. Put the verified broker source code in
   `/opt/solverit/issue-delivery/`, owned by root and non-writable by
   the controller/worker. Review `systemd` hardening and the exact
   Python interpreter environment used by the GitHub SDK.
4. Create `/var/lib/solverit/issue-delivery/protected/jobs.sqlite3`
   as **trusted, separate job metadata**. The SQLite file MUST be owned
   by UID 997 and have no group/world permissions (e.g. mode 0600).
   All parent components must be owned by root or UID 997 and must not
   be group/world writable.
   The current worker-owned SQLite staging files **must not be trusted**:
   migrate or recreate jobs only after independent validation of their
   provenance and commit SHAs. Do not copy a worker-controlled DB
   blindly into the protected directory.
5. Prepare root-managed `/etc/solverit/issue-delivery/broker.env`
   (mode 0600), with `SOLVERIT_BROKER_CONTROLLER_UID=<trusted UID>`
   and `SOLVERIT_BROKER_SOCKET_GID=<group GID>`. The values must be
   positive decimal integers; root (0), UID 997 and UID 1004 are
   rejected as caller identities. Never put a GitHub token in the env file.
6. Validate directory access: broker UID 997 can read the protected DB
   and GitHub App private key; only the controller process can traverse
   `/run/solverit-issue88-broker` via the socket group. The worker
   must be denied. The unit runs the broker as UID 997 and intentionally
   does not enable it.
7. Prior to any start, get security review for the systemd unit, service
   user/group, secret permissions, App installation, required check
   policy, and `SO_PEERCRED` identity model. For staging, explicitly
   start the unit after reviewing it. **Do not restart the auditor MCP,
   the worker or other VPS services.**

## Validation matrix for the next operator run

Run the offline tests from the exact PR HEAD, verify the complete CI
check matrix on that SHA, and record SHA and return codes. On the VPS:

- Authorized controller UID can ask the broker to verify a legitimate,
  protected job→PR binding (after trusted job state is provisioned).
- Rootless worker UID 1004 and arbitrary UIDs cannot read or invoke
  the broker. Direct attempts to mint tokens, publish, merge, delete or
  impersonate an actor must fail.
- Missing/changed SHA, missing binding, untrusted DB permissions,
  expired/revoked App credentials and GitHub API errors must fail closed
  without token exposure.
- Broker restart leaves protected data intact. Socket and secrets are
  not exposed to untrusted containers; logs contain no private material.
- Existing read-only auditor and VPS terminal remain unaffected.

The broker currently **only verifies CI**. It cannot create a workspace,
publish a commit/PR, authorize an OAuth session, prove the independence of
an audit, or finish Issue #88. Publication must use a **separate explicit,
approved operation** with fresh authorization, branch CAS and validation
of GitHub's actual response. Do not expose `mint_token` through a generic
request method or expand this narrow socket into arbitrary GitHub API access.

## Rollback

If staging deployment is later approved and has problems, stop the
new broker service only; check removal of its private socket, revoke
issued installation tokens if necessary, and preserve the protected
SQLite for diagnostics. Do **not** touch auditor MCP, Keycloak,
Supabase, PostgreSQL, or the rootless worker. No merge/force-push/delete
is permitted or executed by this component.
