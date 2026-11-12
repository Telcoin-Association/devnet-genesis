#!/usr/bin/env bash
# orch-harness-gate.sh — bench 6, orchestrator only: hold tasks/bench6/QUIET (the build-slot wrapper, and with
# it the e2e lane's jobs, wait while it exists), run the full harness gate alone on the host, release.
#   tasks/bench6/orch-harness-gate.sh [gate.sh arguments; default --jobs 4]
# Output: HARNESS-GATE start …, the gate's own lines (the last is `GATE unittest= isolated= mutations= load= secs=`),
# HARNESS-GATE rc=<rc>. The gate's logs go to benchmark/work/bench6-scratch/gate-<UTC>/ (not /tmp: quota).
# Launch it detached and alone in its call, WITHOUT nohup:  setsid bash tasks/bench6/orch-harness-gate.sh > <log> 2>&1 < /dev/null &
# (nohup makes SIGHUP ignored in every child, and test_keygen's signal test asserts that a SIGHUP stops the node
# jobs: the gate of 2026-11-12T08:22Z failed on exactly that one subtest for this reason. setsid alone is enough:
# a process with no controlling terminal is sent no SIGHUP when the session that started it ends.)
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
QUIET="${ROOT}/tasks/bench6/QUIET"
[ ! -e "${QUIET}" ] || { echo "HARNESS-GATE a quiet window is already held (${QUIET})"; exit 2; }
trap 'rm -f "${QUIET}"' EXIT
trap 'exit 130' INT TERM
touch "${QUIET}"
cd "${ROOT}" || exit 2
GATE_LOG_DIR="${ROOT}/benchmark/work/bench6-scratch/gate-$(date -u +%Y%m%dT%H%M%SZ)"
export GATE_LOG_DIR
mkdir -p "${GATE_LOG_DIR}"
echo "HARNESS-GATE start $(date -u +%FT%TZ) head=$(git rev-parse --short HEAD) logs=${GATE_LOG_DIR} load=$(cut -d' ' -f1-3 /proc/loadavg) pid=$$"
if [ "$#" -eq 0 ]; then set -- --jobs 4; fi
bash benchmark/tests/gate.sh "$@"
rc=$?
echo "HARNESS-GATE rc=${rc} $(date -u +%FT%TZ) load=$(cut -d' ' -f1-3 /proc/loadavg)"
exit "${rc}"
