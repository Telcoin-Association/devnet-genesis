#!/usr/bin/env bash
#
# launch.sh — start ONE segment of a bench run detached from this shell, and return at once.
#
# Usage: benchmark/launch/launch.sh [--dry-run] <env-file> <segment> [segment args...]
#        benchmark/launch/launch.sh <env-file> status
#
# Segments and the driver call each one starts (from the repo root; R = BENCH_RUN_ID of the env file):
#   probe         benchmark/benchmark-probe.sh all --bin <LAUNCH_PROBE_BIN> [--arms <LAUNCH_PROBE_ARMS>]
#                 [--disks <LAUNCH_PROBE_DISKS>]
#   deploy12      benchmark/benchmark-deploy.sh --yes --with-contracts --to 12
#   arms          benchmark/launch/run-arms.sh            (the run-1 arm walk, bench6-run1.plan)
#   blast15       benchmark/benchmark-deploy.sh --yes --from 13 --to 15
#   step15        benchmark/benchmark-deploy.sh --yes --from 15 --to 15
#   teardown-dry  benchmark/benchmark-teardown.sh --run R
#   teardown      benchmark/benchmark-teardown.sh --run R --yes
#   archive       benchmark/tools/archive-run.sh --run R
#   reindex       benchmark/benchmark-teardown.sh --run R --reindex
#   bundle        python3 benchmark/report/make_bundle.py --run R
#   arms-summary  python3 benchmark/tools/arms-summary.py --run-dir benchmark/results/R
# Segment args are appended to the driver call as given.
#
# The env file: plain KEY=value lines, # comments and blank lines. Keys are BENCH_*, RUN_ARMS_*,
# PARAMS_APPLY_* or LAUNCH_*; a value is bare (no spaces, no quotes) or wholly in "..." or '...', and
# never holds $, a backquote or a backslash. The file is parsed, never sourced. A value holding <...>
# is a placeholder the orchestrator fills at the gate, and a launch refuses it. Every BENCH_*,
# RUN_ARMS_*, PARAMS_APPLY_* and LAUNCH_* variable this shell inherits is dropped first, so the env
# file is the segment's whole configuration.
#
# Refusals (rc 1, nothing started): an env-file line that breaks the rules above, a placeholder, a
# run id that is not rYYYYMMDD-HHMM, a dirty harness tree (`git status --porcelain -- benchmark/`,
# leaving out the untracked bench-5 originals in benchmark/launch/bench5/), a segment of the same run
# still running (its pid file in tasks/bench6/<run>/ names a live wrapper), a driver the segment
# would collide with still running (pgrep -f; each pattern starts with a bracket class, so it cannot
# match its own text), and for the segments that call gcloud a token that `gcloud auth
# print-access-token` cannot print within LAUNCH_TOKEN_SECS (30).
#
# A live start: `nohup setsid bash launch.sh __segment ...` with stdin from /dev/null. The detached
# shell writes its own pid to tasks/bench6/<run>/<segment>-<UTC>.pid, logs to the .log beside it
# (neither is ever overwritten), runs the driver as its child and passes TERM on to it (logged as
# `== <segment> signal TERM ...`, then `== <segment> driver pid=<p> exit=<n> after TERM ...`; INT and
# HUP never reach it: it starts with both ignored). Once the driver has ended and nothing else of the
# segment's process group runs, it ends the log with
#   == <segment> rc=<n> <UTC>
# A process of the group that outlives the driver gets LAUNCH_LEFT_WAIT_SECS; still there, the log
# lists it and ends with `== <segment> LEFT_RUNNING exit=<n> pids=<p,...> <UTC>` instead (exit 125).
# A SIGKILL of the detached shell itself is the one case it cannot cover: `status` then reports the
# segment as died. launch.sh prints LAUNCHED with the pid and the log, and the line to wait for.
# --dry-run runs every check except the token, prints the environment and the command, and starts
# nothing. `status` lists the run's segments: pid, state (running, stopping after <what>, ended, left
# running, died) and the last line of each log.
#
# Knobs (the env file's value, else the launching shell's): LAUNCH_TOKEN_SECS [30], LAUNCH_PID_WAIT_SECS
# [10], LAUNCH_LEFT_WAIT_SECS [60]; from the env file only: LAUNCH_PROBE_BIN, LAUNCH_PROBE_ARMS,
# LAUNCH_PROBE_DISKS.
# Docs: benchmark/launch/README.md.

