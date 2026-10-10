#!/usr/bin/env bash
# Issue 88: negative confinement probe against the dedicated ROOTLESS daemon.
# No host mounts, no privileges, no secret injection; test exits nonzero on breach.
set -eu
ROOTLESS_SOCKET=/run/user/1004/docker.sock
IMAGE='alpine:3.20'
if [ "$(id -un)" != "solverit-worker" ]; then
  printf '%s\n' 'Run as solverit-worker only' >&2
  exit 2
fi
if [ ! -S "$ROOTLESS_SOCKET" ]; then
  echo 'rootless socket missing' >&2
  exit 2
fi
export DOCKER_HOST="unix://$ROOTLESS_SOCKET"
docker info --format '{{json .SecurityOptions}}' | grep -q '"name=rootless"' || { echo 'not rootless' >&2; exit 2; }
docker run --rm --pull=never --name solverit-issue88-negative-probe \
  --network none --memory 512m --memory-swap 512m --cpus 1 --pids-limit 64 \
  --user 65532:65532 --read-only --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,noexec,nosuid,size=16m \
  "$IMAGE" sh -ec '
    test "$(id -u)" = 65532
    test "$(id -g)" = 65532
    test "$(awk "/^NoNewPrivs:/ {print \$2}" /proc/self/status)" = 1
    test "$(awk "/^CapEff:/ {print \$2}" /proc/self/status)" = 0000000000000000
    test "$(awk "/^CapBnd:/ {print \$2}" /proc/self/status)" = 0000000000000000
    test "$(cat /sys/fs/cgroup/memory.max)" = 536870912
    test "$(cat /sys/fs/cgroup/pids.max)" = 64
    test "$(cat /sys/fs/cgroup/cpu.max)" = "100000 100000"
    if touch /root/should-not-work 2>/dev/null; then echo "FAIL: root filesystem writable"; exit 1; fi
    touch /tmp/writable
    test ! -S /var/run/docker.sock
    test ! -S /run/user/1004/docker.sock
    test ! -e /etc/solverit
    test ! -e /home/ubuntu/.ssh
    test ! -e /run/secrets
    test -z "$(awk "NR>1 && \$2 != \"00000000\" {print}" /proc/net/route)"
    echo "PASS: basic offline confinement checks"
  '
echo 'Probe complete; no host services were changed.'
