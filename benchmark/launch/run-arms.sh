#!/usr/bin/env bash
#
# run-arms.sh — walk the run-1 arm plan on a live bench fleet: per arm, apply it by rolling restart
# (tools/params-apply.sh), wait until it is ready, run its steps (blasts of a fixed type, idle
# windows), close it; stop safely at the first problem and print the command that resumes there.
# launch.sh's `arms` segment runs it detached.
#
# Usage: benchmark/launch/run-arms.sh [--plan <file>] [--from-arm <k|name> [--from-step <n>]]
#                                     [--only-arm <k|name> [--from-step <n>]] [--dry-run]
#   --plan <file>       the walk [RUN_ARMS_PLAN, else benchmark/launch/bench6-run1.plan]; format in that file and README.md
#   --from-arm <k>      start at arm k (0 = the plan's first arm line; or the arm's name), then go on
#   --only-arm <k>      run arm k alone
#   --from-step <n>     with either: begin that arm at its step n (1 = its first step)
#   --dry-run           print the whole walk, every driver command with its environment; call nothing
# Needs BENCH_RUN_ID (launch.sh exports the env file). Exit: 0 ARMS_DONE (or a dry run), 1 ARMS_STOPPED
# (the fleet is left as it is), 2 refused before anything ran (arguments, plan), 128 + the signal's
# number for any ARMS_STOPPED after a signal (143 TERM, 130 INT, 129 HUP). From ARMS_START on, everything
# it prints is also appended to results/<run>/logs/run-arms-<segment>-<UTC>.log as it is printed
# (start_walk_log).
#
# TERM, INT or HUP (from ARMS_START on): nothing new starts. A driver call that is running (an apply,
# a mark or close, a fund, a blast run, a health check) is left alone and finishes; the walk prints
# ARMS_STOPPING when the signal comes and stops when the driver returns, reason signal-<SIG>, its arm
# left open, with the usual ARMS_RESUME line. A wait between calls (the ready time, the pool gate,
# the epoch boundary, the idle window) ends at once; an idle window cut short still gets its
# --end-mark. A second signal changes nothing. Under launch.sh only TERM arrives (the detached shell
# and its children start with INT and HUP ignored).
#
# Per arm (k): the recorded name is the arm file's `name`, or <name>-r<N> when the run's manifest
# already records that name (a re-applied arm: the arm tool refuses a recorded name).
#   step 0   params-apply.sh --from-config --arm-file <file> --arm <name>: stop on PA_FAIL or PARAMS_FAIL
#            (a node failed its restart or readback), on two PA_GUARD_DEFER lines, on rc != 0, or when
#            no ARM_READY line came; then wait until its ready= time (at most RUN_ARMS_READY_MAX_WAIT_SECS)
#   step n   one step of the plan line: I = params-apply --mark idle-<n>, RUN_ARMS_IDLE_SECS, --end-mark;
#            a blast type = benchmark-blast.sh fund, then run, under the next free BENCH_RUN_INDEX with
#            the type's environment. Before a saturated blast (M4, M16, M16s) every node's queued pool
#            must be below RUN_ARMS_MAX_QUEUED. A failed blast is tried once more (same type, next index)
#            unless the blast aborted on fleet health; a second failure stops the run.
#   close    params-apply.sh --from-config --close-arm <name>
# After step 0 and after every step: the health check (benchmark-blast.sh status: each node's newest
# BENCH_STATUS line), which stops on a root disk above RUN_ARMS_MAX_DISK_PCT or fatal_db > 0. After a
# blast: a new manifest .commit_stalls[] entry longer than RUN_ARMS_STALL_SECS stops the run.
#
# Lines it prints (tags, at the start of a line):
#   ARMS_START plan=<file> run=<id> arms=<k..k> from_step=<n> <UTC>
#   ARMS_ARM k=<k> arm=<name> file=<file> steps=<steps>
#   ARMS_READY arm=<name> ready=<UTC> wait=<s>
#   ARMS_POOL arm=<name> step=<n> verdict=<ok|high|unknown|off> queued_max=<q> (<node>) read=<n>/<m> limit=<q> <UTC>
#   ARMS_EPOCH arm=<name> step=<n> boundary=<UTC> launch_at=<UTC> offset=<s> lead=<s>
#   ARMS_BLAST arm=<name> step=<n> kind=<type> index=<i> attempt=<a> fund_rc=<rc> run_rc=<rc|-> <UTC>
#   ARMS_RETRY arm=<name> step=<n> kind=<type> index=<i> reason=<...>
#   ARMS_HEALTH arm=<name> after=<step> verdict=<ok|stop|unknown|off> read=<n>/<m> disk_max=<pct> (<node>) fatal_db=<n> <UTC>
#   ARMS_STEP arm=<name> step=<n> kind=<apply|I|L|M4|M16|M16s|close> rc=<n> <UTC>
#   ARMS_DONE arms=<n> blasts=<n> <UTC>
#   ARMS_STOPPING arm=<name> step=<n> signal=<SIG> after=<what|none> pid=<pid|-> <UTC>
#   ARMS_STOPPED arm=<name> step=<n> reason=<reason> <UTC>
#   ARMS_RESUME <the exact command that resumes the walk>
# Knobs (defaults in brackets): RUN_ARMS_MAX_QUEUED [1000; 0 = no pool gate], RUN_ARMS_POOL_WAIT_SECS
# [600], RUN_ARMS_POOL_POLL_SECS [30], RUN_ARMS_PROM_URL [BENCH_PROM_URL, else the bench-obs forward
# http://127.0.0.1:<BENCH_OBS_PROM_LOCAL_PORT, 19090>/api/v1], RUN_ARMS_IDLE_SECS [300],
# RUN_ARMS_READY_MAX_WAIT_SECS [600], RUN_ARMS_HEALTH_SECS [180; 0 = no health check],
# RUN_ARMS_MAX_DISK_PCT [BENCH_ABORT_DISK_PCT, 85], RUN_ARMS_STALL_SECS [BENCH_ABORT_STALL_SECS, 120],
# RUN_ARMS_RPC_URL [http://localhost:18545, the run's RPC tunnel], RUN_ARMS_EPOCH_OFFSET_SECS [half
# the mixed phase], RUN_ARMS_EPOCH_WAIT_MAX_SECS [1500], RUN_ARMS_FIRST_INDEX [0], RUN_ARMS_PLAN [the plan
# when no --plan is given; unset or empty = benchmark/launch/bench6-run1.plan; an env file pins it].
# This script cannot source benchmark/config.sh (its caller allowlist): the defaults above that mirror
# config.sh are checked against it by tests/test_launch.py.

