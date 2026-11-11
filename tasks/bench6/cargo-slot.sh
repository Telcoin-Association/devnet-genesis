#!/usr/bin/env bash
# cargo-slot.sh (bench 6) — run one command under one of three host-wide build slots, after waiting
# while the orchestrator holds a quiet window (an I/O probe or the harness gate must be alone).
#   tasks/bench6/cargo-slot.sh cargo <args>
# Self-contained: it shares the other session's lock directory while that exists (so both sessions
# count against the same three slots) and falls back to its own. The quiet window is the file
# tasks/bench6/QUIET; a window older than 2 h is ignored (a forgotten flag must not hang a unit).
# The lock fd is closed in the subshell that runs the command, so no descendant can hold a slot.
set -uo pipefail
HERE=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6
SHARED=/home/drtnarg/coding/telcoin/tn-workspace/shared/plans/pr-feedback-2026-11-10/locks
SLOTS="${CARGO_SLOTS:-3}"
[ "$#" -ge 1 ] || { echo "usage: cargo-slot.sh <command…>" >&2; exit 64; }
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-4}"
export NEXTEST_TEST_THREADS="${NEXTEST_TEST_THREADS:-6}"
export RUSTC_WRAPPER="${RUSTC_WRAPPER:-sccache}"
i=0
while [ -e "${HERE}/QUIET" ]; do
    [ "${i}" -eq 0 ] && echo "[b6-slot] quiet window held by the orchestrator; waiting since $(date -u +%FT%TZ)" >&2
    i=$((i + 1))
    if [ "${i}" -gt 360 ]; then echo "[b6-slot] quiet window older than 2 h; proceeding" >&2; break; fi
    sleep 20
done
n=0
while :; do
    if [ -d "${SHARED}" ] && [ -w "${SHARED}" ]; then LOCKDIR="${SHARED}"; else LOCKDIR="${HERE}/locks"; mkdir -p "${LOCKDIR}"; fi
    s=1
    while [ "${s}" -le "${SLOTS}" ]; do
        exec 8>"${LOCKDIR}/slot-${s}.lock"
        if flock -n 8; then
            echo "[b6-slot] slot ${s}: $*" >&2
            ( exec 8>&-; "$@" ); rc=$?
            exit "${rc}"
        fi
        exec 8>&-
        s=$((s + 1))
    done
    n=$((n + 1))
    if [ "${n}" -gt 1440 ]; then echo "[b6-slot] no slot free after 6 h; giving up" >&2; exit 75; fi
    sleep 15
done
