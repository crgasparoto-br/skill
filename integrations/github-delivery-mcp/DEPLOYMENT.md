# Issue 88 — GitHub App and OVH VPS bootstrap checklist

> **Stage only.** The production delivery service and sandbox executor do not exist yet.
> Do not expose a public MCP endpoint, grant a write App to the auditor, or claim E2E approval.

## GitHub configuration

1. Preserve the existing audit GitHub App (ID 5257238) and existing read-only MCP endpoint.
2. Create a **new GitHub App**, e.g. `SolverIT Issue Delivery`, under the intended owner. Disable unnecessary webhook events initially. Install **only** on explicitly authorized repositories, starting with `crgasparoto-br/training-system`; include `skill` only if necessary.
3. Request repository permissions: `Contents: read/write`, `Pull requests: read/write`, `Metadata: read`, `Actions: read`, `Checks: read`, `Issues: read` (upgrade to Issues write only if truly required). No Administration write. Do not use the auditor's PEM.
4. Configure an **independent OAuth client** for delivery. Verify login identity and server-maintained profile before job enqueue. OAuth login alone is insufficient authorization.
5. In `skill` ruleset `Protect develop`, configure required CI status checks rather than leaving the list empty. Confirm exact check names from a successful action run first. Keep `training-system` required `Validate repository`.
6. Keep all protected-branch bypass exceptions disabled for the delivery App. A GitHub App's broad Contents write permission **does not replace application checks** against protected refs.
7. The dedicated delivery App must not be installed with access to all repositories; record installation ID **server-side** after installation.

## VPS bootstrap (non-disruptive; no restart or deployment)

Before proceeding, verify OS, Docker and free resources. Never run untrusted builds using
host Docker socket or privileged host containers. The executor requires a separately
validated worker security boundary; this document intentionally does not launch one.

```bash
set -u
printf '%s\n' '== Host and kernel =='
uname -a
cat /etc/os-release
printf '%s\n' '== Docker =='
docker version --format '{{.Server.Version}}' 2>&1 || true
printf '%s\n' '== Resources =='
df -h /var /tmp
free -h
printf '%s\n' '== Existing services (read only) =='
docker ps --format '{{.Names}} {{.Status}}' 2>&1 || true
printf '%s\n' '== End of diagnostic; shell remains open =='
```

A privileged VPS administrator should create dedicated configuration and state
directories for a delivery **control-plane service**, separate from the auditor:

```bash
sudo install -d -m 0750 /opt/solverit/issue-delivery
sudo install -d -m 0700 /etc/solverit/issue-delivery
sudo install -d -m 0700 /var/lib/solverit/issue-delivery
sudo install -d -m 0700 /var/log/solverit/issue-delivery
printf '%s\n' 'Directories prepared; no service started and shell remains open.'
```

**Note:** directories above are host-level staging only; users, ownership, private
network/firewall policy and unit configuration MUST be finalized before deployment.

Never paste GitHub private keys, installation tokens, OAuth client secrets, authorization
codes or session cookies into chat. Prefer a root-owned secret store, restrictive
file permissions and short-lived installation tokens obtained by the control plane.
Do not mount them into worker jobs. Use a separate DNS name and reverse proxy
upstream for the delivery MCP only after authenticated negative tests pass.

## Security release gates

- Verified, non-forgeable OAuth principal; server-side user/repo/tool allowlists.
- GitHub App only installed on authorized repos; no writes to main/develop.
- Isolated ephemeral workers without Docker socket, host mounts or secrets, with egress
  mediation, CPU/RAM/PID/disk/time limits and independent workspace per job.
- Recheck HEAD, blob SHA and authorization before publishing; reject stale writes.
- Persist jobs, idempotency keys and redacted audit events; recover cleanly after restart.
- Offline security tests, authorized and denied OAuth tests, and sandbox E2E.
- CI green on exact PR HEAD and a separate independent auditor verdict.
- Rollback: disable delivery MCP, revoke its installation tokens and stop its workers;
  do **not** restart or revoke the read-only auditor.