set -euo pipefail

LAUNCH_SELF="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/$(basename "${BASH_SOURCE[0]:-$0}")"
ROOT="$(cd "$(dirname "${LAUNCH_SELF}")/../.." && pwd)"
readonly SEGMENTS="probe deploy12 arms blast15 step15 teardown-dry teardown archive reindex bundle arms-summary"
readonly CLEARED_RE='^(BENCH|RUN_ARMS|PARAMS_APPLY|LAUNCH)_'
readonly RUN_RE='^r[0-9]{8}-[0-9]{4}$'
# Drivers that act on the bench fleet or its project; two of them at once collide.
readonly FLEET_PAT='[b]enchmark-(deploy|blast|teardown|probe)\.sh|[r]un-arms\.sh|[p]arams-apply\.sh'

utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# bounded <secs> <cmd...> — the command under a wall-clock limit (timeout, else a perl alarm).
bounded() {
    local s="$1"; shift
    if command -v timeout >/dev/null 2>&1; then timeout "${s}" "$@"; return; fi
    perl -e '$s = shift; alarm $s; exec @ARGV or exit 127' "${s}" "$@"
}

# ======================= the detached side (launch.sh __segment ...) =======================
# __segment <marker> <pidfile> <segment> <harness-sha> <left-wait-secs> -- <cmd...>: runs inside the
# new session, whose leader it is: its pid is the process group of everything the segment starts.
if [ "${1:-}" = __segment ]; then
    set +e
    marker="$2" pidf="$3" seg="$4" sha="$5" left_wait="$6"
    shift 7
    echo "$$" > "${pidf}"
    child="" sig_rc="" sig_name=""
    # Only TERM arrives: this shell starts with INT and HUP ignored (a background job under nohup), and
    # bash cannot trap a signal ignored at its start; the INT and HUP traps are kept for a shell that
    # was started otherwise.
    on_sig() {
        sig_rc="$2" sig_name="$1"
        [ -n "${child}" ] || return 0
        echo "== ${seg} signal $1 $(utc): passed to pid ${child}; the rc line follows once nothing of the segment runs"
        kill -"$1" "${child}" 2>/dev/null
    }
    trap 'on_sig TERM 143' TERM
    trap 'on_sig INT 130' INT
    trap 'on_sig HUP 129' HUP
    # left_running — LEFT: one "<pid> <command>" line per process of this segment's process group
    # other than this shell (and the ps that lists them, through <segment>-<UTC>.left beside the pid file).
    left_running() {
        local f="${pidf%.pid}.left" p pid pg cmd
        LEFT=""
        ps -A -o pid= -o pgid= -o args= > "${f}" 2>/dev/null &
        p=$!
        while kill -0 "${p}" 2>/dev/null; do wait "${p}"; done
        while read -r pid pg cmd; do
            [ "${pg}" = "$$" ] && [ "${pid}" != "$$" ] && [ "${pid}" != "${p}" ] || continue
            LEFT="${LEFT}${pid} ${cmd}"$'\n'
        done < "${f}"
        rm -f "${f}"
    }
    echo "== ${seg} start $(utc) ${marker} pid=$$ harness=${sha}"
    echo "== ${seg} command: $*"
    env | grep -E "${CLEARED_RE}" | sort
    "$@" </dev/null &
    child=$!
    rc=0
    while :; do
        rc=0; wait "${child}" || rc=$?
        kill -0 "${child}" 2>/dev/null || break
    done
    # A wait cut short by a trapped signal leaves the child's status with bash: ask for it once more.
    if [ "${rc}" -gt 128 ]; then r2=0; wait "${child}" 2>/dev/null || r2=$?; [ "${r2}" = 127 ] || rc="${r2}"; fi
    [ -z "${sig_name}" ] || echo "== ${seg} driver pid=${child} exit=${rc} after ${sig_name} $(utc)"
    child=""
    [ -n "${sig_rc}" ] && [ "${rc}" = 0 ] && rc="${sig_rc}"
    # The rc line claims an end, so it waits until nothing of the segment runs: a process the driver
    # left behind (a grandchild that outlived it) gets left_wait seconds, then the log names it and
    # the shell exits 125 without an rc line.
    left_running
    deadline=$(( $(date +%s) + left_wait )) said=""
    while [ -n "${LEFT}" ] && [ "$(date +%s)" -lt "${deadline}" ]; do
        sleep 1
        left_running
        if [ -n "${LEFT}" ] && [ -z "${said}" ]; then
            said=1
            echo "== ${seg} waiting up to ${left_wait} s for what is left of the segment:"
            printf '%s' "${LEFT}" | sed 's/^/     /'
        fi
    done
    if [ -n "${LEFT}" ]; then
        printf '%s' "${LEFT}" | sed 's/^/     /'
        echo "== ${seg} LEFT_RUNNING exit=${rc} pids=$(printf '%s' "${LEFT}" | awk '{ printf "%s%s", (NR > 1 ? "," : ""), $1 }') $(utc)"
        exit 125
    fi
    echo "== ${seg} rc=${rc} $(utc)"
    exit "${rc}"