set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="$(cd "${SELF_DIR}/../.." && pwd)"
readonly PA=benchmark/tools/params-apply.sh BLAST=benchmark/benchmark-blast.sh SCHED=benchmark/recovery-schedule.py
readonly TYPES="I L M4 M16 M16s" SATURATED=" M4 M16 M16s " EPOCH_TYPES=" M16 M16s "
readonly HEALTH_ABORTS=" disk-full batch-cache-cliff quorum-lost node-stalled obs-memory "

utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
now() { date -u +%s; }
iso() { jq -rn --argjson t "$1" '$t | todateiso8601'; }
WALK_LOG="" WALK_TEES=""
# reap <pid> — wait for a child of this shell until it has ended, through any trapped signal (a
# signal makes `wait` return early while the child still runs); its exit status in REAPED. A pid
# that is not this shell's child (wait: 127) ends the wait at once.
REAPED=0
reap() {
    local r r2
    while :; do
        r=0; wait "$1" 2>/dev/null || r=$?
        [ "${r}" -gt 128 ] && kill -0 "$1" 2>/dev/null || break
    done
    # The signal came as the child ended: ask once more for the child's own status.
    if [ "${r}" -gt 128 ]; then r2=0; wait "$1" 2>/dev/null || r2=$?; [ "${r2}" = 127 ] || r="${r2}"; fi
    REAPED="${r}"
}
# leave <rc> — exit <rc> once both copies of the walk's log (start_walk_log) hold every line it
# printed: its own ends close first, then it waits for the two tees. Before the log starts (and in a
# command substitution, whose wait finds no tee) it is a plain exit.
leave() {
    local p
    if [ -n "${WALK_TEES}" ]; then
        exec >/dev/null 2>&1
        # shellcheck disable=SC2086  # two pids, split on purpose
        for p in ${WALK_TEES}; do reap "${p}"; done
    fi
    exit "$1"
}

# --- signals ---------------------------------------------------------------------------------------
# From ARMS_START on, TERM, INT and HUP only set SIG_NAME (on_signal): the driver that runs as
# CHILD_PID is left alone, a wait between calls (nap) ends, and the walk stops at its next
# sig_point with reason signal-<SIG> and exit 128 + the signal's number.
SIG_NAME="" SIG_RC="" CHILD_PID="" CHILD_WHAT="" NAP_PID="" CUR_STEP=0
on_signal() { # <SIG> <rc>
    if [ -n "${SIG_NAME}" ]; then
        echo "  run-arms: $1 again: it changes nothing; still stopping after ${CHILD_WHAT:-the wait in progress}${CHILD_PID:+ (pid ${CHILD_PID})}"
        return 0
    fi
    SIG_NAME="$1" SIG_RC="$2"
    echo "ARMS_STOPPING arm=${CUR_NAME:-?} step=${CUR_STEP} signal=$1 after=${CHILD_WHAT:-none} pid=${CHILD_PID:--} $(utc)"
    if [ -n "${CHILD_WHAT}" ]; then
        echo "  stopping after ${CHILD_WHAT}${CHILD_PID:+ (pid ${CHILD_PID})}: it runs to its end, nothing new starts (README.md, Stop and resume)"
    fi
    if [ -n "${NAP_PID}" ]; then kill "${NAP_PID}" 2>/dev/null || true; fi
}
# nap <secs> — sleep, cut short by a signal.
nap() {
    [ -z "${SIG_NAME}" ] || return 0
    sleep "$1" &
    NAP_PID=$!
    # a signal between the start and the line above found no NAP_PID to end
    if [ -n "${SIG_NAME}" ]; then kill "${NAP_PID}" 2>/dev/null || true; fi
    reap "${NAP_PID}"
    NAP_PID=""
}
die() { echo "run-arms: $*" >&2; leave 2; }
bounded() {
    local s="$1"; shift
    if command -v timeout >/dev/null 2>&1; then timeout "${s}" "$@"; return; fi
    perl -e '$s = shift; alarm $s; exec @ARGV or exit 127' "${s}" "$@"
}
num_or() { case "${1:-}" in ''|*[!0-9]*) printf '%s' "$2" ;; *) printf '%s' "$1" ;; esac; }

# --- arguments -------------------------------------------------------------------------------------
PLAN="${RUN_ARMS_PLAN:-benchmark/launch/bench6-run1.plan}" FROM_ARM="" ONLY_ARM="" FROM_STEP="" DRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help) sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        --dry-run) DRY=1; shift; continue ;;
        --plan|--from-arm|--only-arm|--from-step) [ $# -ge 2 ] || die "$1 needs a value" ;;
        *) die "unknown argument '$1' (--help)" ;;
    esac
    case "$1" in
        --plan) PLAN="$2" ;;
        --from-arm) FROM_ARM="$2" ;;
        --only-arm) ONLY_ARM="$2" ;;
        --from-step) FROM_STEP="$2" ;;
    esac
    shift 2
