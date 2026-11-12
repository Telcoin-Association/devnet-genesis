#!/usr/bin/env bash
# orch-quiet-jobs.sh — bench 6, orchestrator only: wait for a quiet host, hold tasks/bench6/QUIET, then run the
# quiet-host runbook's job 2 (pipelined-persist cycle bench = go/no-go gate 5) and job 1 (engine contention bench).
#   tasks/bench6/orch-quiet-jobs.sh [--deadline-hours N] [--jobs gate5,u4b]
# Quiet = no cargo / rustc / cargo-nextest / clippy-driver / telcoin-network process and a 1-minute load under
# QUIET_LOAD_MAX (default 1.0), three samples 20 s apart. The window is released on every exit path.
# Output: benchmark/work/bench6-scratch/{st-u12c,u4b}/ and one summary line per job on stdout:
#   QUIET-JOBS gate5 pass=<true|false|unknown> ...      QUIET-JOBS u4b rc=<...>      QUIET-JOBS done|gave-up
# Every run records the load before and after itself (a foreign job that starts mid-run cannot be held off).
set -uo pipefail
ROOT=/home/drtnarg/coding/telcoin/devnet-genesis
QUIET="${ROOT}/tasks/bench6/QUIET"
U0A=/home/drtnarg/coding/telcoin/tn-b6-u0a
U7=/home/drtnarg/coding/telcoin/tn-b6-u7
CYCLE_BIN="${U0A}/target/release/deps/it-15c921466125b44f"
CONT_BIN="${U7}/target/release/deps/engine_contention-ddde923d95939745"
PIN="0-3,8-11"
LOAD_MAX="${QUIET_LOAD_MAX:-1.0}"
hours=10; jobs="gate5,u4b"
while [ "$#" -gt 0 ]; do
    case "$1" in
        --deadline-hours) hours="${2:?}"; shift 2 ;;
        --jobs) jobs="${2:?}"; shift 2 ;;
        *) echo "unknown argument $1" >&2; exit 64 ;;
    esac
done
[ -x "${CYCLE_BIN}" ] || { echo "QUIET-JOBS missing ${CYCLE_BIN}"; exit 2; }
[ -x "${CONT_BIN}" ] || { echo "QUIET-JOBS missing ${CONT_BIN}"; exit 2; }
[ ! -e "${QUIET}" ] || { echo "QUIET-JOBS a quiet window is already held (${QUIET})"; exit 2; }

now() { date -u +%FT%TZ; }
busy() { pgrep -x 'cargo|rustc|cargo-nextest|clippy-driver|telcoin-network' >/dev/null 2>&1; }
load_ok() { awk -v max="${LOAD_MAX}" '{ exit !($1 < max) }' /proc/loadavg; }
snap() { echo "# $1 $(now) load=$(cut -d' ' -f1-3 /proc/loadavg) busy=$(pgrep -x 'cargo|rustc|cargo-nextest|clippy-driver|telcoin-network' | wc -l)"; }

echo "QUIET-JOBS waiting for a quiet host since $(now) (deadline ${hours} h, load under ${LOAD_MAX}, jobs ${jobs}) pid=$$"
end=$(( $(date +%s) + hours * 3600 )); ok=0; n=0
while :; do
    if ! busy && load_ok; then ok=$((ok + 1)); else ok=0; fi
    [ "${ok}" -ge 3 ] && break
    if [ "$(date +%s)" -ge "${end}" ]; then echo "QUIET-JOBS gave-up no quiet host by $(now)"; exit 75; fi
    n=$((n + 1)); [ $((n % 90)) -eq 0 ] && snap waiting
    sleep 20
done
trap 'rm -f "${QUIET}"' EXIT
trap 'exit 130' INT TERM
touch "${QUIET}"
echo "QUIET-JOBS window held $(now) load=$(cut -d' ' -f1-3 /proc/loadavg)"