fi

# ================================ the launcher side ========================================
usage() { sed -n '3,20p' "${LAUNCH_SELF}" | sed 's/^# \{0,1\}//'; }
refuse() { echo "launch: refused: $*" >&2; exit 1; }

DRY=0
case "${1:-}" in -h|--help) usage; exit 0 ;; --dry-run) DRY=1; shift ;; esac
[ $# -ge 2 ] || { usage >&2; exit 2; }
ENV_FILE="$1" SEG="$2"
shift 2
SEG_ARGS=("$@")
[ -f "${ENV_FILE}" ] && [ -r "${ENV_FILE}" ] || refuse "env file '${ENV_FILE}' is not a readable file"

# --- the env file --------------------------------------------------------------------------
ENV_KEYS=() ENV_VALS=() PLACEHOLDERS=""
KEY_RE='^[A-Z][A-Z0-9_]*$'
parse_env() {
    local f="$1" n=0 line key val q
    while IFS= read -r line || [ -n "${line}" ]; do
        n=$((n + 1))
        case "${line}" in *$'\r'*) refuse "${f}:${n}: carriage return" ;; esac
        line="${line#"${line%%[![:space:]]*}"}"
        line="${line%"${line##*[![:space:]]}"}"
        case "${line}" in ''|'#'*) continue ;; esac
        case "${line}" in *=*) ;; *) refuse "${f}:${n}: not KEY=value: ${line}" ;; esac
        key="${line%%=*}" val="${line#*=}"
        [[ "${key}" =~ ${KEY_RE} ]] || refuse "${f}:${n}: bad key '${key}'"
        [[ "${key}" =~ ${CLEARED_RE} ]] || refuse "${f}:${n}: ${key}: only BENCH_*, RUN_ARMS_*, PARAMS_APPLY_* and LAUNCH_* keys"
        case "${val}" in
            \"*) q='"' ;;
            \'*) q="'" ;;
            *) q="" ;;
        esac
        if [ -n "${q}" ]; then
            [ "${#val}" -ge 2 ] && [ "${val%"${q}"}" != "${val}" ] || refuse "${f}:${n}: ${key}: unterminated quote"
            val="${val#"${q}"}"; val="${val%"${q}"}"
            case "${val}" in *\"*|*\'*) refuse "${f}:${n}: ${key}: a quote inside the value" ;; esac
        else
            case "${val}" in *[[:space:]]*|*\"*|*\'*) refuse "${f}:${n}: ${key}: spaces or quotes need the whole value in quotes" ;; esac
        fi
        case "${val}" in *'$'*|*'`'*|*\\*) refuse "${f}:${n}: ${key}: \$, backquotes and backslashes are not allowed (the file is never sourced)" ;; esac
        local i
        for i in ${ENV_KEYS[@]+"${!ENV_KEYS[@]}"}; do
            [ "${ENV_KEYS[$i]}" != "${key}" ] || refuse "${f}:${n}: ${key} is set twice"
        done
        case "${val}" in *'<'*'>'*) PLACEHOLDERS="${PLACEHOLDERS} ${key}" ;; esac
        ENV_KEYS+=("${key}"); ENV_VALS+=("${val}")
    done < "${f}"
}
parse_env "${ENV_FILE}"
env_get() { local i; for i in ${ENV_KEYS[@]+"${!ENV_KEYS[@]}"}; do [ "${ENV_KEYS[$i]}" != "$1" ] || { printf '%s' "${ENV_VALS[$i]}"; return 0; }; done; return 1; }