done
[ -z "${FROM_ARM}" ] || [ -z "${ONLY_ARM}" ] || die "give --from-arm or --only-arm, not both"
[ -z "${FROM_STEP}" ] || [ -n "${FROM_ARM}${ONLY_ARM}" ] || die "--from-step needs --from-arm or --only-arm"
case "${FROM_STEP:-1}" in ''|*[!0-9]*|0*) die "--from-step '${FROM_STEP}' must be a positive integer" ;; esac
RUN="${BENCH_RUN_ID:-}"
[[ "${RUN}" =~ ^r[0-9]{8}-[0-9]{4}$ ]] || die "BENCH_RUN_ID '${RUN}' is not rYYYYMMDD-HHMM (launch.sh exports it from the env file)"
cd "${ROOT}"
RESULTS="benchmark/results/${RUN}"
MANIFEST="${RESULTS}/manifest.json"

MAXQ="$(num_or "${RUN_ARMS_MAX_QUEUED:-}" 1000)"
POOL_WAIT="$(num_or "${RUN_ARMS_POOL_WAIT_SECS:-}" 600)"
POOL_POLL="$(num_or "${RUN_ARMS_POOL_POLL_SECS:-}" 30)"
PROM="${RUN_ARMS_PROM_URL:-${BENCH_PROM_URL:-http://127.0.0.1:${BENCH_OBS_PROM_LOCAL_PORT:-19090}/api/v1}}"
IDLE_SECS="$(num_or "${RUN_ARMS_IDLE_SECS:-}" 300)"
READY_MAX="$(num_or "${RUN_ARMS_READY_MAX_WAIT_SECS:-}" 600)"
HEALTH_SECS="$(num_or "${RUN_ARMS_HEALTH_SECS:-}" 180)"
MAX_DISK="$(num_or "${RUN_ARMS_MAX_DISK_PCT:-}" "$(num_or "${BENCH_ABORT_DISK_PCT:-}" 85)")"
STALL_SECS="$(num_or "${RUN_ARMS_STALL_SECS:-}" "$(num_or "${BENCH_ABORT_STALL_SECS:-}" 120)")"
RPC="${RUN_ARMS_RPC_URL:-http://localhost:18545}"
EPOCH_OFFSET="${RUN_ARMS_EPOCH_OFFSET_SECS:-}"
EPOCH_WAIT_MAX="$(num_or "${RUN_ARMS_EPOCH_WAIT_MAX_SECS:-}" 1500)"
FIRST_INDEX="$(num_or "${RUN_ARMS_FIRST_INDEX:-}" 0)"

# --- the plan --------------------------------------------------------------------------------------
# One arm per line: <arm> <step> [<step> ...]; # starts a comment. <arm> is an arm file name in
# benchmark/arms/ (".arm" optional) or a path from the repo root; a step is a type of TYPES, and M16 or
# M16s may carry @epoch (an epoch boundary inside its mixed phase).
A_FILE=() A_NAME=() A_STEPS=()
[ -f "${PLAN}" ] || die "plan '${PLAN}' is not a file"
ln=0
while IFS= read -r line || [ -n "${line}" ]; do
    ln=$((ln + 1))
    line="${line%%#*}"
    read -r -a w <<< "${line}" || true
    [ "${#w[@]}" -gt 0 ] || continue
    [ "${#w[@]}" -ge 2 ] || die "${PLAN}:${ln}: arm '${w[0]}' has no step"
    f="${w[0]}"
    case "${f}" in */*) ;; *) f="benchmark/arms/${f%.arm}.arm" ;; esac
    [ -f "${f}" ] || die "${PLAN}:${ln}: arm file '${f}' does not exist"
    name="$(sed -n 's/^[[:space:]]*name[[:space:]][[:space:]]*\([a-z0-9][a-z0-9-]*\)[[:space:]]*$/\1/p' "${f}" | head -n 1)"
    [ -n "${name}" ] || die "${PLAN}:${ln}: ${f} has no valid name line"
    steps=""
    for s in "${w[@]:1}"; do
        t="${s%@epoch}"
        case " ${TYPES} " in *" ${t} "*) ;; *) die "${PLAN}:${ln}: unknown step '${s}' (types: ${TYPES}; M16 and M16s may carry @epoch)" ;; esac
        [ "${t}" = "${s}" ] || case "${EPOCH_TYPES}" in *" ${t} "*) ;; *) die "${PLAN}:${ln}: @epoch only on M16 or M16s, not '${s}'" ;; esac
        steps="${steps:+${steps} }${s}"
    done
    A_FILE+=("${f}"); A_NAME+=("${name}"); A_STEPS+=("${steps}")
done < "${PLAN}"
NA="${#A_FILE[@]}"
[ "${NA}" -gt 0 ] || die "${PLAN} lists no arm"

# arm_index <k|name> — the plan position of an arm.
arm_index() {
    local i hit=""
    case "$1" in
        ''|*[!0-9]*) for i in "${!A_NAME[@]}"; do
                         if [ "${A_NAME[$i]}" = "$1" ]; then [ -z "${hit}" ] || die "arm '$1' is on more than one plan line: give its number"; hit="${i}"; fi
                     done
                     [ -n "${hit}" ] || die "no arm named '$1' in ${PLAN}" ;;
        *) [ "$1" -lt "${NA}" ] || die "arm ${1} is past the plan's last arm ($((NA - 1)))"; hit="$1" ;;
    esac
    printf '%s' "$((10#${hit}))"
}
K0=0 K1=$((NA - 1)) ONLY=0
if [ -n "${FROM_ARM}" ]; then K0="$(arm_index "${FROM_ARM}")"; fi
if [ -n "${ONLY_ARM}" ]; then K0="$(arm_index "${ONLY_ARM}")"; K1="${K0}"; ONLY=1; fi
STEP0="${FROM_STEP:-1}"
read -r -a w0 <<< "${A_STEPS[$K0]}"
[ "${STEP0}" -le $(( ${#w0[@]} + 1 )) ] || die "--from-step ${STEP0}: arm ${A_NAME[$K0]} has ${#w0[@]} step(s)"

# --- type environments -----------------------------------------------------------------------------
# type_env <type> <index> — the NAME=value words of one blast of that type (run 1: no chaos, no lag).
# L and M4 use the bench-5 light phases and its light start delay; M16 and M16s are load blasts.
type_env() {
    local kind snd win wu mix cd tail=0
    case "$1" in
        L)    kind=light snd=8   win=16 wu=60  mix=360 cd=60 ;;
        M4)   kind=light snd=600 win=4  wu=60  mix=360 cd=60 ;;
        M16)  kind=load  snd=600 win=16 wu=120 mix=480 cd=180; tail="$(num_or "${BENCH_TAIL_SCAN_SECS:-}" 0)" ;;
        M16s) kind=load  snd=600 win=16 wu=120 mix=300 cd=180 ;;
    esac
    printf 'BENCH_RUN_INDEX=%s BENCH_BLAST_KIND=%s BENCH_SENDERS=%s BENCH_WINDOW=%s BENCH_WARMUP_SECS=%s BENCH_DURATION_SECS=%s BENCH_COOLDOWN_SECS=%s BENCH_TAIL_SCAN_SECS=%s BENCH_LIGHT_LOAD=0 BENCH_CHAOS=0 BENCH_LAG_INJECT=0 BENCH_LOG_RATE_CHECK=1' \
        "$2" "${kind}" "${snd}" "${win}" "${wu}" "${mix}" "${cd}" "${tail}"
}
type_field() { type_env "$1" 0 | tr ' ' '\n' | sed -n "s/^$2=//p"; }

# --- state -----------------------------------------------------------------------------------------
LAST_INDEX="" USED_NAMES=" " CUR_NAME="" BLASTS=0
mjq() { [ -f "${MANIFEST}" ] && jq -r "$@" "${MANIFEST}" 2>/dev/null; }

# next_index — one past every BENCH_RUN_INDEX the run used (manifest .blast, .fund, blasts[],
# blast_runs[], the blast-<i>-*/ and funder-<i>-*/ archives) and every index this walk handed out.
next_index() {
    local m d i
    m="$(mjq '[.blast.run_index?, .fund.run_index?, (.blasts // [])[].index?, (.blast_runs // [])[].index?]
              | map(select(type == "number")) | max // empty' || true)"
    for d in "${RESULTS}"/blast-[0-9]*-* "${RESULTS}"/funder-[0-9]*-*; do
        [ -d "${d}" ] || continue
        i="${d##*/}"; i="${i#*-}"; i="${i%%-*}"
        case "${i}" in ''|*[!0-9]*) continue ;; esac
        if [ -z "${m}" ] || [ "${i}" -gt "${m}" ]; then m="${i}"; fi
    done
    if [ -n "${LAST_INDEX}" ] && { [ -z "${m}" ] || [ "${LAST_INDEX}" -gt "${m}" ]; }; then m="${LAST_INDEX}"; fi
    if [ -z "${m}" ]; then printf '%s' "${FIRST_INDEX}"; else printf '%s' "$((m + 1))"; fi
}

