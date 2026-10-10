#!/bin/sh
# Read-only by default; explicit --apply is required to alter Caddy.
# Preserves the pre-existing audit-mcp route and keeps SSH open.
set -u
SOURCE="${1:-}"
MODE="${2:---check}"
CADDY=/etc/caddy/Caddyfile
SITE=auth.solveritconsultoria.com.br
if [ -z "$SOURCE" ] || [ ! -f "$SOURCE" ]; then
  printf 'Usage: sh stage-caddy-auth.sh PATH_TO_FRAGMENT [--check|--apply]\n'
  return 2 2>/dev/null || false
fi
if grep -Fq "$SITE {" "$CADDY"; then
  printf 'BLOCKED: auth hostname already configured; inspect manually.\n'
  return 1 2>/dev/null || false
fi
if ! grep -Fq 'audit-mcp.solveritconsultoria.com.br {' "$CADDY"; then
  printf 'BLOCKED: existing audit MCP route not found.\n'
  return 1 2>/dev/null || false
fi
candidate=$(mktemp /tmp/solverit-caddy-auth.XXXXXX) || return 1 2>/dev/null || false
cat "$CADDY" > "$candidate"
printf '\n' >> "$candidate"
cat "$SOURCE" >> "$candidate"
if ! caddy validate --config "$candidate"; then
  printf 'BLOCKED: Caddy candidate invalid\n'
  rm -f "$candidate"
  return 1 2>/dev/null || false
fi
if [ "$MODE" != "--apply" ]; then
  printf 'Candidate valid. No Caddy changes performed.\n'
  rm -f "$candidate"
  printf '=== TERMINAL PRESERVADO ===\n'
  return 0 2>/dev/null || true
fi
backup="/etc/caddy/Caddyfile.pre-issue88-$(date +%Y%m%d%H%M%S)"
if ! cp -p "$CADDY" "$backup"; then
  printf 'BLOCKED: backup failed\n'
  rm -f "$candidate"
  return 1 2>/dev/null || false
fi
if ! install -m 644 -o root -g root "$candidate" "$CADDY"; then
  printf 'BLOCKED: install failed; restoring backup\n'
  cp -p "$backup" "$CADDY"
  rm -f "$candidate"
  return 1 2>/dev/null || false
fi
rm -f "$candidate"
if ! systemctl reload caddy; then
  printf 'Caddy reload failed; restoring prior configuration\n'
  cp -p "$backup" "$CADDY"
  systemctl reload caddy || true
  return 1 2>/dev/null || false
fi
printf 'Auth hostname staged. Existing audit route preserved. Backup: %s\n' "$backup"
printf '=== TERMINAL PRESERVADO ===\n'
