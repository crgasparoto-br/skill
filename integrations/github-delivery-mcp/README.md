# Issue #88: delivery control plane (phase 1)

**Status: PARTIAL IMPLEMENTATION — NOT PRODUCTION READY.**

This package provides a standalone fail-closed policy module and offline regression
tests. It is **not** an MCP server and does not offer GitHub writes or a VPS job
executor. Do not connect it to the production read-only auditor.

## Trust boundaries

| Component | Credential | Allowed actions |
| --- | --- | --- |
| Existing auditor (PR #87) | Auditor GitHub App, read-only | Observe rulesets/protection |
| Delivery MCP (not implemented yet) | Independent OAuth audience and GitHub App installation | Explicit per-tool authorization |
| Job control plane (not implemented yet) | Short-lived, repo-scoped publication token | Validate state and publish commits/PR |
| Ephemeral executor (not implemented yet) | No GitHub token, host secrets or Docker socket | Clone through mediated input, edit, test |

The server MUST construct `VerifiedPrincipal` from verified OAuth identity and
server-stored profile membership. The principal MUST NOT originate from an MCP
argument, repository file, issue body, test output or job logs. Every dispatch,
including direct MCP calls, requires server-side authorization before any
GitHub request or job enqueue.

## Job contract v1 (future implementation)

Tools: `prepare_workspace`, `inspect_workspace`, `apply_patch`,
`run_allowed_checks`, `get_job_status`, `get_job_logs`,
`publish_branch`, `open_pull_request`.

Each request MUST contain a stable idempotency key, authorized repo,
issue number, work branch, and expected HEAD SHA. Responses MUST expose
`job_id`, `status`, `base_sha`, `head_sha`, `correlation_id`,
redacted artifact references, timestamps, and typed error codes.
Accepted states: `queued`, `running`, `succeeded`, `failed`,
`cancelled`, `timed_out`. Persist transitions before side effects;
recover interrupted running jobs into a reconcilable state. Retry MUST
not duplicate commits, branches or PRs.

The controller MUST use CAS for both branch HEAD and file blob SHA,
and reauthorize before push/PR. The `policy.py` SHA comparison is
a precondition only; it does **not** replace an atomic server-side
ref update with expected SHA.

## Execution profiles

Keep versioned Node/Python task templates in this repository. Never
execute arbitrary user/issue shell strings. Isolate each checkout by
issue and run ID. Reject direct `main`/`develop` publication; reject
merge, deletion and force push. Workers must run without host Docker
socket, credentials, privileged user, unrestricted egress or access
to the auditor's infrastructure. Apply CPU, RAM, PIDs, storage and
duration quotas; preserve exit codes and redacted logs.

## Operations and rollback

Do not deploy this partial package. Deploy a future delivery MCP under
a **different service and credential boundary** after an independent
security review. Rollback is disabling the delivery service, revoking
its installation tokens and keeping the existing read-only audit MCP
unchanged. Never share installation credentials with the audit service.

## Remaining gates

1. Authenticated delivery MCP with explicit per-tool authorization,
   separate App, scope limits and deny-by-default integration tests.
2. Secure job scheduler/executor and runner hardening on the VPS.
3. Clone, patch, pinned checks, repair loop and CAS publication.
4. Crash recovery, cancellation, idempotency, redacted audit logs.
5. End-to-end training-system sandbox proof including failing CI,
   repair, commit, PR to develop and exact-head green CI.
6. Negative security tests and independent audit verdict as first line.

Run phase-1 tests: `cd integrations/github-delivery-mcp && python -m unittest -v test_policy.py`.
No live credentials are used.
