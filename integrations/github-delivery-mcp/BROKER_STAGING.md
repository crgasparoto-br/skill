# Issue #88 — privileged local evidence broker (staging, 2026-10-13)

**Not deployed. Not production ready.** PR #89 targets `develop` and stays draft.
This is the **first security boundary**, not the completed `entregar-issue`
executor or an MCP write capability.

## What has been added

- `protected_broker_server.py`: Linux AF_UNIX server, checks actual
  `SO_PEERCRED` UID **before reading a request**, and only accepts
  `{"version":1,"operation":"verify_bound_ci","job_id":"<canonical-UUID>"}`.
  The JSON cannot override the OAuth actor, repository, PR, GitHub token,
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
- `test_protected_broker_server.py` covers unauthorized peers, forbidden
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
   as **trusted, separate job metadata**. Its file and ALL parent
   components must be owned by root or UID 997, and must not be
   group/world writable. The DB must not be world readable.
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
