#!/usr/bin/env bash
# Issue #88: read-only exact-HEAD controller/broker staging inspection.
# Never activates, deploys, creates files, changes ownership or requests secrets.
(
  set -uo pipefail
  FAIL=0
  PENDING=0
  CODE="/opt/solverit/issue-delivery"
  CTRL_ROOT="/var/lib/solverit/issue88-controller"
  CTRL_DB="$CTRL_ROOT/jobs.sqlite3"
  BROKER_DB="/var/lib/solverit/issue-delivery/protected/jobs.sqlite3"
  MARKER="$CODE/STAGED_COMMIT"
  EXPECTED="${ISSUE88_EXPECTED_SHA:-}"

  ok() { printf 'PASS: %s\n' "$1"; }
  fail() { printf 'FAIL: %s\n' "$1"; FAIL=$((FAIL + 1)); }
  pending() { printf 'PENDING: %s\n' "$1"; PENDING=$((PENDING + 1)); }

  echo "=== 1. EXACT COMMIT AND ROOT-OWNED CODE ==="
  if ! [[ "$EXPECTED" =~ ^[0-9a-f]{40}$ ]]; then
    fail "ISSUE88_EXPECTED_SHA must be an exact 40-byte lowercase Git commit hash"
  elif [ "$(sudo -n cat "$MARKER" 2>/dev/null || true)" = "$EXPECTED" ]; then
    ok "protected staging matches pinned Git HEAD"
  else
    fail "staged commit marker differs from reviewed HEAD"
  fi
  for FILE in \
      app_token_broker.py broker_develop_intake.py broker_oauth.py \
      controller_broker_client.py delivery_controller_intake.py \
      delivery_job_submission.py delivery_job_queries.py github_develop_resolver.py \
      github_evidence_reader.py github_evidence_validation.py github_issue_reader.py \
      trusted_github_http.py mcp_delivery_entrypoint.py jobs.py policy.py \
      mcp_jwks_verifier.py mcp_jwt_verifier.py pr_binding.py \
      protected_broker_server.py; do
    META="$(sudo -n stat -c '%u:%g:%a:%F' "$CODE/$FILE" 2>/dev/null || true)"
    if [ "$META" != "0:0:644:regular file" ]; then
      fail "untrusted or unavailable staged module: $FILE"
    fi
  done

  echo "=== 2. SEPARATED CONTROLLER AUTHENTICATOR AND WORKER ==="
  CTRL_UID="$(id -u solverit-controller 2>/dev/null || true)"
  CTRL_GID="$(id -g solverit-controller 2>/dev/null || true)"
  AUTH_UID="$(id -u solverit-github-auth 2>/dev/null || true)"
  WORKER_UID="$(id -u solverit-worker 2>/dev/null || true)"
  if [[ "$CTRL_UID" =~ ^[0-9]+$ ]] && [ "$CTRL_UID" -gt 0 ] && \
     [ "$CTRL_UID" != "$AUTH_UID" ] && [ "$CTRL_UID" != "$WORKER_UID" ] && \
     [ "$AUTH_UID" = 997 ] && [ "$WORKER_UID" = 1004 ]; then
    ok "controller, authenticator and worker have distinct nonroot UIDs"
  else
    fail "identity separation unavailable"
  fi
  if id -nG solverit-controller 2>/dev/null | tr ' ' '\n' | grep -qx solverit-app-key; then
    fail "controller must not access GitHub App private key"
  else
    ok "controller excluded from GitHub App key group"
  fi
  if id -nG solverit-worker 2>/dev/null | tr ' ' '\n' | grep -qx solverit-delivery-control; then
    fail "worker must not join privileged broker IPC group"
  else
    ok "worker excluded from broker IPC group"
  fi

  echo "=== 3. CONTROLLER DATABASE WITHOUT BROKER DATABASE ACCESS ==="
  if [ "$CTRL_ROOT" = "$(dirname "$BROKER_DB")" ]; then
    fail "controller database path collides with authenticator storage"
  fi
  DIR_META="$(sudo -n stat -c '%u:%g:%a:%F' "$CTRL_ROOT" 2>/dev/null || true)"
  DB_META="$(sudo -n stat -c '%u:%g:%a:%F' "$CTRL_DB" 2>/dev/null || true)"
  if [ "$DIR_META" = "$CTRL_UID:$CTRL_GID:700:directory" ] && \
     [ "$DB_META" = "$CTRL_UID:$CTRL_GID:600:regular file" ] && \
     ! sudo -n test -L "$CTRL_ROOT" && ! sudo -n test -L "$CTRL_DB"; then
    ok "controller job store is private and not a symlink"
  else
    fail "controller job store ownership or mode mismatch"
  fi
  BROKER_META="$(sudo -n stat -c '%u:%g:%a:%F' "$BROKER_DB" 2>/dev/null || true)"
  if [ "$BROKER_META" = "997:986:600:regular file" ]; then
    ok "existing authenticator SQLite stays independently private"
  else
    fail "authenticator protected SQLite metadata mismatch"
  fi
  if sudo -n -u solverit-controller /usr/bin/python3 -B -c \
      'import sqlite3; c=sqlite3.connect("file:/var/lib/solverit/issue88-controller/jobs.sqlite3?mode=ro", uri=True); c.execute("SELECT job_id FROM jobs LIMIT 0"); c.close()' \
      >/dev/null 2>&1; then
    ok "controller can read its existing jobs schema without writes"
  else
    fail "controller cannot inspect its existing SQLite job schema"
  fi

  echo "=== 4. NON-ACTIVATION AND SDK READINESS ==="
  if systemctl is-active --quiet solverit-issue88-github-broker.service || \
     sudo -n test -e /run/solverit-issue88-broker/broker.sock; then
    fail "broker/socket unexpectedly active during pre-activation review"
  else
    ok "broker and IPC socket remain inactive"
  fi
  if sudo -n -u solverit-controller /usr/bin/python3 -B -c \
      'import jwt, mcp.server.fastmcp' >/dev/null 2>&1; then
    ok "system controller interpreter exposes MCP SDK and JWT dependencies"
  else
    pending "pin/provision controller MCP SDK dependencies before service activation"
  fi

  echo "=== RESULT ==="
  echo "FAIL=$FAIL PENDING=$PENDING"
  if [ "$FAIL" -ne 0 ] || [ "$PENDING" -ne 0 ]; then
    echo "RESULT: NOT READY -- no service activation permitted"
    false
  else
    echo "RESULT: STRUCTURAL STAGING READY -- not an activation approval"
  fi
)
RC=$?
echo "=== CODIGO DE RETORNO: $RC ==="
echo "=== TERMINAL PRESERVADO ==="
test "$RC" -eq 0
