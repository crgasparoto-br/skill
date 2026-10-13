#!/usr/bin/env bash
# Issue #88: preflight/test/provision staging ONLY. Never start services.
# Requires ISSUE88_EXPECTED_SHA to match the PR's complete, reviewed SHA.
(
  set -euo pipefail
  WORK="$HOME/projetos/skill-issue88-jobs"
  EXPECTED="$(printenv ISSUE88_EXPECTED_SHA 2>/dev/null || true)"
  BRANCH="refs/heads/feat/88-controlled-issue-delivery"
  TARGET="/opt/solverit/issue-delivery"
  DB="/var/lib/solverit/issue-delivery/protected/jobs.sqlite3"

  echo "=== 1. VALIDANDO COMMIT E EXTRAINDO CODIGO EM DIRETORIO ISOLADO ==="
  if ! [[ "$EXPECTED" =~ ^[0-9a-f]{40}$ ]]; then
    echo "BLOQUEADO: ISSUE88_EXPECTED_SHA precisa ter 40 caracteres hexadecimais."
    false
  fi
  test -d "$WORK/.git" -o -f "$WORK/.git"
  git -C "$WORK" fetch --no-tags origin "$BRANCH"
  ACTUAL="$(git -C "$WORK" rev-parse FETCH_HEAD)"
  if [ "$ACTUAL" != "$EXPECTED" ]; then
    echo "BLOQUEADO: a PR mudou; nenhum provisionamento executado."
    echo "HEAD remoto: $ACTUAL"
    false
  fi
  STAGE="$(mktemp -d "$HOME/projetos/issue88-broker-stage.XXXXXX")"
  git -C "$WORK" archive "$EXPECTED" integrations/github-delivery-mcp | tar -x -C "$STAGE"
  CODE="$STAGE/integrations/github-delivery-mcp"
  test -f "$CODE/protected_broker_server.py"
  echo "Codigo isolado: $STAGE"

  echo "=== 2. EXECUTANDO SUITE OFFLINE ANTES DE QUALQUER ALTERACAO NO SISTEMA ==="
  # Tests include test_mcp_sdk_pilot.py: PyJWT/cryptography alone are NOT enough.
  # Use the already-available pilot environment when it is complete.
  # Otherwise create a disposable environment in staging; never modify
  # system Python, the existing pilot venv or the production services.
  PYTHON="/tmp/issue88-sdk/bin/python"
  if [ ! -x "$PYTHON" ] || ! "$PYTHON" -c 'import jwt, cryptography, mcp.server.fastmcp' >/dev/null 2>&1; then
    echo "SDK MCP ausente no ambiente anterior; criando venv isolada para os testes."
    /usr/bin/python3 -m venv "$STAGE/.venv"
    PYTHON="$STAGE/.venv/bin/python"
    DEPLOG="$STAGE/dependencies.log"
    if ! "$PYTHON" -m pip install --disable-pip-version-check --no-input \
        -r "$CODE/requirements-sdk-pilot.txt" > "$DEPLOG" 2>&1; then
      echo "BLOQUEADO: falha ao instalar dependencias da suite no staging."
      echo "Log local: $DEPLOG"
      false
    fi
  fi
  if ! "$PYTHON" -c 'import jwt, cryptography, mcp.server.fastmcp' >/dev/null 2>&1; then
    echo "BLOQUEADO: ambiente de teste incompleto; nada provisionado."
    false
  fi
  "$PYTHON" -m pip freeze > "$STAGE/dependencies-resolved.txt"
  echo "Ambiente de testes: $PYTHON"
  echo "Manifesto de dependencias: $STAGE/dependencies-resolved.txt"
  LOG="$STAGE/testes.log"
  if (cd "$CODE" && PYTHONPATH="$CODE" "$PYTHON" -m unittest discover -s . -p 'test_*.py' > "$LOG" 2>&1); then
    tail -n 8 "$LOG"
  else
    tail -n 45 "$LOG"
    echo "BLOQUEADO: testes falharam. Log local: $LOG"
    false
  fi

  echo "=== 3. PROVISIONANDO IDENTIDADE SEGREGADA ==="
  sudo -v
  test "$(id -u solverit-github-auth)" = 997
  test "$(id -u solverit-worker)" = 1004
  if ! getent group solverit-delivery-control >/dev/null; then
    sudo groupadd --system solverit-delivery-control
  fi
  if ! id solverit-controller >/dev/null 2>&1; then
    sudo useradd --system --user-group --no-create-home \
      --home-dir /nonexistent --shell /usr/sbin/nologin solverit-controller
  fi
  CONTROLLER_UID="$(id -u solverit-controller)"
  test "$CONTROLLER_UID" != 0
  test "$CONTROLLER_UID" != 997
  test "$CONTROLLER_UID" != 1004
  sudo usermod -aG solverit-delivery-control solverit-controller
  sudo usermod -aG solverit-delivery-control solverit-github-auth
  if id -nG solverit-worker | tr ' ' '\n' | grep -qx solverit-delivery-control; then
    echo "BLOQUEADO: worker no grupo privilegiado."
    false
  fi
  if id -nG solverit-controller | tr ' ' '\n' | grep -qx solverit-app-key; then
    echo "BLOQUEADO: controlador possui acesso a chave da GitHub App."
    false
  fi

  echo "=== 4. COPIANDO APENAS CODIGO INERTE, SEM INICIAR SERVICOS ==="
  sudo install -d -o root -g root -m 0755 "$TARGET"
  for FILE in \
    app_token_broker.py broker_oauth.py controller_broker_client.py \
    github_evidence_reader.py github_evidence_validation.py jobs.py \
    pr_binding.py mcp_jwks_verifier.py mcp_jwt_verifier.py \
    protected_broker_server.py; do
    sudo install -o root -g root -m 0644 "$CODE/$FILE" "$TARGET/$FILE"
  done
  printf '%s\n' "$EXPECTED" | sudo tee "$TARGET/STAGED_COMMIT" >/dev/null
  sudo chmod 0644 "$TARGET/STAGED_COMMIT"
  sudo chown root:root "$TARGET/STAGED_COMMIT"

  echo "=== 5. CRIANDO SQLITE PRIVADO SEM JOBS FICTICIOS ==="
  sudo install -d -o root -g solverit-github-auth -m 0750 \
    /var/lib/solverit/issue-delivery
  sudo install -d -o solverit-github-auth -g solverit-github-auth -m 0700 \
    /var/lib/solverit/issue-delivery/protected
  if sudo test -L "$DB"; then
    echo "BLOQUEADO: SQLite nao pode ser symlink."
    false
  fi
  if ! sudo test -e "$DB"; then
    sudo -u solverit-github-auth env PYTHONPATH="$TARGET" \
      /usr/bin/python3 -c \
      'import os; os.umask(0o077); from pr_binding import PRBindingStore; PRBindingStore("/var/lib/solverit/issue-delivery/protected/jobs.sqlite3")'
  fi
  test "$(sudo stat -c %u "$DB")" = 997
  test "$(sudo stat -c %a "$DB")" = 600
  sudo stat -c 'Banco: %U:%G modo=%a %n' "$DB"
  echo "Controller UID: $CONTROLLER_UID"
  getent group solverit-delivery-control
  echo "Codigo staging em: $TARGET"
  echo "Log de testes: $LOG"
  echo "Broker desligado; nenhum servico reiniciado."
  echo "=== PREPARACAO CONCLUIDA ==="
)
RC=$?
echo "=== CODIGO DE RETORNO: $RC ==="
echo "=== TERMINAL PRESERVADO ==="
# Return failure to the calling wrapper/CI, not a false green from echo.
# This file is executed by 'bash script', never sourced in the SSH shell.
test "$RC" -eq 0
