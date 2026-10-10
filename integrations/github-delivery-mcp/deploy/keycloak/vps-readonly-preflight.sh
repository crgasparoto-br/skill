#!/bin/sh
# Issue 88 Keycloak read-only VPS preflight. Does not change system state.
printf '\n=== KEYCLOAK PREFLIGHT ===\n'
printf '\nPort 18780 listeners:\n'
ss -ltnp 2>/dev/null | grep ':18780 ' || printf 'No listener found on port 18780\n'
printf '\nCaddy service state:\n'
systemctl is-active caddy 2>/dev/null || true
printf '\nCaddy configuration locations (names only):\n'
for file in /etc/caddy/Caddyfile /etc/caddy/sites-enabled; do
  if [ -e "$file" ]; then ls -ld "$file"; fi
done
printf '\nDocker Compose availability:\n'
docker compose version 2>/dev/null || printf 'Docker Compose not available to current user\n'
printf '\nHost resource headroom:\n'
free -h
df -h /
printf '\n=== TERMINAL PRESERVADO ===\n'