# pick_name <name> — <name> unless the manifest or this walk has it; then <name>-r2, -r3, ...
pick_name() {
    local recorded n c
    recorded=" $(mjq '[(.param_arms // [])[] | .name? | strings] | join(" ")' || true) "
    c="$1" n=1
    while case "${recorded}${USED_NAMES}" in *" ${c} "*) true ;; *) false ;; esac; do
        n=$((n + 1)); c="$1-r${n}"
        [ "${n}" -lt 100 ] || die "no free recorded name for arm $1"
    done
    printf '%s' "${c}"
}

resume_cmd() { # <k> <step>
    local sel="--from-arm $1"
    [ "${ONLY}" = 0 ] || sel="--only-arm $1"
    [ "$2" -le 1 ] || sel="${sel} --from-step $2"
    if [ -n "${LAUNCH_ENV_FILE:-}" ]; then
        printf 'benchmark/launch/launch.sh %s arms --plan %s %s' "${LAUNCH_ENV_FILE}" "${PLAN}" "${sel}"
    else
        printf 'BENCH_RUN_ID=%s benchmark/launch/run-arms.sh --plan %s %s' "${RUN}" "${PLAN}" "${sel}"
    fi
}
# stop_rc — 1, or 128 + the signal's number once the walk was signalled (whatever the stop's reason).
stop_rc() { if [ -n "${SIG_NAME}" ]; then echo "${SIG_RC}"; else echo 1; fi; }
# stop <k> <step> <reason> <resume-step> — the fleet is left as it is.
stop() {
    echo "ARMS_STOPPED arm=${CUR_NAME:-${A_NAME[$1]}} step=$2 reason=$3 $(utc)"
    echo "ARMS_RESUME $(resume_cmd "$1" "$4")"
    leave "$(stop_rc)"
}
# owe_close <k> <step> <reason> — stop with every step of arm k done and its close not: the next arm's
# apply closes it, so the walk resumes there; after the last arm only the close is owed.
owe_close() {
    if [ "$1" -lt "${K1}" ]; then stop "$(($1 + 1))" "$2" "$3" 1; fi
    echo "ARMS_STOPPED arm=${CUR_NAME} step=$2 reason=$3 $(utc)"
    echo "ARMS_RESUME BENCH_RUN_ID=${RUN} ${PA} --from-config --close-arm ${CUR_NAME}"
    leave "$(stop_rc)"
}
# sig_point <k> <step> <resume-step> — after a signal, stop here (reason signal-<SIG>, the arm left
# open); else go on. A resume past the arm's last step owes the arm's close.
sig_point() {
    local w
    [ -n "${SIG_NAME}" ] || return 0
    read -r -a w <<< "${A_STEPS[$1]}"
    if [ "$3" -gt "${#w[@]}" ] && [ -n "${CUR_NAME}" ]; then owe_close "$1" "$2" "signal-${SIG_NAME}"; fi
    stop "$1" "$2" "signal-${SIG_NAME}" "$3"
}
step_line() { echo "ARMS_STEP arm=${CUR_NAME} step=$1 kind=$2 rc=$3 $(utc)"; }

