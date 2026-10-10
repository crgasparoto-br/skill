#!/bin/sh
# Read-only by default; explicit --apply is required to alter Caddy.
# Invoke via "sh script.sh" (not source) to preserve caller shell.
# Preserves the pre-existing audit-mcp route and keeps SSH open.
set -u
main() {
SOURCE="${1:-}"
MODE="${2:---check}"
CADDY=/etc/caddy/Caddyfile
SITE=auth.solveritconsultoria.com.br
if [ -z "$SOURCE" ] || [ ! -f "$SOURCE" ]; then
  printf 'Usage: sh stage-caddy-auth.sh PATH_TO_FRAGMENT [--check|--apply]\n'
  return 2
fi
if grep -Fq "$SITE {" "$CADDY"; then
  printf 'BLOCKED: auth hostname already configured; inspect manually.\n'
  return 1
fi
if ! grep -Fq 'audit-mcp.solveritconsultoria.com.br {' "$CADDY"; then
  printf 'BLOCKED: existing audit MCP route not found.\n'
  return 1
fi
candidate=$(mktemp /tmp/solverit-caddy-auth.XXXXXX) || return 1
cat "$CADDY" > "$candidate"
printf '\n' >> "$candidate"
cat "$SOURCE" >> "$candidate"
if ! caddy validate --config "$candidate" --adapter caddyfile; then
  printf 'BLOCKED: Caddy candidate invalid\n'
  rm -f "$candidate"
  return 1
fi
if [ "$MODE" != "--apply" ]; then
  printf 'Candidate valid. No Caddy changes performed.\n'
  rm -f "$candidate"
  printf '=== TERMINAL PRESERVADO ===\n'
  return 0
fi
backup="/etc/caddy/Caddyfile.pre-issue88-$(date +%Y%m%d%H%M%S)"
if ! cp -p "$CADDY" "$backup"; then
  printf 'BLOCKED: backup failed\n'
  rm -f "$candidate"
  return 1
fi
if ! install -m 644 -o root -g root "$candidate" "$CADDY"; then
  printf 'BLOCKED: install failed; restoring backup\n'
  cp -p "$backup" "$CADDY"
  rm -f "$candidate"
  return 1
fi
rm -f "$candidate"
if ! systemctl reload caddy; then
  printf 'Caddy reload failed; restoring prior configuration\n'
  cp -p "$backup" "$CADDY"
  systemctl reload caddy || true
  return 1
fi
printf 'Auth hostname staged. Existing audit route preserved. Backup: %s\n' "$backup"
printf '=== TERMINAL PRESERVADO ===\n'

}
main "$@"