case ",${jobs}," in *,gate5,*)
    OUT="${ROOT}/benchmark/work/bench6-scratch/st-u12c"; mkdir -p "${OUT}"
    export TMPDIR="${U0A}/target/tmp"; mkdir -p "${TMPDIR}"
    cd "${U0A}/crates/engine" || exit 2
    T=(--ignored --exact persist_pipeline::bench_pipeline_cycle_vs_max_phase --nocapture --test-threads 1)
    run_cycle() {  # <name> <pin 0|1> [delay ms]
        local f="${OUT}/cycle-$1.txt"
        { snap before
          if [ -n "${3:-}" ]; then export PIPELINE_CYCLE_PERSIST_DELAY_MS="$3"; else unset PIPELINE_CYCLE_PERSIST_DELAY_MS; fi
          if [ "$2" = "1" ]; then taskset -c "${PIN}" "${CYCLE_BIN}" "${T[@]}"; else "${CYCLE_BIN}" "${T[@]}"; fi
          echo "EXIT=$?"
          snap after; } > "${f}" 2>&1
        unset PIPELINE_CYCLE_PERSIST_DELAY_MS
    }
    run_cycle pinned 1
    run_cycle unpinned 0
    # persist-bound at bench 5's ratio: D = 2.44 x execute_ms - persist_ms from the unforced pinned run
    bl="$(grep -a 'BENCH pipeline_cycle' "${OUT}/cycle-pinned.txt" | tail -1)"
    ex="$(printf '%s\n' "${bl}" | sed -n 's/.* execute_ms=\([0-9.]*\).*/\1/p')"
    pe="$(printf '%s\n' "${bl}" | sed -n 's/.* persist_ms=\([0-9.]*\).*/\1/p')"
    D="$(awk -v e="${ex:-0}" -v p="${pe:-0}" 'BEGIN { d = 2.44 * e - p; if (d < 1) d = 1; printf "%d", d + 0.5 }')"
    if [ -n "${ex}" ] && [ -n "${pe}" ]; then
        run_cycle pinned-persist-bound 1 "${D}"
        run_cycle unpinned-persist-bound 0 "${D}"
    fi
    all=true; over=true; cnt=0
    for name in pinned unpinned pinned-persist-bound unpinned-persist-bound; do
        f="${OUT}/cycle-${name}.txt"
        l="$(grep -a 'BENCH pipeline_cycle' "${f}" 2>/dev/null | tail -1)"
        [ -n "${l}" ] || { all=unknown; continue; }
        cnt=$((cnt + 1))
        p="$(printf '%s\n' "${l}" | sed -n 's/.* pass=\([a-z]*\).*/\1/p')"
        o="$(printf '%s\n' "${l}" | sed -n 's/.* overlapped=\([0-9]*\)\/.*/\1/p')"
        [ "${p}" = "true" ] || { [ "${all}" = "unknown" ] || all=false; }
        [ "${o:-0}" -gt 0 ] || over=false
        echo "QUIET-JOBS gate5 ${name}: $(printf '%s\n' "${l}" | cut -c1-420)"
        grep -a '^# before\|^# after\|^EXIT=' "${f}" | tr '\n' ' '; echo
    done
    echo "QUIET-JOBS gate5 pass=${all} overlapped_everywhere=${over} runs=${cnt}/4 forced_delay_ms=${D} execute_ms=${ex:-?} persist_ms=${pe:-?} $(now)"
;; esac

case ",${jobs}," in *,u4b,*)
    OUT="${ROOT}/benchmark/work/bench6-scratch/u4b"; mkdir -p "${OUT}"
    export TMPDIR="${U7}/target/tmp"; mkdir -p "${TMPDIR}"
    cd "${U7}" || exit 2
    rcs=""
    for spec in "global c8 1" "dedicated c8 1" "global c16 0" "dedicated c16 0"; do
        # shellcheck disable=SC2086
        set -- ${spec}
        f="${OUT}/engine-contention-$1-$2.txt"
        snap before > "${f}.meta"
        if [ "$3" = "1" ]; then taskset -c "${PIN}" "${CONT_BIN}" --pool "$1" > "${f}" 2> "${f}.err"; else "${CONT_BIN}" --pool "$1" > "${f}" 2> "${f}.err"; fi
        rc=$?; echo "EXIT=${rc}" >> "${f}.meta"; snap after >> "${f}.meta"
        rcs="${rcs} $1-$2=${rc}"
    done
    echo "QUIET-JOBS u4b rc:${rcs} $(now)"
;; esac
echo "QUIET-JOBS done $(now) load=$(cut -d' ' -f1-3 /proc/loadavg)"
