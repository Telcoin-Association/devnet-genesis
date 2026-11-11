#!/usr/bin/env bash
# cargo-slot.sh (bench 6) — run one command under a host-wide build slot, but first wait while the
# orchestrator holds a quiet window (an I/O probe or the harness gate must be alone on the host).
#   tasks/bench6/cargo-slot.sh cargo <args>
# The quiet window is the file tasks/bench6/QUIET. A window older than 2 h is ignored (a forgotten
# flag must not hang a unit for good). The slot itself is the shared three-slot wrapper.
set -uo pipefail
HERE=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6
SLOT=/home/drtnarg/coding/telcoin/tn-workspace/shared/plans/pr-feedback-2026-11-10/scripts/cargo-slot.sh
[ "$#" -ge 1 ] || { echo "usage: cargo-slot.sh <command…>" >&2; exit 64; }
i=0
while [ -e "${HERE}/QUIET" ]; do
    [ "${i}" -eq 0 ] && echo "[b6-slot] quiet window held by the orchestrator; waiting since $(date -u +%FT%TZ)" >&2
    i=$((i + 1))
    if [ "${i}" -gt 360 ]; then echo "[b6-slot] quiet window older than 2 h; proceeding" >&2; break; fi
    sleep 20
done
exec "${SLOT}" "$@"
