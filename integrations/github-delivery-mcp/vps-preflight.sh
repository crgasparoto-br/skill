#!/usr/bin/env bash
# Non-destructive VPS preflight. No secrets read, no containers started/stopped.
set -u
printf '%s\n' '== SolverIT Issue Delivery: VPS preflight (read-only) =='
printf 'UTC: '; date -u '+%Y-%m-%dT%H:%M:%SZ'
printf 'Host kernel: '; uname -sr
printf 'OS: '; ( . /etc/os-release; printf '%s\n' "${PRETTY_NAME:-unknown}" )
printf '%s\n' '== Resources =='
df -h /var /tmp 2>&1 || true
free -h 2>&1 || true
printf '%s\n' '== Docker runtime =='
if command -v docker >/dev/null 2>&1; then
  docker version --format 'Server: {{.Server.Version}}' 2>&1 || true
  docker ps --format '{{.Names}} {{.Status}}' 2>&1 || true
else
  printf '%s\n' 'Docker not present'
fi
printf '%s\n' '== Kernel isolation capabilities (presence only) =='
if [ -e /sys/kernel/security/apparmor ]; then echo 'AppArmor: available'; else echo 'AppArmor: not detected'; fi
if [ -e /proc/self/ns/user ]; then echo 'User namespace: available'; else echo 'User namespace: not detected'; fi
printf '%s\n' '== Mandatory manual verification =='
printf '%s\n' 'Check firewall, DNS/TLS, sandbox backend and egress policy outside this script.'
printf '%s\n' 'No configuration changed. Terminal remains open.'
