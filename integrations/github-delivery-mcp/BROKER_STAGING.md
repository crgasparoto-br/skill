# Issue #88 — privileged local evidence broker (staging, 2026-10-13)

**Protected code and broker.env staged on VPS, service NOT started; NOT production ready.** PR #89 targets `develop` and stays draft.
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


## VPS staging checkpoint — broker.env verified, prestart JWKS runtime gate (2026-10-15)

Operator executed `ops/provision-broker-env.py --apply`, confirmed the
two-user Keycloak Evaluate evidence and entered the actual authorized
`solverit-mcp` Keycloak `sub` via the hidden prompt. The independent
`ops/verify-broker-env.py` verified that
`/etc/solverit/issue-delivery/broker.env` is owned by
`root:root`, mode `0600`, contains only the expected policy keys and
a canonical nonzero UUID. Overall `RC=0`; broker not started.

**New offline prestart verifier:**
`ops/check-broker-jwks-runtime.py` first imports the separate protected
env validator as root and reads the protected env without printing
its contents. It then **drops all supplemental groups and permanently
switches to UID 997/GID 986**, imports the actual staged
`broker_oauth` code from `/opt/solverit/issue-delivery`, fetches the
**real public Keycloak JWKS** over HTTPS and checks that deliberately
invalid unsigned bearer strings fail closed. It does not bind sockets,
write privileged files, create GitHub tokens, change OAuth settings,
start any service or invoke the protected job/PR store.

Run `test_broker_jwks_runtime.py` offline from the exact PR HEAD and
then run `check-broker-jwks-runtime.py` as root using `sudo -n`, with
`python3 -B` to avoid bytecode cache writes. No OAuth token is needed;
do not paste or log the approved `sub`.

A successful JWKS prestart check is **not** a real signed access-token
acceptance test, does **not** prove that the configured subject matches
a signed token, does not test access when only `solverit:read` is
granted, and does not prove controller socket authorization. These
and exact-HEAD CI and independent auditing remain activation gates.
The broker service MUST remain inactive until independently reviewed.
 

## 2026-10-15 — Real Keycloak JWKS runtime PASS, signed JWT matrix added

The operator executed `test_broker_jwks_runtime.py` (**8/8 PASS**) and
`ops/check-broker-jwks-runtime.py` on the VPS (**RC=0**). The
root-owned broker policy was verified, the runner dropped to UID 997/GID
986, the **real Keycloak public JWKS** was loaded under the privileged
broker UID, and three deliberately invalid bearer strings were
rejected. Broker remained **inactive**, and no service/configuration was
changed.

After that checkpoint, versioned source code added a **strict broker-only
OAuth client `azp` check**. Tokens used to authorize delivery must
originate from `solverit-chatgpt-mcp` in addition to matching the exact
Keycloak issuer, audience, approved `sub` and `solverit:deliver` scope.
The read-only auditor uses the verifier's unchanged default (no new
client pin), so this restriction is **only** active for the new delivery
broker. The new `test_broker_jwks_signed.py` signs ephemeral RSA
test tokens in memory (no Keycloak private keys, no saved token) and
checks allow/deny outcomes for signatures, scopes, subjects, audiences,
issuers, expiry, missing claims, Key ID, JOSE headers and `azp`.

**Important:** the code staged in `/opt/solverit/issue-delivery` remains
at the previous approved commit until a separately reviewed deployment
copies this new broker code. Do not start that old broker or assume the
VPS is enforcing `azp`. The signed-token matrix is offline and
requires a new VPS test run; **a real signed Keycloak JWT has still not
been supplied, authenticated or tested**. Socket security, controller
operations, CI on exact updated SHA and independent audit remain
unapproved, and there is no automatic merge.


## VPS signed RS256 policy suite — 2026-10-15, operator evidence

The operator executed two isolated test suites from the pinned commit
`8e2f2cce61f2f591f7854aab51bd985d1d17406d` in a temporary VPS
directory. Reported evidence:

- `test_broker_jwks_signed.py`: **16 tests, all PASS** (0.409 s);
  authentic RS256 signing with an ephemeral in-memory RSA key, exact
  issuer/audience/subject/scope/`azp`, rejection of altered signature,
  alternative algorithms/keys/`kid`, JOSE header injection, missing
  claims, expiry/nbf/iat, unknown audience and stale JWKS.
- `test_broker_oauth.py`: **8 tests, all PASS** (0.002 s);
  mandatory delivery scope, broker client pin, invalid JWT/subject,
  malformed configuration, and unchanged default verifier behavior
  for the separate read-only auditor.
- `systemctl` verification: broker still **inactive**.
- Overall wrapper `RC=0`; SSH terminal preserved.

**Verdict:** cryptographic offline policy regression PASS (24/24).
This is operator-supplied VPS evidence, NOT complete CI on the PR HEAD
and NOT a live Keycloak access token acceptance test.

**Next controlled stage:** the root-owned code on the VPS still points
at a prior `STAGED_COMMIT`. Re-run the guarded, version-pinned
`ops/prepare-broker-staging.sh` from an immutable HEAD to execute the
**complete** offline suite and update only the inoperative staging
code if tests pass. This script must not touch the protected
`broker.env`, start services, create fake jobs or merge PRs.
Confirm preserved SQLite ownership and live broker inactive afterward.
Then plan an independent real signed-token validation procedure and
separate Unix-socket denial tests before any service startup.


## Protected staging refresh after crypto tests — operator procedure (2026-10-15)