# call <what> <out-file> <cmd...> — run a driver, its output to this log and to <out-file> (a tee
# reading a FIFO), as the walk's running child <what>: a signal leaves it alone (on_signal), and
# call waits for its end and the tee's. Its rc.
call() {
    local what="$1" out="$2" tee_pid rc
    shift 2
    echo ">>> $(utc) $*"
    tee "${out}" < "${TMP}/call" &
    tee_pid=$!
    CHILD_WHAT="${what}"
    "$@" > "${TMP}/call" 2>&1 &
    CHILD_PID=$!
    reap "${CHILD_PID}"; rc="${REAPED}"
    CHILD_PID="" CHILD_WHAT=""
    reap "${tee_pid}"
    return "${rc}"
}
sleep_until() { local t="$1" d; while [ -z "${SIG_NAME}" ]; do d=$(( t - $(now) )); [ "${d}" -gt 0 ] || return 0; [ "${d}" -le 30 ] || d=30; nap "${d}"; done; }
TMP="$(mktemp -d "${TMPDIR:-/tmp}/run-arms.XXXXXX")"
trap 'rm -rf "${TMP}"' EXIT
mkfifo "${TMP}/call" || die "cannot make a FIFO in ${TMP}"

# start_walk_log — from ARMS_START on, everything the walk prints (its tags, each driver's output, its
# own errors) is also appended to results/<run>/logs/run-arms-<segment>-<UTC>.log as it is printed:
# <segment> is LAUNCH_SEGMENT (launch.sh's `arms`), else `hand`. The archive and the bundle read
# results/, never tasks/, and a killed walk leaves every line it printed. What the caller sees (the
# segment log in tasks/bench6/<run>/, a terminal) is unchanged. A tee per stream reads a FIFO, so the
# walk knows both pids (leave waits for them, then launch.sh's rc line is the last line of its log);
# each tee ignores HUP, INT, TERM and PIPE and ends when every writer closed its FIFO, so the output
# of a driver that outlives a killed walk reaches both copies.
start_walk_log() {
    local n=0 seg="${LAUNCH_SEGMENT:-hand}"
    case "${seg}" in ''|*[!a-z0-9-]*) seg=hand ;; esac
    mkdir -p "${RESULTS}/logs" || die "cannot create ${RESULTS}/logs"
    until WALK_LOG="${RESULTS}/logs/run-arms-${seg}-$(date -u +%Y%m%dT%H%M%SZ).log"; ( set -C; : > "${WALK_LOG}" ) 2>/dev/null; do
        n=$((n + 1)); [ "${n}" -lt 5 ] || die "no free log name in ${RESULTS}/logs"
        sleep 1
    done
    mkfifo "${TMP}/out" "${TMP}/err" || die "cannot make the log FIFOs in ${TMP}"
    ( trap '' HUP INT TERM PIPE; exec tee -i -a "${WALK_LOG}" ) < "${TMP}/out" &
    WALK_TEES="$!"
    ( trap '' HUP INT TERM PIPE; exec tee -i -a "${WALK_LOG}" >&2 ) < "${TMP}/err" &
    WALK_TEES="${WALK_TEES} $!"
    exec > "${TMP}/out" 2> "${TMP}/err"
}

# --- checks between steps --------------------------------------------------------------------------
expected_nodes() {
    local c=0
    if [ -f "${RESULTS}/nodes.txt" ]; then c="$(grep -cvE '^[[:space:]]*(#|$)' "${RESULTS}/nodes.txt" || true)"; fi
    printf '%s' "$(num_or "${c}" 0)"
}

# health <k> <after-step> — each node's newest BENCH_STATUS line (benchmark-blast.sh status, read-only
# serial console reads, bounded). An unreadable status never stops the run.
health() {
    local k="$1" after="$2" at out rc=0 n=0 m pct fatal fsum=0 dmax=-1 dnode="" fnode="" verdict=ok line node
    at=$((after + 1)); [ "${after}" != 0 ] || at="${first}"
    sig_point "${k}" "${after}" "${at}"
    if [ "${HEALTH_SECS}" = 0 ]; then echo "ARMS_HEALTH arm=${CUR_NAME} after=${after} verdict=off $(utc)"; return 0; fi
    CHILD_WHAT="health-${after}"
    bounded "${HEALTH_SECS}" "${BLAST}" status > "${TMP}/health" 2>&1 &
    CHILD_PID=$!
    reap "${CHILD_PID}"; rc="${REAPED}"
    CHILD_PID="" CHILD_WHAT=""
    out="$(cat "${TMP}/health")"
    while IFS= read -r line; do
        node="$(printf '%s' "${line}" | sed -n 's/^[[:space:]]*\([A-Za-z0-9._-]*\): BENCH_STATUS .*/\1/p')"
        [ -n "${node}" ] || continue
        n=$((n + 1))
        pct="$(printf '%s' "${line}" | tr ' ' '\n' | sed -n 's/^root_used_pct=//p' | tail -n 1)"
        fatal="$(printf '%s' "${line}" | tr ' ' '\n' | sed -n 's/^fatal_db=//p' | tail -n 1)"
        case "${pct}" in ''|*[!0-9]*) ;; *) if [ "${pct}" -gt "${dmax}" ]; then dmax="${pct}"; dnode="${node}"; fi ;; esac
        case "${fatal}" in ''|*[!0-9]*) ;; *) if [ "${fatal}" -gt 0 ]; then fsum=$((fsum + fatal)); fnode="${fnode:-${node}}"; fi ;; esac
    done <<< "${out}"
    m="$(expected_nodes)"
    if [ "${fsum}" -gt 0 ] || [ "${dmax}" -gt "${MAX_DISK}" ]; then verdict=stop
    elif [ "${rc}" != 0 ] || [ "${n}" = 0 ] || [ "${n}" -lt "${m}" ]; then verdict=unknown; fi
    echo "ARMS_HEALTH arm=${CUR_NAME} after=${after} verdict=${verdict} read=${n}/${m} disk_max=$([ "${dmax}" -ge 0 ] && echo "${dmax} (${dnode})" || echo '?') fatal_db=${fsum} $(utc)"
    [ "${verdict}" != unknown ] || echo "  (status rc=${rc}; an unreadable node is not a stop; watch it: README.md, Monitor)"
    [ "${fsum}" = 0 ] || stop "${k}" "${after}" "fatal-db-${fnode}" "$((after + 1))"
    [ "${dmax}" -le "${MAX_DISK}" ] || stop "${k}" "${after}" "disk-${dnode}-${dmax}pct" "$((after + 1))"
    sig_point "${k}" "${after}" "${at}"
    return 0
}