RUN="$(env_get BENCH_RUN_ID)" || refuse "${ENV_FILE} sets no BENCH_RUN_ID"
case " ${PLACEHOLDERS} " in *" BENCH_RUN_ID "*) refuse "BENCH_RUN_ID is still a placeholder (${RUN}): fill it at the gate" ;; esac
[[ "${RUN}" =~ ${RUN_RE} ]] || refuse "BENCH_RUN_ID '${RUN}' is not rYYYYMMDD-HHMM"
RUN_DIR="${ROOT}/tasks/bench6/${RUN}"
MARK_PREFIX="bench6-launch:${RUN}:"
# launch.sh's own knobs: the env file's value, else the launching shell's, else the default.
TOKEN_SECS="$(env_get LAUNCH_TOKEN_SECS)" || TOKEN_SECS="${LAUNCH_TOKEN_SECS:-30}"
PID_WAIT_SECS="$(env_get LAUNCH_PID_WAIT_SECS)" || PID_WAIT_SECS="${LAUNCH_PID_WAIT_SECS:-10}"
case "${TOKEN_SECS}:${PID_WAIT_SECS}" in *[!0-9:]*|0*|*:0*|:*|*:) refuse "LAUNCH_TOKEN_SECS '${TOKEN_SECS}' and LAUNCH_PID_WAIT_SECS '${PID_WAIT_SECS}' must be positive integers" ;; esac
LEFT_WAIT_SECS="$(env_get LAUNCH_LEFT_WAIT_SECS)" || LEFT_WAIT_SECS="${LAUNCH_LEFT_WAIT_SECS:-60}"
case "${LEFT_WAIT_SECS}" in ''|*[!0-9]*) refuse "LAUNCH_LEFT_WAIT_SECS '${LEFT_WAIT_SECS}' must be a whole number of seconds" ;; esac

# --- liveness of a segment's wrapper ---------------------------------------------------------
# pid_alive <pidfile> — 0 when its pid runs AND is one of this run's wrappers (pid reuse safe).
pid_alive() {
    local p cmd
    p="$(cat "$1" 2>/dev/null || true)"
    case "${p}" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "${p}" 2>/dev/null || return 1
    cmd="$(ps -o command= -p "${p}" 2>/dev/null || true)"
    case "${cmd}" in *"${MARK_PREFIX}"*) return 0 ;; esac
    return 1
}

