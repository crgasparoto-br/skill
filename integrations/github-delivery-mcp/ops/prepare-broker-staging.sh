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
  if [ "$(sudo -n /usr/bin/id -u 2>/dev/null || true)" != "0" ]; then
    echo "BLOQUEADO: usuario ubuntu nao possui sudo -n administrativo nao interativo."
    echo "Nenhuma identidade, codigo ou banco foi provisionado."
    false
  fi
  echo "Autorizacao sudo -n NOPASSWD confirmada por /usr/bin/id -u."
  test "$(id -u solverit-github-auth)" = 997
  test "$(id -u solverit-worker)" = 1004
  if ! getent group solverit-delivery-control >/dev/null; then
    sudo -n groupadd --system solverit-delivery-control
  fi
  if ! id solverit-controller >/dev/null 2>&1; then
    sudo -n useradd --system --user-group --no-create-home \
      --home-dir /nonexistent --shell /usr/sbin/nologin solverit-controller
  fi
  CONTROLLER_UID="$(id -u solverit-controller)"
  test "$CONTROLLER_UID" != 0
  test "$CONTROLLER_UID" != 997
  test "$CONTROLLER_UID" != 1004
  sudo -n usermod -aG solverit-delivery-control solverit-controller
  sudo -n usermod -aG solverit-delivery-control solverit-github-auth
  if id -nG solverit-worker | tr ' ' '\n' | grep -qx solverit-delivery-control; then
    echo "BLOQUEADO: worker no grupo privilegiado."
    false
  fi
  if id -nG solverit-controller | tr ' ' '\n' | grep -qx solverit-app-key; then
    echo "BLOQUEADO: controlador possui acesso a chave da GitHub App."
    false
  fi

  echo "=== 4. COPIANDO APENAS CODIGO INERTE, SEM INICIAR SERVICOS ==="
  # No code replacement is allowed while any broker process is active.
  if systemctl is-active --quiet solverit-issue88-github-broker.service; then
    echo "BLOQUEADO: broker ativo; staging nao pode modificar codigo em uso."
    false
  fi
  if sudo -n /usr/bin/test -e /run/solverit-issue88-broker/broker.sock; then
    echo "BLOQUEADO: socket preexistente; inspecionar antes de atualizar staging."
    false
  fi
  if sudo -n /usr/bin/test -L "$TARGET"; then
    echo "BLOQUEADO: caminho de staging nao pode ser symlink."
    false
  fi
  if sudo -n /usr/bin/test -e "$TARGET"; then
    META="$(sudo -n stat -c '%u:%g:%a:%F' "$TARGET")"
    if [ "$META" != "0:0:755:directory" ]; then
      echo "BLOQUEADO: staging preexistente nao e root-owned 0755."
      false
    fi
  fi
  sudo -n install -d -o root -g root -m 0755 "$TARGET"
  for FILE in \
    app_token_broker.py broker_oauth.py controller_broker_client.py \
    broker_develop_intake.py github_develop_resolver.py github_issue_reader.py \
    delivery_controller_intake.py delivery_job_submission.py delivery_job_queries.py \
    github_evidence_reader.py github_evidence_validation.py jobs.py policy.py \
    mcp_delivery_entrypoint.py pr_binding.py mcp_jwks_verifier.py mcp_jwt_verifier.py \
    protected_broker_server.py; do
    sudo -n install -o root -g root -m 0644 "$CODE/$FILE" "$TARGET/$FILE"
  done
  # Privileged OAuth preflights must never run from the operator's writable
  # extraction directory. Only install reviewed, inert scripts under root.
  if sudo -n /usr/bin/test -L "$TARGET/ops"; then
    echo "BLOQUEADO: diretorio protegido ops e symlink."
    false
  fi
  if sudo -n /usr/bin/test -e "$TARGET/ops"; then
    OPS_META="$(sudo -n stat -c '%u:%g:%a:%F' "$TARGET/ops")"
    if [ "$OPS_META" != "0:0:755:directory" ]; then
      echo "BLOQUEADO: scripts privilegiados fora de diretorio root-owned."
      false
    fi
  fi
  sudo -n install -d -o root -g root -m 0755 "$TARGET/ops"
  for FILE in check-broker-live-access.py check-broker-jwks-runtime.py verify-broker-env.py; do
    test -f "$CODE/ops/$FILE"
    sudo -n install -o root -g root -m 0644 "$CODE/ops/$FILE" "$TARGET/ops/$FILE"
  done
  echo "=== 5. VALIDANDO SQLITE PRIVADO SEM JOBS FICTICIOS ==="
  sudo -n install -d -o root -g solverit-github-auth -m 0750 \
    /var/lib/solverit/issue-delivery
  sudo -n install -d -o solverit-github-auth -g solverit-github-auth -m 0700 \
    /var/lib/solverit/issue-delivery/protected
  if sudo -n test -L "$DB"; then
    echo "BLOQUEADO: SQLite nao pode ser symlink."
    false
  fi
  if ! sudo -n test -e "$DB"; then
    sudo -n -u solverit-github-auth env PYTHONPATH="$TARGET" \
      /usr/bin/python3 -c \
      'import os; os.umask(0o077); from pr_binding import PRBindingStore; PRBindingStore("/var/lib/solverit/issue-delivery/protected/jobs.sqlite3")'
  fi
  test "$(sudo -n stat -c %u "$DB")" = 997
  test "$(sudo -n stat -c %a "$DB")" = 600
  sudo -n stat -c 'Banco: %U:%G modo=%a %n' "$DB"
  echo "=== 5B. ISOLANDO O ESTADO DO CONTROLADOR (SEM ATIVAR SERVICO) ==="
  CTRL_ROOT="/var/lib/solverit/issue88-controller"
  CTRL_DB="$CTRL_ROOT/jobs.sqlite3"
  CTRL_GID="$(id -g solverit-controller)"
  if sudo -n /usr/bin/test -L "$CTRL_ROOT" || sudo -n /usr/bin/test -L "$CTRL_DB"; then
    echo "BLOQUEADO: armazenamento do controlador nao pode conter symlinks."
    false
  fi
  if sudo -n /usr/bin/test -e "$CTRL_ROOT"; then
    CTRL_META="$(sudo -n stat -c '%u:%g:%a:%F' "$CTRL_ROOT")"
    if [ "$CTRL_META" != "$CONTROLLER_UID:$CTRL_GID:700:directory" ]; then
      echo "BLOQUEADO: diretorio do controlador preexistente fora de politica."
      false
    fi
  else
    sudo -n install -d -o solverit-controller -g solverit-controller -m 0700 "$CTRL_ROOT"
  fi
  if ! sudo -n /usr/bin/test -e "$CTRL_DB"; then
    sudo -n -u solverit-controller env PYTHONPATH="$TARGET" \
      /usr/bin/python3 -B -c \
      'import os; os.umask(0o077); from jobs import JobStore; JobStore("/var/lib/solverit/issue88-controller/jobs.sqlite3")'
  fi
  CTRL_DB_META="$(sudo -n stat -c '%u:%g:%a:%F' "$CTRL_DB")"
  if [ "$CTRL_DB_META" != "$CONTROLLER_UID:$CTRL_GID:600:regular file" ]; then
    echo "BLOQUEADO: estado do controlador sem isolamento."
    false
  fi
  echo "PASS: banco do controlador privado, independente do banco do autenticador."
  echo "=== 6. ATTESTANDO CODIGO E HEAD DE STAGING ==="
  if systemctl is-active --quiet solverit-issue88-github-broker.service; then
    echo "BLOQUEADO: broker inesperadamente ativo apos copia."
    false
  fi
  if sudo -n /usr/bin/test -e /run/solverit-issue88-broker/broker.sock; then
    echo "BLOQUEADO: socket inesperado; nao publicar marker de commit."
    false
  fi
  sudo -n -u solverit-github-auth env PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH="$TARGET" /usr/bin/python3 -B -c \
    'import broker_oauth, protected_broker_server; assert broker_oauth.DELIVERY_CLIENT == "solverit-chatgpt-mcp"'
  # Verify deployed bytes against immutable Git objects, not only a marker
  # or the operator-writable extracted workspace. No secrets are read.
  for FILE in \
    app_token_broker.py broker_oauth.py controller_broker_client.py \
    broker_develop_intake.py github_develop_resolver.py github_issue_reader.py \
    delivery_controller_intake.py delivery_job_submission.py delivery_job_queries.py \
    github_evidence_reader.py github_evidence_validation.py jobs.py policy.py \
    mcp_delivery_entrypoint.py pr_binding.py mcp_jwks_verifier.py mcp_jwt_verifier.py \
    protected_broker_server.py; do
    git -C "$WORK" show "$EXPECTED:integrations/github-delivery-mcp/$FILE" |
      sudo -n cmp - "$TARGET/$FILE" >/dev/null
  done
  for FILE in check-broker-live-access.py check-broker-jwks-runtime.py verify-broker-env.py; do
    test "$(sudo -n stat -c '%u:%g:%a:%F' "$TARGET/ops/$FILE")" = "0:0:644:regular file"
    git -C "$WORK" show "$EXPECTED:integrations/github-delivery-mcp/ops/$FILE" |
      sudo -n cmp - "$TARGET/ops/$FILE" >/dev/null
  done
  # Publish STAGED_COMMIT only after all code imports, DB checks and
  # inactive service verification pass.
  printf '%s\n' "$EXPECTED" | sudo -n tee "$TARGET/STAGED_COMMIT" >/dev/null
  sudo -n chmod 0644 "$TARGET/STAGED_COMMIT"
  sudo -n chown root:root "$TARGET/STAGED_COMMIT"
  echo "PASS: staged code imports with pinned delivery client, broker inactive."
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