# pool_read — "<verdict> <queued_max> <node> <read> <expected>" from bench-obs's Prometheus (the
# query of benchmark-blast.sh pool_at_start, queued sub-pool only, max by node, one bounded read).
pool_read() {
    local q raw rows m n top
    q='max by (node) (reth_transaction_pool_queued_pool_transactions{network="bench"})'
    raw="$(bounded 25 curl -sS --max-time 20 --get --data-urlencode "query=${q}" "${PROM}/query" 2>/dev/null)" || raw=""
    rows="$(printf '%s' "${raw}" | jq -r 'select(.status == "success") | .data.result[] | "\(.value[1] | tonumber | floor) \(.metric.node // "?")"' 2>/dev/null)" || rows=""
    m="$(expected_nodes)"
    n="$(printf '%s' "${rows}" | grep -c . || true)"
    top="$(printf '%s\n' "${rows}" | grep . | sort -rn | head -n 1 || true)"
    if [ -n "${top}" ] && [ "${top%% *}" -ge "${MAXQ}" ]; then echo "high ${top} ${n} ${m}"
    elif [ -z "${top}" ] || [ "${n}" -lt "${m}" ]; then echo "unknown ${top:-? ?} ${n} ${m}"
    else echo "ok ${top} ${n} ${m}"; fi
}
# pool_gate <k> <step> — rc 0 go (ok, or still unknown at the deadline), 1 still high at the deadline,
# 2 a signal came (the walk stops at once).
pool_gate() {
    local k="$1" st="$2" deadline v q node r m
    if [ "${MAXQ}" = 0 ]; then echo "ARMS_POOL arm=${CUR_NAME} step=${st} verdict=off $(utc)"; return 0; fi
    deadline=$(( $(now) + POOL_WAIT ))
    while :; do
        [ -z "${SIG_NAME}" ] || return 2
        read -r v q node r m <<< "$(pool_read)"
        echo "ARMS_POOL arm=${CUR_NAME} step=${st} verdict=${v} queued_max=${q} (${node}) read=${r}/${m} limit=${MAXQ} $(utc)"
        [ "${v}" != ok ] || return 0
        if [ "$(now)" -ge "${deadline}" ]; then
            [ "${v}" = high ] && return 1
            echo "  the pools could not be read until the deadline: going on (the blast records POOL_AT_START)"
            return 0
        fi
        nap "${POOL_POLL}"
    done
}

# epoch_wait <k> <step> <type> — wait so that the next epoch boundary falls RUN_ARMS_EPOCH_OFFSET_SECS
# (default half the mixed phase) after the blast's planned mixed start. The blast's start_at is its
# launch + max(BENCH_START_DELAY_SECS 300, 240) (start_delay_secs, a load blast) and its mixed phase
# begins BENCH_PREAMBLE_SECS (90) + warmup later. The boundary comes from recovery-schedule.py over the
# run's RPC tunnel (the registry's epoch start + duration, 1200 s). rc 1: unreadable, 2: too far off.
epoch_wait() {
    local st="$2" t="$3" wu mix off delay pre lead out b at
    wu="$(type_field "${t}" BENCH_WARMUP_SECS)"; mix="$(type_field "${t}" BENCH_DURATION_SECS)"
    off="$(num_or "${EPOCH_OFFSET}" $((mix / 2)))"
    delay="$(num_or "${BENCH_START_DELAY_SECS:-}" 300)"; [ "${delay}" -ge 240 ] || delay=240
    pre="$(num_or "${BENCH_PREAMBLE_SECS:-}" 90)"
    lead=$(( off + wu + pre + delay ))
    out="$(bounded 60 python3 "${SCHED}" --rpc-url "${RPC}" --earliest-kill $(( $(now) + 30 + lead - 1 )) \
        --before-close 1 --downtime 2 2>&1)" || { echo "  epoch read failed: ${out}"; return 1; }
    b="$(printf '%s\n' "${out}" | grep '^{' | tail -n 1 | jq -r '.boundary_unix // empty' 2>/dev/null)" || b=""
    case "${b}" in ''|*[!0-9]*) echo "  epoch read gave no boundary_unix: ${out}"; return 1 ;; esac
    at=$(( b - lead ))
    echo "ARMS_EPOCH arm=${CUR_NAME} step=${st} boundary=$(iso "${b}") launch_at=$(iso "${at}") offset=${off} lead=${lead}"
    [ $(( at - $(now) )) -le "${EPOCH_WAIT_MAX}" ] || return 2
    sleep_until "${at}"
}

# --- the steps -------------------------------------------------------------------------------------
pa() { call "$1" "$2" env "${PA}" --from-config "${@:3}"; }

do_idle() { # <k> <step>
    local k="$1" st="$2" rc=0 cut=""
    pa "mark-idle-${st}" "${TMP}/mark" --mark "idle-${st}" || rc=$?
    if [ "${rc}" != 0 ]; then step_line "${st}" I "${rc}"; stop "${k}" "${st}" "mark-rc${rc}" "${st}"; fi
    nap "${IDLE_SECS}"
    # A signal cuts the idle window short. Its mark is still ended (a record write, no node), and a
    # resume measures the window again.
    [ -z "${SIG_NAME}" ] || cut=1
    pa "end-mark-idle-${st}" "${TMP}/mark" --end-mark "idle-${st}" || rc=$?
    if [ "${rc}" = 0 ] && [ -n "${cut}" ]; then step_line "${st}" I "${SIG_RC}"; sig_point "${k}" "${st}" "${st}"; fi
    step_line "${st}" I "${rc}"
    [ "${rc}" = 0 ] || stop "${k}" "${st}" "end-mark-rc${rc}" "$((st + 1))"
}

