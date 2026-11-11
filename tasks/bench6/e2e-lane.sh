#!/usr/bin/env bash
# e2e-lane.sh — bench 6: one e2e job on the machine at a time (the e2e suites use fixed ports).
#   tasks/bench6/e2e-lane.sh <command…>
# Takes an exclusive lock (blocks), waits while another session's attest or e2e re-run is alive
# (deadline 6 h, then gives up with rc 75), then runs the command through a host-wide build slot.
set -uo pipefail
LOCK=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/e2e-lane.lock
SLOT=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6/cargo-slot.sh
[ "$#" -ge 1 ] || { echo "usage: e2e-lane.sh <command…>" >&2; exit 64; }
exec 9>"${LOCK}"
echo "[e2e-lane] waiting for the lane lock $(date -u +%FT%TZ)" >&2
flock 9
i=0
while pgrep -f '[t]est-and-attest|[a]ttest-retry|[r]erun-e2e' >/dev/null 2>&1; do
    i=$((i + 1))
    if [ "${i}" -gt 720 ]; then echo "[e2e-lane] gave up after 6 h behind a foreign attest" >&2; exit 75; fi
    sleep 30
done
echo "[e2e-lane] lane held, running: $* $(date -u +%FT%TZ)" >&2
# the lock fd is closed in the child so no descendant (an sccache daemon, a leaked node) can keep the lane
( exec 9>&-; "${SLOT}" "$@" )
rc=$?
echo "[e2e-lane] rc=${rc} $(date -u +%FT%TZ)" >&2
exit "${rc}"