if [ "${SEG}" = status ]; then
    [ "${#SEG_ARGS[@]}" -eq 0 ] || refuse "status takes no arguments"
    echo "run ${RUN}: segments in ${RUN_DIR#"${ROOT}"/}"
    found=0
    for pf in "${RUN_DIR}"/*.pid; do
        [ -f "${pf}" ] || continue
        found=1
        name="$(basename "${pf}" .pid)" lf="${pf%.pid}.log"
        last="$(tail -n 1 "${lf}" 2>/dev/null || true)"
        if pid_alive "${pf}"; then
            # After a TERM: the walk's ARMS_STOPPING line names the driver call it waits for; any
            # other segment's wrapper line names the driver it passed the TERM to.
            state=running
            sl="$(grep '^ARMS_STOPPING ' "${lf}" 2>/dev/null | tail -n 1 || true)"
            if [ -n "${sl}" ]; then
                what="$(printf '%s\n' "${sl}" | tr ' ' '\n' | sed -n 's/^after=//p')"
                cp="$(printf '%s\n' "${sl}" | tr ' ' '\n' | sed -n 's/^pid=//p')"
                state=stopping
                [ "${what:-none}" = none ] || state="stopping after ${what}"
                case "${cp}" in ''|-) ;; *) state="${state} (pid ${cp})" ;; esac
            else
                sl="$(grep -E '^== [a-z0-9-]+ signal ' "${lf}" 2>/dev/null | tail -n 1 || true)"
                if [ -n "${sl}" ]; then cp="${sl##*passed to pid }"; state="stopping after the driver (pid ${cp%%;*})"; fi
            fi
        else case "${last}" in
            "== "*" rc="*) state=ended ;;
            "== "*" LEFT_RUNNING "*) state="left running ($(printf '%s\n' "${last}" | tr ' ' '\n' | sed -n 's/^pids=//p'))" ;;
            *) state="died (no rc line)" ;;
        esac; fi
        echo "SEGMENT ${name} pid=$(cat "${pf}" 2>/dev/null || echo '?') state=${state} last: ${last:-<empty log>}"
    done
    [ "${found}" = 1 ] || echo "  (no segment launched yet)"
    exit 0
fi

# --- the segment ------------------------------------------------------------------------------
case " ${SEGMENTS} " in *" ${SEG} "*) ;; *) echo "launch: unknown segment '${SEG}' (${SEGMENTS}, status)" >&2; exit 2 ;; esac
[ -z "${PLACEHOLDERS}" ] || refuse "placeholders not filled in ${ENV_FILE}:${PLACEHOLDERS}"

GCLOUD=1 PAT="${FLEET_PAT}" WAIT_TAG=""
case "${SEG}" in
    probe)
        bin="$(env_get LAUNCH_PROBE_BIN)" || refuse "the probe needs LAUNCH_PROBE_BIN in ${ENV_FILE}"
        [ -f "${ROOT}/${bin}" ] || [ -f "${bin}" ] || refuse "LAUNCH_PROBE_BIN '${bin}' is not a file (benchmark/tools/build-probe-bin.sh builds it)"
        CMD=(benchmark/benchmark-probe.sh all --bin "${bin}")
        arms="$(env_get LAUNCH_PROBE_ARMS)" || arms=""
        [ -z "${arms}" ] || CMD+=(--arms "${arms}")
        disks="$(env_get LAUNCH_PROBE_DISKS)" || disks=""
        [ -z "${disks}" ] || CMD+=(--disks "${disks}")
        WAIT_TAG="DOWN_OK | DOWN_INCOMPLETE" ;;
    deploy12) CMD=(benchmark/benchmark-deploy.sh --yes --with-contracts --to 12); WAIT_TAG="BENCH_DEPLOY_RESULT" ;;
    arms) CMD=(benchmark/launch/run-arms.sh); WAIT_TAG="ARMS_DONE | ARMS_STOPPED (then ARMS_RESUME)" ;;
    blast15) CMD=(benchmark/benchmark-deploy.sh --yes --from 13 --to 15); WAIT_TAG="BENCH_DEPLOY_RESULT" ;;
    step15) CMD=(benchmark/benchmark-deploy.sh --yes --from 15 --to 15); WAIT_TAG="BENCH_DEPLOY_RESULT" ;;
    teardown-dry) CMD=(benchmark/benchmark-teardown.sh --run "${RUN}"); WAIT_TAG="TEARDOWN_DONE ... dry_run=1" ;;
    teardown) CMD=(benchmark/benchmark-teardown.sh --run "${RUN}" --yes); WAIT_TAG="TEARDOWN_DONE" ;;
    archive) CMD=(benchmark/tools/archive-run.sh --run "${RUN}"); PAT='[a]rchive-run\.sh|[b]enchmark-teardown\.sh'
        WAIT_TAG="== archive-run run=${RUN} rc=" ;;
    reindex) CMD=(benchmark/benchmark-teardown.sh --run "${RUN}" --reindex); GCLOUD=0; PAT='[b]enchmark-teardown\.sh' ;;
    bundle) CMD=(python3 benchmark/report/make_bundle.py --run "${RUN}"); GCLOUD=0; PAT='[m]ake_bundle\.py' ;;
    arms-summary) CMD=(python3 benchmark/tools/arms-summary.py --run-dir "benchmark/results/${RUN}"); GCLOUD=0; PAT='[a]rms-summary\.py' ;;
esac
CMD+=(${SEG_ARGS[@]+"${SEG_ARGS[@]}"})

# --- refusals ------------------------------------------------------------------------------------
dirty="$(git -C "${ROOT}" status --porcelain -- benchmark/ ':(exclude)benchmark/launch/bench5' 2>&1)" \
    || refuse "cannot read the harness tree's state (git status in ${ROOT}): ${dirty}"
[ -z "${dirty}" ] || refuse "the harness tree is dirty (commit or move these first):"$'\n'"${dirty}"
SHA="$(git -C "${ROOT}" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)"

for pf in "${RUN_DIR}"/*.pid; do
    [ -f "${pf}" ] || continue
    if pid_alive "${pf}"; then refuse "segment $(basename "${pf}" .pid) of ${RUN} is still running (pid $(cat "${pf}")); see: $0 ${ENV_FILE} status"; fi
done
hits="$(pgrep -f -- "${PAT}" 2>/dev/null || true)"
[ -z "${hits}" ] || refuse "a driver this segment collides with is running (pgrep -f '${PAT}'): pid $(printf '%s' "${hits}" | tr '\n' ' ')"

if [ "${GCLOUD}" = 1 ] && [ "${DRY}" = 0 ]; then
    tsecs="${TOKEN_SECS}"
    bounded "${tsecs}" gcloud auth print-access-token >/dev/null 2>&1 \
        || refuse "gcloud auth print-access-token failed or took more than ${tsecs} s: run gcloud auth login (re-auth within 1 h of a long segment)"
fi

# --- the environment the segment gets --------------------------------------------------------------
for v in $(compgen -e); do if [[ "${v}" =~ ${CLEARED_RE} ]]; then unset "${v}"; fi; done
for i in "${!ENV_KEYS[@]}"; do export "${ENV_KEYS[$i]}=${ENV_VALS[$i]}"; done
case "${ENV_FILE}" in /*) LAUNCH_ENV_FILE="${ENV_FILE}" ;; *) LAUNCH_ENV_FILE="$(cd "$(dirname "${ENV_FILE}")" && pwd)/$(basename "${ENV_FILE}")" ;; esac
LAUNCH_ENV_FILE="${LAUNCH_ENV_FILE#"${ROOT}"/}"
export LAUNCH_ENV_FILE LAUNCH_SEGMENT="${SEG}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TAG_NOTE=""
[ -z "${WAIT_TAG}" ] || TAG_NOTE="  (the last tag of the driver before it: ${WAIT_TAG})"
LOG_REL="tasks/bench6/${RUN}/${SEG}-${STAMP}.log"
if [ "${DRY}" = 1 ]; then
    echo "DRY RUN: nothing is started; token: not checked in a dry run"
    echo "  cd ${ROOT}"
    env | grep -E "${CLEARED_RE}" | sort | sed 's/^/  env /'
    printf '  command:'; printf ' %q' "${CMD[@]}"; echo
    echo "  log ${LOG_REL} (pid beside it); wait for: == ${SEG} rc=${TAG_NOTE}"
    exit 0
fi

# --- the live start ---------------------------------------------------------------------------------
mkdir -p "${RUN_DIR}"
n=1 base="${RUN_DIR}/${SEG}-${STAMP}"
until ( set -C; : > "${base}.log" ) 2>/dev/null; do
    n=$((n + 1)); [ "${n}" -le 20 ] || refuse "no free log name for ${base}"
    base="${RUN_DIR}/${SEG}-${STAMP}-${n}"
done
LOG="${base}.log" PIDF="${base}.pid"
[ ! -e "${PIDF}" ] || refuse "${PIDF} exists already"
SETSID=(setsid)
command -v setsid >/dev/null 2>&1 || SETSID=(perl -MPOSIX -e 'POSIX::setsid(); exec @ARGV or exit 127')
cd "${ROOT}"
[ "${DRY}" = 0 ] || exit 0
nohup "${SETSID[@]}" bash "${LAUNCH_SELF}" __segment "${MARK_PREFIX}${SEG}" "${PIDF}" "${SEG}" "${SHA}" "${LEFT_WAIT_SECS}" -- "${CMD[@]}" \
    >> "${LOG}" 2>&1 < /dev/null &
waited=0 pid=""
while [ "${waited}" -lt "$(( PID_WAIT_SECS * 10 ))" ]; do
    pid="$(cat "${PIDF}" 2>/dev/null || true)"
    [ -z "${pid}" ] || break
    sleep 0.1; waited=$((waited + 1))
done
[ -n "${pid}" ] || { echo "launch: the segment wrote no pid file within ${PID_WAIT_SECS} s; read ${LOG}" >&2; exit 1; }
echo "LAUNCHED segment=${SEG} run=${RUN} pid=${pid} harness=${SHA} log=${LOG#"${ROOT}"/}"
echo "  wait for: ^== ${SEG} rc=  in ${LOG#"${ROOT}"/}${TAG_NOTE}"
echo "  status:   $0 ${ENV_FILE} status"