do_blast() { # <k> <step> <type[@epoch]>
    local k="$1" st="$2" t="${3%@epoch}" epoch=0 attempt=1 idx frc rrc reason before stalls
    [ "${t}" = "$3" ] || epoch=1
    while [ "${attempt}" -le 2 ]; do
        idx="$(next_index)"; LAST_INDEX="${idx}"
        frc=0 rrc=-
        # shellcheck disable=SC2046  # type_env prints NAME=value words without spaces
        call "blast-fund-${idx}" "${TMP}/fund" env $(type_env "${t}" "${idx}") "${BLAST}" fund --yes --run "${RUN}" || frc=$?
        if [ "${frc}" = 0 ]; then
            case "${SATURATED}" in *" ${t} "*)
                reason=0; pool_gate "${k}" "${st}" || reason=$?
                if [ "${reason}" = 1 ]; then
                    echo "ARMS_BLAST arm=${CUR_NAME} step=${st} kind=${t} index=${idx} attempt=${attempt} fund_rc=0 run_rc=- $(utc)"
                    step_line "${st}" "${t}" 1; stop "${k}" "${st}" pool-queued "${st}"
                fi ;;
            esac
            if [ "${epoch}" = 1 ] && [ -z "${SIG_NAME}" ]; then
                reason=0; epoch_wait "${k}" "${st}" "${t}" || reason=$?
                if [ "${reason}" != 0 ]; then
                    step_line "${st}" "${t}" 1
                    if [ "${reason}" = 1 ]; then stop "${k}" "${st}" epoch-unreadable "${st}"; fi
                    stop "${k}" "${st}" epoch-wait-too-long "${st}"
                fi
            fi
            if [ -n "${SIG_NAME}" ]; then
                echo "ARMS_BLAST arm=${CUR_NAME} step=${st} kind=$3 index=${idx} attempt=${attempt} fund_rc=0 run_rc=- $(utc)"
                step_line "${st}" "${t}" "${SIG_RC}"; sig_point "${k}" "${st}" "${st}"
            fi
            before="$(mjq '(.commit_stalls // []) | length' || true)"; before="$(num_or "${before}" 0)"
            rrc=0
            # shellcheck disable=SC2046
            call "blast-run-${idx}" "${TMP}/run" env $(type_env "${t}" "${idx}") "${BLAST}" run --yes --run "${RUN}" || rrc=$?
        fi
        echo "ARMS_BLAST arm=${CUR_NAME} step=${st} kind=$3 index=${idx} attempt=${attempt} fund_rc=${frc} run_rc=${rrc} $(utc)"
        if [ "${frc}" = 0 ] && [ "${rrc}" = 0 ]; then
            BLASTS=$((BLASTS + 1))
            step_line "${st}" "${t}" 0
            stalls="$(mjq --argjson f "${before}" --argjson s "${STALL_SECS}" \
                '(.commit_stalls // [])[$f:][] | select((.secs // 0) > $s) | "\(.start) \(.secs)s"' || true)"
            [ -z "${stalls}" ] || { echo "  commit stall(s) above ${STALL_SECS} s: ${stalls}"; stop "${k}" "${st}" commit-stall "$((st + 1))"; }
            return 0
        fi
        reason=""
        [ "${rrc}" = - ] || reason="$(mjq '.abort.reason // empty' || true)"
        case "${HEALTH_ABORTS}" in *" ${reason} "*)
            step_line "${st}" "${t}" "${rrc}"
            stop "${k}" "${st}" "blast-abort-${reason}" "${st}" ;;
        esac
        # After a signal a failed blast is not tried again.
        if [ -n "${SIG_NAME}" ]; then
            step_line "${st}" "${t}" "$([ "${frc}" = 0 ] && echo "${rrc}" || echo "${frc}")"; sig_point "${k}" "${st}" "${st}"
        fi
        if [ "${attempt}" = 1 ]; then
            echo "ARMS_RETRY arm=${CUR_NAME} step=${st} kind=${t} index=$(next_index) reason=$([ "${frc}" = 0 ] && echo "run-rc${rrc}${reason:+-${reason}}" || echo "fund-rc${frc}")"
        fi
        attempt=$((attempt + 1))
    done
    step_line "${st}" "${t}" "$([ "${frc}" = 0 ] && echo "${rrc}" || echo "${frc}")"
    stop "${k}" "${st}" blast-failed-twice "${st}"
}

do_apply() { # <k>
    local k="$1" rc=0 out="${TMP}/apply" ready t wait
    pa "apply-${CUR_NAME}" "${out}" --arm-file "${A_FILE[$k]}" --arm "${CUR_NAME}" || rc=$?
    step_line 0 apply "${rc}"
    if [ "$(grep -cE '^[[:space:]]*PA_GUARD_DEFER ' "${out}" || true)" -ge 2 ]; then stop "${k}" 0 guard-deferred-twice 1; fi
    if grep -qE '^[[:space:]]*(PA_FAIL|PARAMS_FAIL) ' "${out}"; then
        stop "${k}" 0 "node-failed-$(grep -hE '^[[:space:]]*(PA_FAIL|PARAMS_FAIL) ' "${out}" | head -n 1 | awk '{print $2}')" 1
    fi
    [ "${rc}" = 0 ] || stop "${k}" 0 "apply-rc${rc}" 1
    ready="$(grep -E "^ARM_READY ${CUR_NAME} " "${out}" | tail -n 1 | tr ' ' '\n' | sed -n 's/^ready=//p' || true)"
    [ -n "${ready}" ] || stop "${k}" 0 no-arm-ready 1
    t="$(jq -rn --arg t "${ready}" '$t | fromdateiso8601' 2>/dev/null)" || t=""
    case "${t}" in ''|*[!0-9]*) stop "${k}" 0 "bad-ready-${ready}" 1 ;; esac
    wait=$(( t - $(now) )); [ "${wait}" -ge 0 ] || wait=0
    echo "ARMS_READY arm=${CUR_NAME} ready=${ready} wait=${wait}"
    [ "${wait}" -le "${READY_MAX}" ] || stop "${k}" 0 ready-too-far 1
    sleep_until "${t}"
    sig_point "${k}" 0 "${first}"
}

