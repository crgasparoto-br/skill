#!/usr/bin/env bash
# Issue #88: READ-ONLY post-provisioning attestation.
# Never writes to /etc, /opt, /var/lib, systemd, Keycloak or GitHub.
(
  set -uo pipefail
  FAIL=0
  PENDING=0
  AUTH_UID=997
  WORKER_UID=1004
  CTRL_UID=995
  BROKER_GID=984
  CODE=/opt/solverit/issue-delivery
  DB=/var/lib/solverit/issue-delivery/protected/jobs.sqlite3
  APP_KEY=/etc/solverit/issue-delivery/secrets/github-app.pem

  ok() { printf 'PASS: %s\n' "$1"; }
  fail() { printf 'FAIL: %s\n' "$1"; FAIL=$((FAIL + 1)); }
  pending() { printf 'PENDING: %s\n' "$1"; PENDING=$((PENDING + 1)); }

  echo "=== 1. ROOT PRIVILEGES (NO PASSWORD PROMPTS) ==="
  if [ "$(sudo -n /usr/bin/id -u 2>/dev/null)" = 0 ]; then
    ok "sudo NOPASSWD works"
  else
    fail "sudo NOPASSWD not available"
  fi

  echo "=== 2. SEPARATE SERVICE IDENTITIES ==="
  if [ "$(id -u solverit-controller 2>/dev/null)" = "$CTRL_UID" ]; then
    ok "dedicated controller UID 995"
  else
    fail "unexpected controller identity"
  fi
  if [ "$(id -u solverit-github-auth 2>/dev/null)" = "$AUTH_UID" ]; then
    ok "authenticator UID 997"
  else
    fail "unexpected authenticator identity"
  fi
  if [ "$(id -u solverit-worker 2>/dev/null)" = "$WORKER_UID" ]; then
    ok "rootless worker UID 1004"
  else
    fail "unexpected rootless worker identity"
  fi
  if [ "$(getent group solverit-delivery-control | cut -d: -f3)" = "$BROKER_GID" ]; then
    ok "broker IPC group GID 984"
  else
    fail "unexpected broker group"
  fi
  for U in solverit-controller solverit-github-auth; do
    if id -nG "$U" | tr ' ' '\n' | grep -qx solverit-delivery-control; then
      ok "$U belongs to broker IPC group"
    else
      fail "$U is missing from broker IPC group"
    fi
  done
  if id -nG solverit-worker | tr ' ' '\n' | grep -qx solverit-delivery-control; then
    fail "rootless worker must NOT belong to broker group"
  else
    ok "worker excluded from broker group"
  fi
  if id -nG solverit-controller | tr ' ' '\n' | grep -qx solverit-app-key; then
    fail "controller must NOT belong to GitHub App private-key group"
  else
    ok "controller excluded from GitHub App key group"
  fi

  echo "=== 3. VERSIONED ROOT-OWNED CODE AND PRIVATE DB ==="
  if sudo -n test -f "$CODE/STAGED_COMMIT"; then
    printf 'STAGED_COMMIT: '
    sudo -n cat "$CODE/STAGED_COMMIT"
  else
    fail "staged SHA marker missing"
  fi
  for F in protected_broker_server.py broker_oauth.py app_token_broker.py; do
    META="$(sudo -n stat -c '%u:%g:%a:%F' "$CODE/$F" 2>/dev/null || true)"
    if [ "$META" = "0:0:644:regular file" ]; then
      ok "$F root-owned, read-only"
    else
      fail "$F unexpected metadata: $META"
    fi
  done
  META="$(sudo -n stat -c '%u:%g:%a:%F' "$DB" 2>/dev/null || true)"
  if [ "$META" = "997:986:600:regular file" ]; then
    ok "protected SQLite private to authenticator"
  else
    fail "protected SQLite metadata invalid: $META"
  fi

  echo "=== 4. BROKER MODULES UNDER THE ACTUAL SERVICE INTERPRETER ==="
  # DO NOT print exceptions: paths may contain private host information.
  if sudo -n -u solverit-github-auth env \
      PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$CODE" \
      /usr/bin/python3 -B -c \
      'import jwt, cryptography, broker_oauth, protected_broker_server' \
      >/dev/null 2>&1; then
    ok "systemd /usr/bin/python3 can import broker dependencies"
  else
    pending "systemd /usr/bin/python3 cannot import broker dependencies"
  fi
  if sudo -n -u solverit-github-auth /usr/bin/test -r "$APP_KEY"; then
    ok "authenticator can access existing GitHub App key (content not read)"
  else
    pending "GitHub App key not accessible at configured broker path"
  fi

  echo "=== 5. SERVICE AND KEYCLOAK ACTIVATION GATES ==="
  if systemctl -q is-active solverit-issue88-github-broker.service; then
    fail "broker unexpectedly active before independent staging approval"
  else
    ok "broker not running"
  fi
  if sudo -n /usr/bin/test -e /etc/solverit/issue-delivery/broker.env; then
    pending "broker.env exists: inspect ownership/mode privately before activation"
  else
    pending "broker.env not yet provisioned; do not start broker"
  fi
  if sudo -n /usr/bin/test -e /run/solverit-issue88-broker/broker.sock; then
    fail "broker socket exists although broker should be inactive"
  else
    ok "no broker socket exposed"
  fi
  echo "Keycloak scope solverit:deliver and independent OAuth subject mapping:"
  pending "requires verified Keycloak administrative configuration; not inferred from HTTP 200"

  echo "=== FINAL READINESS ==="
  echo "FAILED=$FAIL PENDING=$PENDING"
  if [ "$FAIL" -ne 0 ]; then
    echo "RESULT: REPROVADO -- correct safety failures before any activation"
    false
  else
    echo "RESULT: STAGING STRUCTURAL CHECKS PASSED; OPERATIONAL ACTIVATION NOT APPROVED"
    echo "Readiness attestation is not authorization to start services."
  fi
)
RC=$?
echo "=== CODIGO DE RETORNO: $RC ==="
echo "=== TERMINAL PRESERVADO ==="
test "$RC" -eq 0
