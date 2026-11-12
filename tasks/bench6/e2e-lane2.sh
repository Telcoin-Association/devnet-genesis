#!/usr/bin/env bash
# e2e-lane2.sh — bench 6: the second e2e lane (2026-11-12). The same promise as e2e-lane.sh, one e2e job on the
# machine at a time (the e2e suites use fixed ports), for the time the first lane stands still behind a wait
# pattern that matches a shell's whole command line (tasks/lessons.md, 2026-11-12). It touches no process.
#   tasks/bench6/e2e-lane2.sh <command…>
# 1. Its own exclusive lock (e2e-lane2.lock): lane-2 jobs run one after the other.
# 2. It waits while another session's attest or e2e re-run is alive, matched on a process's program or on the
#    script a shell runs (the first two words of `ps args`), never on a whole command line; while a
#    cargo-nextest or an e2e node (telcoin-network) process runs (a first-lane job that got through, or
#    anyone's test run); and while someone else holds tasks/bench6/QUIET. Deadline 6 h, then rc 75.
# 3. It holds tasks/bench6/QUIET while the command runs: the first lane's parked jobs go through cargo-slot.sh,
#    which waits while that file exists, so none of them can start beside this one. After touching the file it
#    waits 25 s and checks step 2 once more (a job that read "no QUIET" a moment earlier is a cargo-nextest
#    process by then); if something did start, it lets go and waits again.
# 4. It takes one of the three host-wide build slots itself, with cargo-slot.sh's own locks and job limits (it
#    cannot call cargo-slot.sh, which would wait for this script's QUIET).
set -uo pipefail
HERE=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/bench6
LOCK="${HERE}/e2e-lane2.lock"
QUIET="${HERE}/QUIET"
SHARED=/home/drtnarg/coding/telcoin/tn-workspace/shared/plans/pr-feedback-2026-11-10/locks
SLOTS="${CARGO_SLOTS:-3}"
[ "$#" -ge 1 ] || { echo "usage: e2e-lane2.sh <command…>" >&2; exit 64; }
export CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-4}"
export NEXTEST_TEST_THREADS="${NEXTEST_TEST_THREADS:-6}"
export RUSTC_WRAPPER="${RUSTC_WRAPPER:-sccache}"

# foreign — true while another session's attest or e2e re-run is alive (program or script name only).
foreign() {
    ps -eo args= | awk '
        function base(p,  n, a) { n = split(p, a, "/"); return a[n] }
        {
            p0 = base($1); p1 = base($2)
            if (p0 ~ /^(test-and-attest|attest-retry|rerun-e2e)/ || p1 ~ /^(test-and-attest|attest-retry|rerun-e2e)/) found = 1
            if (p0 == "make" && $2 == "attest") found = 1
        }
        END { exit !found }'
}
# testing — true while any nextest run or e2e node is alive.
testing() { pgrep -x 'cargo-nextest|telcoin-network' >/dev/null 2>&1; }

exec 9>"${LOCK}"
echo "[e2e-lane2] waiting for the lane-2 lock $(date -u +%FT%TZ)" >&2
flock 9
mine=0
trap '[ "${mine}" = 1 ] && rm -f "${QUIET}"' EXIT
trap 'exit 130' INT TERM
i=0
while :; do
    if [ ! -e "${QUIET}" ] && ! foreign && ! testing; then
        touch "${QUIET}"; mine=1
        sleep 25
        if ! foreign && ! testing; then break; fi
        rm -f "${QUIET}"; mine=0
        echo "[e2e-lane2] another job started while the window was being taken; waiting again $(date -u +%FT%TZ)" >&2
    fi
    i=$((i + 1))
    if [ "${i}" -gt 720 ]; then echo "[e2e-lane2] gave up after 6 h $(date -u +%FT%TZ)" >&2; exit 75; fi
    sleep 30
done
echo "[e2e-lane2] lane held, QUIET held, running: $* $(date -u +%FT%TZ)" >&2
n=0
while :; do
    if [ -d "${SHARED}" ] && [ -w "${SHARED}" ]; then LOCKDIR="${SHARED}"; else LOCKDIR="${HERE}/locks"; mkdir -p "${LOCKDIR}"; fi
    s=1
    while [ "${s}" -le "${SLOTS}" ]; do
        exec 8>"${LOCKDIR}/slot-${s}.lock"
        if flock -n 8; then
            echo "[e2e-lane2] slot ${s}" >&2
            # both lock fds are closed in the child so no descendant (an sccache daemon, a leaked node) can keep them
            ( exec 8>&- 9>&-; "$@" ); rc=$?
            echo "[e2e-lane2] rc=${rc} $(date -u +%FT%TZ)" >&2
            exit "${rc}"
        fi
        exec 8>&-
        s=$((s + 1))
    done
    n=$((n + 1))
    if [ "${n}" -gt 1440 ]; then echo "[e2e-lane2] no slot free after 6 h; giving up" >&2; exit 75; fi
    sleep 15
done