# --- the dry run: the whole walk, nothing called ------------------------------------------------------
dry_walk() {
    local k st s t idx first nb=0 ns=0
    echo "DRY RUN: run-arms walks ${PLAN} on ${RUN}; nothing is called"
    echo "  inherited environment:"
    env | grep -E '^(BENCH|RUN_ARMS|PARAMS_APPLY|LAUNCH)_' | sort | sed 's/^/    /' || true
    echo "  pool gate: queued < ${MAXQ} on every node (0 = off), polled every ${POOL_POLL} s for up to ${POOL_WAIT} s at ${PROM}"
    echo "  health after each step: $([ "${HEALTH_SECS}" = 0 ] && echo off || echo "${BLAST} status (bounded ${HEALTH_SECS} s): stop on root disk > ${MAX_DISK} % or fatal_db > 0")"
    for k in $(seq "${K0}" "${K1}"); do
        CUR_NAME="$(pick_name "${A_NAME[$k]}")"; USED_NAMES="${USED_NAMES}${CUR_NAME} "
        echo "arm ${k} ${CUR_NAME} (${A_FILE[$k]}): ${A_STEPS[$k]}"
        echo "  step 0  ${PA} --from-config --arm-file ${A_FILE[$k]} --arm ${CUR_NAME}; wait until its ARM_READY ready= (at most ${READY_MAX} s); health"
        first=1; [ "${k}" != "${K0}" ] || first="${STEP0}"
        st=0
        for s in ${A_STEPS[$k]}; do
            st=$((st + 1)); [ "${st}" -ge "${first}" ] || { echo "  step ${st}  ${s}: skipped (--from-step ${first})"; continue; }
            t="${s%@epoch}"; ns=$((ns + 1))
            if [ "${t}" = I ]; then
                echo "  step ${st}  I: ${PA} --from-config --mark idle-${st}; sleep ${IDLE_SECS}; ${PA} --from-config --end-mark idle-${st}; health"
                continue
            fi
            idx="$(next_index)"; LAST_INDEX="${idx}"; nb=$((nb + 1))
            echo "  step ${st}  ${s}: env $(type_env "${t}" "${idx}") ${BLAST} fund --yes --run ${RUN}"
            case "${SATURATED}" in *" ${t} "*) echo "           pool gate (above)" ;; esac
            [ "${t}" = "${s}" ] || echo "           epoch: python3 ${SCHED} --rpc-url ${RPC} ...; launch so the boundary falls $(num_or "${EPOCH_OFFSET}" $(( $(type_field "${t}" BENCH_DURATION_SECS) / 2 ))) s into the mixed phase"
            echo "           env $(type_env "${t}" "${idx}") ${BLAST} run --yes --run ${RUN}; on failure once more under the next index; health"
        done
        echo "  close   ${PA} --from-config --close-arm ${CUR_NAME}"
    done
    echo "DRY RUN END: $((K1 - K0 + 1)) arm(s), ${ns} step(s), ${nb} blast(s)"
}

if [ "${DRY}" = 1 ]; then dry_walk; exit 0; fi
start_walk_log
echo "ARMS_START plan=${PLAN} run=${RUN} arms=${K0}..${K1} from_step=${STEP0} $(utc)"
echo ">>> run-arms: output copied to ${WALK_LOG}"
trap 'on_signal TERM 143' TERM
trap 'on_signal INT 130' INT
trap 'on_signal HUP 129' HUP

# Every arm file of the walk passes the arm tool's own parser (no node) before anything changes.
for k in $(seq "${K0}" "${K1}"); do
    sig_point "${K0}" 0 "${STEP0}"
    rc=0; "${PA}" --arm-file "${A_FILE[$k]}" --print-state > "${TMP}/state" 2>&1 || rc=$?
    if [ "${rc}" != 0 ]; then cat "${TMP}/state"; CUR_NAME="${A_NAME[$k]}"; stop "${K0}" 0 "arm-file-refused-${A_NAME[$k]}" "${STEP0}"; fi
done

[ "${DRY}" = 0 ] || exit 0
for k in $(seq "${K0}" "${K1}"); do
    first=1; [ "${k}" != "${K0}" ] || first="${STEP0}"
    CUR_NAME="" CUR_STEP=0
    sig_point "${k}" 0 "${first}"
    CUR_NAME="$(pick_name "${A_NAME[$k]}")"; USED_NAMES="${USED_NAMES}${CUR_NAME} "
    echo "ARMS_ARM k=${k} arm=${CUR_NAME} file=${A_FILE[$k]} steps=${A_STEPS[$k]// /,}"
    do_apply "${k}"
    health "${k}" 0
    st=0
    for s in ${A_STEPS[$k]}; do
        st=$((st + 1))
        [ "${st}" -ge "${first}" ] || continue
        CUR_STEP="${st}"
        sig_point "${k}" "${st}" "${st}"
        if [ "${s}" = I ]; then do_idle "${k}" "${st}"; else do_blast "${k}" "${st}" "${s}"; fi
        health "${k}" "${st}"
    done
    CUR_STEP=$((st + 1))
    sig_point "${k}" "$((st + 1))" "$((st + 1))"
    rc=0; pa "close-${CUR_NAME}" "${TMP}/close" --close-arm "${CUR_NAME}" || rc=$?
    step_line "$((st + 1))" close "${rc}"
    [ "${rc}" = 0 ] || owe_close "${k}" "$((st + 1))" "close-rc${rc}"
done
echo "ARMS_DONE arms=$((K1 - K0 + 1)) blasts=${BLASTS} $(utc)"
leave 0