The operator ran the pinned `test_broker_jwks_signed.py` (**16/16 PASS**)
and `test_broker_oauth.py` (**8/8 PASS**) at SHA
`8e2f2cce61f2f591f7854aab51bd985d1d17406d`, with final `RC=0`.
Broker remained **inactive**. This certifies offline RS256 policy and
auditor-regression behavior on that SHA, not CI on subsequent commits.

A reviewed update to `ops/prepare-broker-staging.sh` now **refuses to
update staging if the broker service is active or the socket exists**;
rejects a symlink or non-root-owned staging directory; requires the
full offline test suite; installs only allowlisted inert code as root;
and writes the `STAGED_COMMIT` marker **last** after SQLite security
checks and an import test under UID 997 verifying the pinned OAuth
client `solverit-chatgpt-mcp`.

To refresh the old staging code under `/opt/solverit/issue-delivery`
the operator must run this revised script from the **exact PR HEAD**.
It does not edit or reveal the already provisioned root-owned
`broker.env`, and does not start systemd services, publish to GitHub,
modify Keycloak or touch the live auditor.

**Caution:** this script provisions/copies code, so it is not a
read-only diagnostic. Run only once the pinned commit, full suite,
service inactivity and target ownership have been verified. Successful
staging is still **not a valid activation approval**; Keycloak
authorization-code/PKCE *real signed token* acceptance, negative scope
and subject tests, socket identity, controller MCP and independent
audit are outstanding. No merge.


## Pre-activation signed Keycloak OAuth access-token proof (Issue #88)

The new ops/check-broker-live-access.py is a **read-only operator preflight**,
not a production MCP endpoint. Unlike the ephemeral-key RS256 unit tests and
the public JWKS probe, it validates **three genuine Keycloak access tokens**
without putting credentials in shell arguments, environment variables, files,
issues, PRs, chat, or logs. The interactive terminal disables echo for each
token, imposes an 8192-byte bound, and fails closed without printing claims,
subjects, JWTs, private policy values or Python exceptions.

Prerequisites, all mandatory:

1. Independently review the exact PR #89 HEAD and refresh inactive, root-owned
   staging using the existing pinned ops/prepare-broker-staging.sh (full
   suite must pass). Verify protected STAGED_COMMIT matches that HEAD.
2. Confirm the broker service is **inactive**, its socket absent, and the
   protected broker.env has passed ops/verify-broker-env.py.
3. Obtain short-lived, real OAuth **access tokens** through the existing
   authorized Keycloak PKCE/client flow: (a) approved solverit-mcp subject
   with solverit:deliver; (b) same subject without that optional scope;
   (c) other subject (solverit-mcp-test) with no delivery permission.
   All three must target the exact MCP audience and originate from the
   solverit-chatgpt-mcp OAuth client. Do **not** use ID tokens, example JWTs,
   fixture-signed tokens or an administrator's broad token. Never post
   tokens or decoded claims to ChatGPT.

On the VPS, extract the **reviewed immutable commit** into a disposable
operator directory; do not execute a mutable checkout with different bytes:

```bash
WORK="$HOME/projetos/skill-issue88-jobs"
git -C "$WORK" fetch --no-tags origin refs/heads/feat/88-controlled-issue-delivery
HEAD_SHA="$(git -C "$WORK" rev-parse FETCH_HEAD)"
# Compare HEAD_SHA with the reviewed PR HEAD before executing.
PROBE_DIR="$(mktemp -d "$HOME/projetos/issue88-probe.XXXXXX")"
git -C "$WORK" archive "$HEAD_SHA" integrations/github-delivery-mcp/ops |
  tar -x -C "$PROBE_DIR"
SCRIPT_DIR="$PROBE_DIR/integrations/github-delivery-mcp/ops"
ISSUE88_EXPECTED_SHA="$HEAD_SHA" bash "$SCRIPT_DIR/prepare-broker-staging.sh"
# Next command prompts for three hidden, genuinely signed access tokens.
sudo -n env ISSUE88_EXPECTED_SHA="$HEAD_SHA" /usr/bin/python3 -B \
  "/opt/solverit/issue-delivery/ops/check-broker-live-access.py"
```

Do not run the live-token preflight until the revised staging script reports
success at the same SHA. The script verifies the trusted env as root, securely
prompts for the tokens, **drops permanently to authenticator UID 997/GID 986**
and uses the staged broker's real JWKS verifier. Negative controls must first
pass **genuine RS256 signature, expiry, issuer, audience and client validation**
under a narrowly relaxed *test-only* policy; invalid/unsigned tokens cannot
satisfy a negative-control result. The normal delivery verifier must accept
the positive token and reject both negatives. A token from the second subject
without delivery scope exercises two restrictions together; the independent
subject-specific deny gate remains covered by the signed offline matrix.
No job, PR, GitHub write, socket binding, service enablement or restart occurs.

Read-only verifier results can authorize **further isolated tests**, not
activate the production delivery MCP. A positive live-token proof still leaves
broker peer-UID/socket tests, trusted job→PR intake, isolated executor clone,
patch/check/publish, exact-HEAD GitHub CI and **separate independent audit**
outstanding. A failed preflight is a hard stop; retain the broker inactive.

### Root-owned real-token preflight hardening (2026-10-18)

The guarded staging refresh additionally installs the three strictly allowlisted
read-only OAuth verification scripts in `/opt/solverit/issue-delivery/ops`
(owner `root:root`, directory `0755`, files `0644`). The staging commit
marker is written only after byte-for-byte comparison of every staged module
and privileged script against the immutable Git commit. A previously existing
symlink or non-root-owned scripts directory blocks refresh. Real signed-token
preflight must be executed **only from that protected directory**, never from
the operator-writable extracted checkout; the script rejects other source
locations before soliciting credentials. No daemon is started and the auditor
remains read-only.
