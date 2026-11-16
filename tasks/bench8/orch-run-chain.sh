#!/usr/bin/env bash
# orch-run-chain.sh — bench 8 (bench 7's chain plus the credential checks, the idle check's endpoint
# fallback, the floor count and the endpoint sampler as a segment), orchestrator only: deploy12, the idle-window checks and blast15 as one
# chain, so a deployed fleet never waits on a session for its blast (bench 6 run 3b's fleet idled 46
# minutes after deploy12 when the session that launched each segment by hand hit its limit).
#
# Usage: tasks/bench8/orch-run-chain.sh [--live] <env-file>
#
# Without --live it is a plan: it runs the preconditions, prints every step it would take and starts
# nothing. With --live, started detached by the orchestrator so it outlives the session:
#   setsid bash tasks/bench8/orch-run-chain.sh --live <env> > <log> 2>&1 < /dev/null &
# it runs, logging each step as one line "CHAIN <step> ... <UTC>":
#   1. preconditions (both modes): `launch.sh --dry-run <env> deploy12` and `... blast15` rc 0 (the
#      launcher's own parser and refusals; the run id is read from its dry-run output), the run id is
#      new (no benchmark/results/<run>/manifest.json), the harness tree is clean apart from
#      benchmark/launch/bench5/, no fleet driver runs; the credentials: `gcloud auth print-access-token`
#      succeeds (the token is never printed) and the login is at most CHAIN_LOGIN_MAX_AGE_SECS old (its age is
#      the file time of gcloud's credential store, which `gcloud auth login` rewrites and a token refresh does
#      not; an unknown age refuses unless CHAIN_LOGIN_AGE_UNKNOWN_OK=1): exit 4, "CHAIN stop reason=credentials ...";
#   2. `launch.sh <env> deploy12`, then waits for "== deploy12 rc=" in the log the launcher names
#      (CHAIN_DEPLOY_DEADLINE_SECS); not rc 0, or no "BENCH_DEPLOY_RESULT rc=0 last_step=12": exit 10;
#   2b. right after deploy12's rc 0, the endpoint sampler as a segment, every CHAIN_SAMPLER_INTERVAL_SECS on all
#      nodes until the chain ends (its stop file, written by every exit of the chain, and --parent-pid):
#      "CHAIN sampler started pid=<pid> interval=<s>s out=<dir> log=<log> stop_file=<file>"; a sampler that
#      ends early is said once ("CHAIN sampler ended rc=<n> log=<log>: the chain goes on without it");
#   3. the idle checks against the bench Prometheus forward, retried for CHAIN_IDLE_WAIT_SECS: every
#      node of the manifest scraped (up == 1), or, for a node Prometheus lacks (no up, no mode or a switch
#      series missing: the metrics agent's remote write loses a batch per scrape on some nodes), its own
#      endpoint read once through orch-endpoint-sampler.sh's path ("CHAIN idle-check endpoint-fallback
#      need=<nodes> answered=<nodes> failed=<nodes> dir=<dir> round=<n>"): a node that answered counts as up
#      and its mode and switches are taken from its endpoint, and "idle-checks ok" names it (up_fallback=); each validator in mode cvv_active and each observer in
#      mode observer (tn_node_mode); every switch of manifest .param_arms[0].switches on every node with
#      the manifest's value (tn_node_switch{name}: on/off as 1/0, counts as is, durations in ms) and no
#      other switch on; every name of CHAIN_REQUIRED_SWITCHES [quorum_exec_block_floor_outputs] must be a
#      count in the manifest (else exit 11) and is read back from every node like the others. The storage engine the manifest names and the deploy log's
#      "HOST_PROBE_SUMMARY ... uniform=yes" are notes. A check still failing at the end: exit 11, and
#      the fleet is left up and idle;
#   4. the credentials again (CHAIN_LOGIN_MAX_AGE_BLAST_SECS; exit 4 leaves the fleet up and idle), then
#      `launch.sh <env> blast15` the moment the checks pass, the fleet-health watch beside it
#      (orch-fleet-health.sh --until-file <blast15 log>), the wait for "== blast15 rc="
#      (CHAIN_BLAST_DEADLINE_SECS), and "CHAIN done rc=<n>".
# While a segment runs, a line of its log matching CHAIN_CRED_PAT (a failed token refresh: "Reauthentication
# failed", "cannot prompt during non-interactive execution", ...) is reported once as "CHAIN credentials
# refresh-failed seg=<seg> ..." with the fleet's state; a segment that then fails ends the chain with exit 4,
# not as a failed deploy or blast.
# It never tears down, exports or archives: those stay separate, deliberate calls.
# Exit: 0 done with blast15 rc 0 and its BENCH_DEPLOY_RESULT line (or the plan), 2 usage,
# 3 a precondition, 4 credentials, 10 deploy12, 11 an idle check, 12 blast15.
#
# Knobs (environment; the defaults are the real paths): CHAIN_ROOT [the repo], CHAIN_LAUNCH
# [benchmark/launch/launch.sh], CHAIN_PROM_URL [http://localhost:19090], CHAIN_WATCH
# [tasks/bench7/orch-fleet-health.sh], CHAIN_LOG_DIR [tasks/bench7/<run>], CHAIN_DEPLOY_DEADLINE_SECS
# [5400], CHAIN_BLAST_DEADLINE_SECS [9000], CHAIN_IDLE_WAIT_SECS [300], CHAIN_IDLE_RETRY_SECS [20],
# CHAIN_POLL_SECS [15], CHAIN_LOGIN_MAX_AGE_SECS [3600], CHAIN_LOGIN_MAX_AGE_BLAST_SECS [7200],
# CHAIN_LOGIN_AGE_UNKNOWN_OK [0], CHAIN_GCLOUD_CREDS_FILE [${CLOUDSDK_CONFIG:-~/.config/gcloud}/credentials.db],
# CHAIN_CRED_PAT [an ERE, below], CHAIN_WATCH_SECS [300], CHAIN_WATCH_DISK_MAX [80], CHAIN_WATCH_MAX_SECS
# [blast deadline + 900], CHAIN_WATCH_END_SECS [watch secs + 300], CHAIN_ENGINE_KEY [a jq path; by
# default the first manifest key named storage_engine, execution_engine, execution_store, db_engine or
# engine], CHAIN_DRIVER_PAT [launch.sh's FLEET_PAT], CHAIN_SAMPLER [tasks/bench8/orch-endpoint-sampler.sh],
# CHAIN_REQUIRED_SWITCHES [quorum_exec_block_floor_outputs; comma-separated, empty for none],
# CHAIN_SAMPLER_INTERVAL_SECS [60].
# The launcher refuses while a driver's file name is in a running command line (pgrep -f): nothing this
# script runs names one, and its own pgrep pattern starts each name with a bracket class.

set -uo pipefail

utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "CHAIN $* $(utc)"; }
usage() { echo "usage: tasks/bench8/orch-run-chain.sh [--live] <env-file>"; }

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="${CHAIN_ROOT:-$(cd "${SELF_DIR}/../.." && pwd)}"
LAUNCH="${CHAIN_LAUNCH:-${ROOT}/benchmark/launch/launch.sh}"
PROM="${CHAIN_PROM_URL:-http://localhost:19090}"
WATCH="${CHAIN_WATCH:-${SELF_DIR}/../bench7/orch-fleet-health.sh}"
SAMPLER="${CHAIN_SAMPLER:-${SELF_DIR}/orch-endpoint-sampler.sh}"
REQUIRED="${CHAIN_REQUIRED_SWITCHES-quorum_exec_block_floor_outputs}"
SAMPLER_INTERVAL="${CHAIN_SAMPLER_INTERVAL_SECS:-60}"
DEPLOY_DEADLINE="${CHAIN_DEPLOY_DEADLINE_SECS:-5400}"
BLAST_DEADLINE="${CHAIN_BLAST_DEADLINE_SECS:-9000}"
IDLE_WAIT="${CHAIN_IDLE_WAIT_SECS:-300}"
IDLE_RETRY="${CHAIN_IDLE_RETRY_SECS:-20}"
POLL="${CHAIN_POLL_SECS:-15}"
WATCH_SECS="${CHAIN_WATCH_SECS:-300}"
WATCH_DISK_MAX="${CHAIN_WATCH_DISK_MAX:-80}"
ENGINE_KEY="${CHAIN_ENGINE_KEY:-}"
LOGIN_MAX_AGE="${CHAIN_LOGIN_MAX_AGE_SECS:-3600}"
LOGIN_MAX_AGE_BLAST="${CHAIN_LOGIN_MAX_AGE_BLAST_SECS:-7200}"
LOGIN_UNKNOWN_OK="${CHAIN_LOGIN_AGE_UNKNOWN_OK:-0}"
CREDS_FILE="${CHAIN_GCLOUD_CREDS_FILE:-${CLOUDSDK_CONFIG:-${HOME}/.config/gcloud}/credentials.db}"
# gcloud's failed token refresh as a segment's log shows it (the lost run 7b's driver log: the first two).
CRED_PAT="${CHAIN_CRED_PAT:-Reauthentication failed|cannot prompt during non-interactive execution|Reauthentication required|There was a problem refreshing your current auth tokens|invalid_grant|RefreshError}"
# launch.sh's FLEET_PAT: the drivers that act on the bench fleet; two at once collide.
DRIVER_PAT="${CHAIN_DRIVER_PAT:-[b]enchmark-(deploy|blast|teardown|probe)\.sh|[r]un-arms\.sh|[p]arams-apply\.sh}"

LIVE=0 ENV_FILE=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        --live) LIVE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        -*) echo "orch-run-chain: unknown option $1" >&2; usage >&2; exit 2 ;;
        *) [ -z "${ENV_FILE}" ] || { echo "orch-run-chain: one env file only" >&2; exit 2; }
           ENV_FILE="$1"; shift ;;
    esac
done
[ -n "${ENV_FILE}" ] || { usage >&2; exit 2; }
for v in "${DEPLOY_DEADLINE}" "${BLAST_DEADLINE}" "${IDLE_WAIT}" "${IDLE_RETRY}" "${POLL}" "${WATCH_SECS}" "${WATCH_DISK_MAX}" "${LOGIN_MAX_AGE}" "${LOGIN_MAX_AGE_BLAST}" "${SAMPLER_INTERVAL}"; do
    case "${v}" in ''|*[!0-9]*) echo "orch-run-chain: the CHAIN_*_SECS knobs and CHAIN_WATCH_DISK_MAX are whole numbers ('${v}')" >&2; exit 2 ;; esac
done
WATCH_MAX="${CHAIN_WATCH_MAX_SECS:-$((BLAST_DEADLINE + 900))}"
WATCH_END="${CHAIN_WATCH_END_SECS:-$((WATCH_SECS + 300))}"
case "${WATCH_MAX}:${WATCH_END}" in *[!0-9:]*|:*|*:) echo "orch-run-chain: CHAIN_WATCH_MAX_SECS and CHAIN_WATCH_END_SECS are whole numbers" >&2; exit 2 ;; esac
case "${ENV_FILE}" in /*) ;; *) ENV_FILE="$(pwd)/${ENV_FILE}" ;; esac
MODE=dry
[ "${LIVE}" != 1 ] || MODE=live

# --- the end of the chain ---------------------------------------------------------------------------
# FLEET says what this script leaves behind when it stops: none (nothing launched), deploying, idle
# (deployed, no blast), blasting, ended (blast15 ended; the fleet stays up for the read and the export).
FINAL=0 FLEET=none
fleet_note() {
    case "${FLEET}" in
        deploying) say "FLEET MAY BE UP: nothing is torn down by this script; decide the teardown by hand (launch.sh <env> status)" ;;
        idle) say "FLEET IS UP AND IDLE: decide teardown or blast by hand" ;;
        blasting) say "FLEET IS UP: blast15 may still run (launch.sh <env> status); nothing is torn down by this script" ;;
        ended) say "FLEET IS UP: read and export while it is, then teardown-dry and teardown by hand" ;;
    esac
}
SAMPLER_STOP=""
sampler_stop() { [ -z "${SAMPLER_STOP}" ] || : > "${SAMPLER_STOP}" 2>/dev/null || :; }
finish() { FINAL=1; sampler_stop; exit "$1"; }
stop() { local code="$1"; shift; say "stop reason=$*"; fleet_note; finish "${code}"; }
on_exit() {
    local rc=$?
    [ "${FINAL}" = 1 ] && return 0
    sampler_stop
    say "stop reason=unexpected rc=${rc}"
    fleet_note
}
on_signal() { say "stop reason=signal $1"; fleet_note; finish "$2"; }
trap on_exit EXIT
trap 'on_signal TERM 143' TERM
trap 'on_signal INT 130' INT
trap '' HUP

cd "${ROOT}" || { echo "orch-run-chain: no repo at ${ROOT}" >&2; exit 2; }
say "start mode=${MODE} env=${ENV_FILE#"${ROOT}"/} pid=$$"

# --- 1. preconditions -------------------------------------------------------------------------------
RUN=""
precondition_dry_launch() {
    local seg="$1" out="" rc=0 run=""
    out="$(bash "${LAUNCH}" --dry-run "${ENV_FILE}" "${seg}" 2>&1 < /dev/null)" || rc=$?
    if [ "${rc}" != 0 ]; then
        printf '%s\n' "${out}" | sed 's/^/    /'
        stop 3 "precondition launch-dry seg=${seg} rc=${rc}"
    fi
    run="$(printf '%s\n' "${out}" | sed -n 's/^  env BENCH_RUN_ID=//p' | tail -n 1)" || run=""
    printf '%s\n' "${run}" | grep -Eq '^r[0-9]{8}-[0-9]{4}$' || stop 3 "precondition launch-dry seg=${seg} no BENCH_RUN_ID in the dry-run output"
    [ -z "${RUN}" ] || [ "${RUN}" = "${run}" ] || stop 3 "precondition launch-dry seg=${seg} run=${run} differs from ${RUN}"
    RUN="${run}"
    say "precondition ok launch-dry seg=${seg} run=${RUN}"
}
preconditions() {
    local t dirty="" hits=""
    for t in jq curl git pgrep ps gcloud; do
        command -v "${t}" >/dev/null 2>&1 || stop 3 "precondition tools ${t} is not installed"
    done
    [ -f "${ENV_FILE}" ] && [ -r "${ENV_FILE}" ] || stop 3 "precondition env-file not a readable file: ${ENV_FILE}"
    [ -f "${LAUNCH}" ] || stop 3 "precondition launcher not a file: ${LAUNCH}"
    precondition_dry_launch deploy12
    precondition_dry_launch blast15
    [ ! -f "${ROOT}/benchmark/results/${RUN}/manifest.json" ] \
        || stop 3 "precondition run-id benchmark/results/${RUN}/manifest.json exists: the run id is not new"
    dirty="$(git -C "${ROOT}" status --porcelain -- benchmark/ ':(exclude)benchmark/launch/bench5' 2>&1)" \
        || stop 3 "precondition harness-tree git status failed: $(printf '%s' "${dirty}" | head -n 1)"
    [ -z "${dirty}" ] || stop 3 "precondition harness-tree dirty: $(printf '%s\n' "${dirty}" | head -n 5 | tr '\n' ';')"
    hits="$(pgrep -f -- "${DRIVER_PAT}" 2>/dev/null)" || hits=""
    [ -z "${hits}" ] || stop 3 "precondition driver-running pids=$(printf '%s' "${hits}" | tr '\n' ',')"
    credentials preconditions "${LOGIN_MAX_AGE}"
    say "preconditions ok run=${RUN}"
}

# login_age — "<secs> source=<store>-mtime", or "unknown source=<why>".
login_age() {
    local m=""
    [ -f "${CREDS_FILE}" ] || { printf 'unknown source=no-credential-store'; return 0; }
    m="$(stat -c %Y "${CREDS_FILE}" 2>/dev/null)" || m="$(stat -f %m "${CREDS_FILE}" 2>/dev/null)" || m=""
    case "${m}" in ''|*[!0-9]*) printf 'unknown source=stat-failed'; return 0 ;; esac
    printf '%s source=%s-mtime' "$(( $(date +%s) - m ))" "${CREDS_FILE##*/}"
}
# credentials <at> <max-age-secs> — the token call and the login's age; stop 4 on a failed token, a login
# older than <max-age-secs>, or an unknown age without CHAIN_LOGIN_AGE_UNKNOWN_OK=1.
credentials() {
    local at="$1" max="$2" err="" rc=0 age="" secs="" next="start the chain again"
    [ "${at}" = preconditions ] || next="launch blast15 by hand: bash ${LAUNCH} ${ENV_FILE} blast15"
    err="$(timeout 60 gcloud auth print-access-token 2>&1 >/dev/null < /dev/null)" || rc=$?
    age="$(login_age)" || age="unknown source=error"
    secs="${age%% *}"
    [ "${rc}" = 0 ] || stop 4 "credentials token-failed at=${at} rc=${rc} login_age=${age} ($(printf '%s\n' "${err}" | grep -v '^[[:space:]]*$' | head -n 1)): run \`gcloud auth login\`, then ${next}"
    if [ "${secs}" = unknown ]; then
        [ "${LOGIN_UNKNOWN_OK}" = 1 ] || stop 4 "credentials login-age-unknown at=${at} (${age}): run \`gcloud auth login\` (or set CHAIN_LOGIN_AGE_UNKNOWN_OK=1), then ${next}"
    elif [ "${secs}" -gt "${max}" ]; then
        stop 4 "credentials login-too-old at=${at} login_age=${secs}s max=${max}s (a run needs about 3 h, a login lasts just under 5 h): run \`gcloud auth login\`, then ${next}"
    fi
    say "credentials ok at=${at} token=ok login_age=${age} max=${max}s"
}
preconditions

MANIFEST="${ROOT}/benchmark/results/${RUN}/manifest.json"
LOG_DIR="${CHAIN_LOG_DIR:-${ROOT}/tasks/bench8/${RUN}}"

# --- the plan (no --live): print every step and start nothing ----------------------------------------
if [ "${LIVE}" != 1 ]; then
    say "plan step=1 launch: bash ${LAUNCH} ${ENV_FILE} deploy12"
    say "plan step=2 wait: ^== deploy12 (rc=|LEFT_RUNNING ) in the log launch.sh names, deadline=${DEPLOY_DEADLINE}s; then rc=0 and BENCH_DEPLOY_RESULT rc=0 last_step=12, else stop (exit 10)"
    say "plan step=3 idle-checks: ${PROM} for up to ${IDLE_WAIT}s (every ${IDLE_RETRY}s): up, modes, the switches of benchmark/results/${RUN}/manifest.json .param_arms[0].switches on every node; notes: engine, HOST_PROBE_SUMMARY uniform=yes; a failure stops (exit 11) with the fleet up and idle"
    say "plan step=2b sampler: right after deploy12 rc=0: bash ${SAMPLER} ${RUN} ${LOG_DIR#"${ROOT}"/}/endpoint-samples --interval ${SAMPLER_INTERVAL} --stop-file ${LOG_DIR#"${ROOT}"/}/endpoint-sampler.stop --parent-pid <chain pid>, until the chain ends; one that ends early is said once and the chain goes on"
    say "plan step=3 also: a node Prometheus lacks passes when its own endpoint (bash ${SAMPLER} ${RUN} <dir> --once --nodes <nodes>) shows its mode and switches; read back from every node: ${REQUIRED:-none}"
    say "plan step=4 launch: bash ${LAUNCH} ${ENV_FILE} blast15 (the moment the checks pass)"
    say "plan step=5 watch: bash ${WATCH} ${RUN} --watch ${WATCH_SECS} --disk-max ${WATCH_DISK_MAX} --max-secs ${WATCH_MAX} --until-file <blast15 log> > ${LOG_DIR#"${ROOT}"/}/fleet-health-blast15-<UTC>.log"
    say "plan step=6 wait: ^== blast15 (rc=|LEFT_RUNNING ), deadline=${BLAST_DEADLINE}s; then CHAIN done rc=<n> (exit 0 only with rc=0 and BENCH_DEPLOY_RESULT rc=0 last_step=15)"
    say "plan credentials: gcloud auth print-access-token again before blast15 (login age max ${LOGIN_MAX_AGE_BLAST}s); a segment log line matching CHAIN_CRED_PAT is reported as CHAIN credentials, and a segment that fails after one ends the chain with exit 4"
    say "plan nothing is torn down, exported or archived by this script"
    say "dry done: nothing was started (add --live to run the chain)"
    finish 0
fi

# --- segments ------------------------------------------------------------------------------------
SEG_PID="" SEG_LOG="" LAUNCH_RC=0 END_LINE="" SEG_RC=""
# launch_segment <seg> — the live launch; sets SEG_PID and SEG_LOG (absolute). Non-zero when the
# launcher refused or printed no LAUNCHED line (LAUNCH_RC holds its rc).
launch_segment() {
    local seg="$1" out="" rc=0 line=""
    SEG_PID="" SEG_LOG="" LAUNCH_RC=0
    say "${seg} launch"
    [ "${LIVE}" = "1" ] || return 1
    out="$(bash "${LAUNCH}" "${ENV_FILE}" "${seg}" 2>&1 < /dev/null)" || rc=$?
    printf '%s\n' "${out}" | sed 's/^/    /'
    line="$(printf '%s\n' "${out}" | grep "^LAUNCHED segment=${seg} " | tail -n 1)" || line=""
    LAUNCH_RC="${rc}"
    [ "${rc}" = 0 ] && [ -n "${line}" ] || { [ "${rc}" != 0 ] || LAUNCH_RC=1; return 1; }
    SEG_PID="$(printf '%s\n' "${line}" | tr ' ' '\n' | sed -n 's/^pid=//p')"
    SEG_LOG="$(printf '%s\n' "${line}" | tr ' ' '\n' | sed -n 's/^log=//p')"
    case "${SEG_LOG}" in /*) ;; *) SEG_LOG="${ROOT}/${SEG_LOG}" ;; esac
    say "${seg} launched pid=${SEG_PID} log=${SEG_LOG#"${ROOT}"/}"
}

# wrapper_alive <seg> — the segment's wrapper still runs; pid-reuse safe: the process's command line
# must carry the marker that the log's start line names (bench6-launch:<run>:<seg> today).
wrapper_alive() {
    local seg="$1" marker="" cmd=""
    case "${SEG_PID}" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "${SEG_PID}" 2>/dev/null || return 1
    marker="$(sed -n "1s/^== ${seg} start [^ ]* \\([^ ]*\\) pid=.*/\\1/p" "${SEG_LOG}" 2>/dev/null)" || marker=""
    [ -n "${marker}" ] || return 0
    cmd="$(ps -o args= -p "${SEG_PID}" 2>/dev/null)" || cmd=""
    case "${cmd}" in *"${marker}"*) return 0 ;; esac
    return 1
}

WATCH_PID="" WATCH_LOG=""
# watch_poll — note a watch that has ended (an alarm ends it early); the chain never stops a segment.
watch_poll() {
    local rc=0
    [ -n "${WATCH_PID}" ] || return 0
    kill -0 "${WATCH_PID}" 2>/dev/null && return 0
    wait "${WATCH_PID}" 2>/dev/null || rc=$?
    say "watch rc=${rc} log=${WATCH_LOG#"${ROOT}"/}"
    WATCH_PID=""
}

# cred_scan <seg> — the first line of the segment's log matching CRED_PAT, reported once with the fleet's state.
CRED_SEEN=""
cred_scan() {
    local seg="$1" l="" state=""
    [ -z "${CRED_SEEN}" ] || return 0
    l="$(grep -a -E -m 1 -- "${CRED_PAT}" "${SEG_LOG}" 2>/dev/null | head -n 1)" || l=""
    [ -n "${l}" ] || return 0
    CRED_SEEN="${seg}"
    case "${FLEET}" in
        deploying) state="the fleet MAY BE UP (deploy12 has not ended): run \`gcloud auth login\`, then read \`launch.sh <env> status\` before anything else" ;;
        *) state="the fleet is UP: run \`gcloud auth login\`, then read \`launch.sh <env> status\` (${seg} may still run; nothing is torn down)" ;;
    esac
    say "credentials refresh-failed seg=${seg} line=\"$(printf '%s' "${l}" | tr -d '\r' | cut -c1-160)\": ${state}"
}
# seg_stop <code> <reason> — a failed segment; exit 4 when its log showed a failed credential refresh.
seg_stop() {
    local code="$1"; shift
    [ -z "${CRED_SEEN}" ] || stop 4 "credentials seg=${CRED_SEEN} $* (its log shows a failed credential refresh)"
    stop "${code}" "$@"
}

SAMPLER_PID="" SAMPLER_LOG=""
# start_sampler — the endpoint sampler, all nodes, until the chain ends; never stops the chain.
start_sampler() {
    local out="${LOG_DIR}/endpoint-samples"
    mkdir -p "${LOG_DIR}" || { say "sampler not-started: cannot create ${LOG_DIR#"${ROOT}"/} (the chain goes on without it)"; return 0; }
    SAMPLER_STOP="${LOG_DIR}/endpoint-sampler.stop"
    SAMPLER_LOG="${LOG_DIR}/endpoint-sampler-$(date -u +%Y%m%dT%H%M%SZ).log"
    SAMPLER_ROOT="${ROOT}" bash "${SAMPLER}" "${RUN}" "${out}" --interval "${SAMPLER_INTERVAL}" --stop-file "${SAMPLER_STOP}" \
        --parent-pid "$$" --max-secs "$((IDLE_WAIT + BLAST_DEADLINE + WATCH_END + 900))" > "${SAMPLER_LOG}" 2>&1 < /dev/null &
    SAMPLER_PID=$!
    say "sampler started pid=${SAMPLER_PID} interval=${SAMPLER_INTERVAL}s out=${out#"${ROOT}"/} log=${SAMPLER_LOG#"${ROOT}"/} stop_file=${SAMPLER_STOP#"${ROOT}"/}"
}
# sampler_poll — a sampler that has ended is said once; the chain goes on.
sampler_poll() {
    local rc=0
    [ -n "${SAMPLER_PID}" ] || return 0
    kill -0 "${SAMPLER_PID}" 2>/dev/null && return 0
    wait "${SAMPLER_PID}" 2>/dev/null || rc=$?
    say "sampler ended rc=${rc} log=${SAMPLER_LOG#"${ROOT}"/}: the chain goes on without it"
    SAMPLER_PID=""
}

# wait_segment <seg> <deadline-secs> — 0 when the log has its end line (END_LINE, SEG_RC), 1 at the
# deadline, 2 when the wrapper is gone without one (a SIGKILL of the wrapper).
wait_segment() {
    local seg="$1" limit="$2" t0 end="" gone=0
    t0="$(date +%s)"
    END_LINE="" SEG_RC=""
    while :; do
        cred_scan "${seg}"
        end="$(grep -E "^== ${seg} (rc=|LEFT_RUNNING )" "${SEG_LOG}" 2>/dev/null | tail -n 1)" || end=""
        if [ -n "${end}" ]; then
            cred_scan "${seg}"
            END_LINE="${end}"
            SEG_RC="$(printf '%s\n' "${end}" | sed -n "s/^== ${seg} rc=\\([0-9]*\\).*/\\1/p")"
            [ -n "${SEG_RC}" ] || SEG_RC=125
            return 0
        fi
        if wrapper_alive "${seg}"; then gone=0; else gone=$((gone + 1)); fi
        [ "${gone}" -lt 2 ] || return 2
        [ $(( $(date +%s) - t0 )) -lt "${limit}" ] || return 1
        watch_poll
        sampler_poll
        sleep "${POLL}"
    done
}

# --- 2. deploy12 -----------------------------------------------------------------------------------
FLEET=deploying
launch_segment deploy12 || { FLEET=none; stop 10 "deploy launch-refused rc=${LAUNCH_RC}"; }
DEPLOY_LOG="${SEG_LOG}"
wait_segment deploy12 "${DEPLOY_DEADLINE}"
case $? in
    1) seg_stop 10 "deploy deadline=${DEPLOY_DEADLINE}s no '== deploy12 rc=' line in ${SEG_LOG#"${ROOT}"/} (the segment may still run)" ;;
    2) seg_stop 10 "deploy died: wrapper pid=${SEG_PID} gone without an rc line in ${SEG_LOG#"${ROOT}"/}" ;;
esac
if grep -Eq '^BENCH_DEPLOY_RESULT rc=0 last_step=12( |$)' "${DEPLOY_LOG}"; then res=ok; else res=missing; fi
say "deploy12 rc=${SEG_RC} result=${res}"
[ "${SEG_RC}" = 0 ] || seg_stop 10 "deploy rc=${SEG_RC} (${END_LINE})"
[ "${res}" = ok ] || seg_stop 10 "deploy result-missing: no 'BENCH_DEPLOY_RESULT rc=0 last_step=12' in ${DEPLOY_LOG#"${ROOT}"/}"
FLEET=idle
start_sampler
# The launcher refuses a segment while a wrapper of the run is alive: let this one finish its exit.
n=0
while wrapper_alive deploy12 && [ "${n}" -lt 30 ]; do sleep 1; n=$((n + 1)); done

# --- 3. the idle checks -----------------------------------------------------------------------------
[ -f "${MANIFEST}" ] || stop 11 "idle-check manifest benchmark/results/${RUN}/manifest.json is missing"
NET="$(jq -r '.prometheus.network_label // "bench"' "${MANIFEST}" 2>/dev/null)" || NET=""
[ -n "${NET}" ] || NET=bench
# The nodes of the manifest with their role: .instances[] when present, else the keys of .zones_used.
WANT="$(jq -c '
    if ((.instances // []) | length) > 0
    then [.instances[] | {name: .name, role: (.role // (if (.name | test("observer")) then "observer" else "validator" end))}]
    else [(.zones_used // {}) | keys[] | {name: ., role: (if test("observer") then "observer" else "validator" end)}]
    end' "${MANIFEST}" 2>/dev/null)" || WANT=""
[ -n "${WANT}" ] && [ "${WANT}" != "[]" ] || stop 11 "idle-check manifest lists no node (.instances, .zones_used)"
SWITCHES="$(jq -c '(.param_arms // [])[0].switches // {}' "${MANIFEST}" 2>/dev/null)" || SWITCHES=""
[ -n "${SWITCHES}" ] || stop 11 "idle-check manifest .param_arms[0].switches is unreadable"
REQ_NOTE=""
for k in $(printf '%s' "${REQUIRED}" | tr ',' ' '); do
    v="$(printf '%s' "${SWITCHES}" | jq -r --arg k "${k}" '.[$k] // empty | tostring' 2>/dev/null)" || v=""
    case "${v}" in ''|*[!0-9]*) stop 11 "idle-check manifest .param_arms[0].switches.${k}='${v:-absent}' is not a count (it is read back from every node)" ;; esac
    REQ_NOTE="${REQ_NOTE} ${k}=${v}"
done
IDLE_DIR="${LOG_DIR}/idle-checks"
mkdir -p "${IDLE_DIR}" || stop 11 "idle-check cannot create ${IDLE_DIR#"${ROOT}"/}"

# prom_query <promql> — the body of an instant query; non-zero when curl or the query fails.
prom_query() {
    local body=""
    body="$(curl -s --max-time 20 --data-urlencode "query=$1" "${PROM}/api/v1/query" 2>/dev/null)" || return 1
    printf '%s' "${body}" | jq -e '.status == "success"' >/dev/null 2>&1 || return 1
    printf '%s\n' "${body}"
}

# Each jq verdict prints one line: "ok <detail>" or "fail <detail>".
UP_JQ='
    [.data.result[] | .metric.node] as $up
    | [$want[].name | select(. as $n | any($up[]; . == $n) | not)] as $miss
    | (if ($miss | length) == 0 then "ok" else "fail" end)
      + " up=\(($want | length) - ($miss | length))/\($want | length) missing=\(if ($miss | length) == 0 then "-" else ($miss | join(",")) end)"
      + (if ($fb | length) == 0 then "" else " fallback=\($fb | join(","))" end)'
# The nodes Prometheus lacks: no up, no mode, or a switch series of the manifest missing.
NEED_JQ='
    ([$up[0].data.result[] | .metric.node]) as $u
    | ([$md[0].data.result[] | .metric.node]) as $m
    | ([$s[0].data.result[] | "\(.metric.node) \(.metric.name)"]) as $have
    | ($sw | keys) as $names
    | [$want[].name | . as $n
        | select((any($u[]; . == $n) | not) or (any($m[]; . == $n) | not)
                 or any($names[]; "\($n) \(.)" as $k | any($have[]; . == $k) | not))]
    | join(",")'
# A sampler round's newest file per node as the three answers: up 1, tn_node_mode (value 1), tn_node_switch.
EP_PY='
import glob, gzip, json, math, os, re, sys
lab = re.compile(r"(\w+)=\"((?:[^\"\\]|\\.)*)\"")
row = re.compile(r"^(tn_node_mode|tn_node_switch)\{([^}]*)\}\s+(\S+)")
newest = {}
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*-metrics-*.txt.gz"))):
    newest[os.path.basename(f).rsplit("-metrics-", 1)[0]] = f
res = {"up": [], "modes": [], "switches": []}
for node, f in sorted(newest.items()):
    try:
        with gzip.open(f, "rt", errors="replace") as fh:
            text = fh.read()
    except (OSError, EOFError):
        continue
    res["up"].append({"metric": {"node": node}, "value": [0, "1"]})
    for line in text.splitlines():
        m = row.match(line)
        if not m:
            continue
        labels = dict(lab.findall(m.group(2)))
        try:
            v = float(m.group(3))
        except ValueError:
            continue
        if math.isnan(v) or math.isinf(v):
            continue
        txt = str(int(v)) if v == int(v) else repr(v)
        if m.group(1) == "tn_node_mode" and v == 1 and "mode" in labels:
            res["modes"].append({"metric": {"node": node, "mode": labels["mode"]}, "value": [0, "1"]})
        elif m.group(1) == "tn_node_switch" and "name" in labels:
            res["switches"].append({"metric": {"node": node, "name": labels["name"]}, "value": [0, txt]})
print(json.dumps(res))
'
MODES_JQ='
    [.data.result[] | {node: .metric.node, mode: .metric.mode}] as $got
    | [$want[] | . as $w
        | (if $w.role == "observer" then "observer" else "cvv_active" end) as $em
        | [$got[] | select(.node == $w.name) | .mode] as $ms
        | select($ms != [$em])
        | "\($w.name):\(if ($ms | length) == 0 then "none" else ($ms | join("+")) end)"] as $bad
    | (if ($bad | length) == 0 then "ok" else "fail" end)
      + " cvv_active=\([$got[] | select(.mode == "cvv_active")] | length)"
      + " observer=\([$got[] | select(.mode == "observer")] | length)"
      + " want_cvv_active=\([$want[] | select(.role != "observer")] | length)"
      + " want_observer=\([$want[] | select(.role == "observer")] | length)"
      + " wrong=\(if ($bad | length) == 0 then "-" else ($bad | join(",")) end)"'
# A manifest value as the gauge shows it: true/false 1/0, a number as is, a duration in milliseconds
# ("0ms", "150ms", "1s 500ms"); null when it is none of these (reported, not compared).
SWITCH_JQ='
    def ms_per: {"ns": 0.000001, "us": 0.001, "µs": 0.001, "ms": 1, "s": 1000, "min": 60000, "m": 60000, "h": 3600000};
    def gauge_value:
        if type == "boolean" then (if . then 1 else 0 end)
        elif type == "number" then .
        elif type == "string" then
            (ascii_downcase | gsub("^\\s+|\\s+$"; "")) as $s
            | if $s == "true" then 1
              elif $s == "false" then 0
              elif ($s | test("^-?[0-9]+(\\.[0-9]+)?$")) then ($s | tonumber)
              elif ($s | test("^([0-9]+(\\.[0-9]+)?\\s*(ns|us|µs|ms|s|min|m|h)\\s*)+$")) then
                  [$s | scan("([0-9]+(?:\\.[0-9]+)?)\\s*(ns|us|µs|ms|s|min|m|h)") | (.[0] | tonumber) * ms_per[.[1]]] | add
              else null end
        else null end;
    ($sw | to_entries | map({name: .key, raw: (.value | tostring), want: (.value | gauge_value)})) as $exp
    | [.data.result[] | {node: .metric.node, name: .metric.name, v: (.value[1] | tonumber)}] as $got
    | [ $want[] as $w
        | $exp[] | select(.want != null) as $e
        | ([$got[] | select(.node == $w.name and .name == $e.name) | .v] | max) as $g
        | if $g == null then "missing:\($e.name)@\($w.name)"
          elif (($g - $e.want) * ($g - $e.want)) > 0.000000000001 then "wrong:\($e.name)@\($w.name)=\($g)(want:\($e.raw))"
          else empty end ] as $bad1
    | [ $got[] | . as $g
        | select(any($want[]; .name == $g.node))
        | select($g.v != 0)
        | select(any($exp[]; .name == $g.name) | not)
        | "unexpected-on:\($g.name)@\($g.node)=\($g.v)" ] as $bad2
    | ($bad1 + $bad2) as $bad
    | [$exp[] | select(.want == null) | "\(.name)=\(.raw)"] as $unver
    | (if ($bad | length) == 0 then "ok" else "fail" end)
      + " switches=\($exp | length) nodes=\($want | length) problems=\($bad | length)"
      + (if ($bad | length) == 0 then "" else " " + ($bad[:8] | join(" ")) + (if ($bad | length) > 8 then " ..." else "" end) end)
      + (if ($unver | length) == 0 then "" else " unverifiable=" + ($unver | join(",")) end)'

# prom_body <which> <promql> — the round's answer in ${IDLE_DIR}/<which>.json; no file when the query failed.
prom_body() {
    local body=""
    rm -f "${IDLE_DIR}/$1.json"
    body="$(prom_query "$2")" || return 0
    printf '%s\n' "${body}" > "${IDLE_DIR}/$1.json"
}
# endpoint_fallback — the nodes Prometheus lacks, read once through the sampler's path; a node that
# answered replaces its Prometheus series (up, modes, switches) with its endpoint's. Sets FB_OK, FB_LIST.
FB_OK="[]" FB_LIST=""
endpoint_fallback() {
    local need="" dir="" ep="" failed="" w="" rc=0
    FB_OK="[]" FB_LIST=""
    [ -s "${IDLE_DIR}/up.json" ] && [ -s "${IDLE_DIR}/modes.json" ] && [ -s "${IDLE_DIR}/switches.json" ] || return 0
    need="$(jq -n -r --argjson want "${WANT}" --argjson sw "${SWITCHES}" --slurpfile up "${IDLE_DIR}/up.json" \
        --slurpfile md "${IDLE_DIR}/modes.json" --slurpfile s "${IDLE_DIR}/switches.json" "${NEED_JQ}" 2>/dev/null)" || need=""
    [ -n "${need}" ] || return 0
    dir="${IDLE_DIR}/endpoint-round-${ROUND}"
    SAMPLER_ROOT="${ROOT}" bash "${SAMPLER}" "${RUN}" "${dir}" --once --nodes "${need}" > "${dir}.log" 2>&1 < /dev/null || rc=$?
    ep="$(python3 -c "${EP_PY}" "${dir}" 2>/dev/null)" || ep=""
    [ -n "${ep}" ] || ep='{"up": [], "modes": [], "switches": []}'
    FB_OK="$(printf '%s' "${ep}" | jq -c '[.up[].metric.node]')" || FB_OK="[]"
    for w in up modes switches; do
        jq -c --argjson ep "${ep}" --argjson fb "${FB_OK}" --arg k "${w}" \
            '.data.result = ([.data.result[] | select(.metric.node as $n | any($fb[]; . == $n) | not)] + $ep[$k])' \
            "${IDLE_DIR}/${w}.json" > "${IDLE_DIR}/${w}.merged" 2>/dev/null && mv "${IDLE_DIR}/${w}.merged" "${IDLE_DIR}/${w}.json"
    done
    FB_LIST="$(printf '%s' "${FB_OK}" | jq -r 'join(",")')" || FB_LIST=""
    failed="$(jq -n -r --arg need "${need}" --argjson fb "${FB_OK}" '[$need | split(",")[] | select(. as $n | any($fb[]; . == $n) | not)] | join(",")')" || failed="?"
    say "idle-check endpoint-fallback need=${need} answered=${FB_LIST:--} failed=${failed:--} sampler_rc=${rc} dir=${dir#"${ROOT}"/} round=${ROUND}"
}
# idle_check <which> <promql> <jq> — one check on the round's answer; logs its line; 0 when it passed.
FAILED_WHICH="" FAILED_DETAIL=""
idle_check() {
    local which="$1" query="$2" prog="$3" verdict=""
    if [ -s "${IDLE_DIR}/${which}.json" ]; then
        verdict="$(jq -r --argjson want "${WANT}" --argjson sw "${SWITCHES}" --argjson fb "${FB_OK}" "${prog}" "${IDLE_DIR}/${which}.json" 2>&1)" || verdict="fail jq: $(printf '%s' "${verdict}" | head -n 1)"
    else
        verdict="fail query-failed: ${query}"
    fi
    say "idle-check ${which} ${verdict} round=${ROUND}"
    case "${verdict}" in ok*) return 0 ;; esac
    FAILED_WHICH="${which}" FAILED_DETAIL="${verdict#fail }"
    return 1
}

# The storage engine the manifest names (a key another unit adds): a note, never a stop.
engine_note() {
    local v=""
    if [ -n "${ENGINE_KEY}" ]; then
        v="$(jq -r "(${ENGINE_KEY}) // empty | tostring" "${MANIFEST}" 2>/dev/null | head -n 1)" || v=""
        [ -z "${v}" ] || v="${v} key=${ENGINE_KEY}"
    else
        v="$(jq -r '[paths(scalars) as $p
                     | select(($p | last | tostring) | test("^(storage_engine|execution_engine|execution_store|db_engine|engine)$"))
                     | "\(getpath($p)) key=.\($p | map(tostring) | join("."))"] | first // empty' "${MANIFEST}" 2>/dev/null)" || v=""
    fi
    printf '%s' "${v:-unknown}"
}
host_probe_note() {
    local l=""
    l="$(grep -a 'HOST_PROBE_SUMMARY ' "${DEPLOY_LOG}" 2>/dev/null | tail -n 1)" || l=""
    case "${l}" in
        '') printf 'absent' ;;
        *' uniform=yes'*) printf 'uniform' ;;
        *) printf 'not-uniform' ;;
    esac
}

ROUND=0
t_idle="$(date +%s)"
while :; do
    ROUND=$((ROUND + 1))
    ok=1
    q_up="max by (node) (up{network=\"${NET}\"} == 1)"
    q_modes="max by (node, mode) (tn_node_mode{network=\"${NET}\"} == 1)"
    q_sw="max by (node, name) (tn_node_switch{network=\"${NET}\"})"
    prom_body up "${q_up}"
    prom_body modes "${q_modes}"
    prom_body switches "${q_sw}"
    endpoint_fallback
    idle_check up "${q_up}" "${UP_JQ}" || ok=0
    idle_check modes "${q_modes}" "${MODES_JQ}" || ok=0
    idle_check switches "${q_sw}" "${SWITCH_JQ}" || ok=0
    [ "${ok}" = 1 ] && break
    [ $(( $(date +%s) - t_idle )) -lt "${IDLE_WAIT}" ] || stop 11 "idle-check ${FAILED_WHICH} ${FAILED_DETAIL} after ${ROUND} rounds"
    sampler_poll
    sleep "${IDLE_RETRY}"
done
HP="$(host_probe_note)"
credentials blast15 "${LOGIN_MAX_AGE_BLAST}"
say "idle-checks ok round=${ROUND} engine=$(engine_note) host_probe=${HP} up_fallback=${FB_LIST:--}${REQ_NOTE}"

# --- 4. blast15 at once, the watch beside it ------------------------------------------------------
launch_segment blast15 || stop 12 "blast launch-refused rc=${LAUNCH_RC}"
FLEET=blasting
[ "${HP}" = uniform ] || say "note host-probe ${HP}: read HOST_PROBE_SUMMARY in ${DEPLOY_LOG#"${ROOT}"/}"
WATCH_LOG="${LOG_DIR}/fleet-health-blast15-$(date -u +%Y%m%dT%H%M%SZ).log"
bash "${WATCH}" "${RUN}" --watch "${WATCH_SECS}" --disk-max "${WATCH_DISK_MAX}" --max-secs "${WATCH_MAX}" \
    --until-file "${SEG_LOG}" > "${WATCH_LOG}" 2>&1 < /dev/null &
WATCH_PID=$!
say "watch started pid=${WATCH_PID} log=${WATCH_LOG#"${ROOT}"/}"

wait_segment blast15 "${BLAST_DEADLINE}"
case $? in
    1) seg_stop 12 "blast deadline=${BLAST_DEADLINE}s no '== blast15 rc=' line in ${SEG_LOG#"${ROOT}"/} (the segment may still run)" ;;
    2) seg_stop 12 "blast died: wrapper pid=${SEG_PID} gone without an rc line in ${SEG_LOG#"${ROOT}"/}" ;;
esac
if grep -Eq '^BENCH_DEPLOY_RESULT rc=0 last_step=15( |$)' "${SEG_LOG}"; then res=present; else res=missing; fi
say "blast15 rc=${SEG_RC} result=${res}"
FLEET=ended

# The watch ends at its next round after the rc line; give it that long, then leave it to --max-secs.
n=0
while [ -n "${WATCH_PID}" ] && kill -0 "${WATCH_PID}" 2>/dev/null && [ "${n}" -lt "${WATCH_END}" ]; do sleep 1; n=$((n + 1)); done
watch_poll
[ -z "${WATCH_PID}" ] || say "watch still-running pid=${WATCH_PID} (it ends by --max-secs ${WATCH_MAX}) log=${WATCH_LOG#"${ROOT}"/}"

sampler_poll
say "done rc=${SEG_RC}"
fleet_note
if [ "${SEG_RC}" = 0 ] && [ "${res}" = present ]; then finish 0; fi
[ -z "${CRED_SEEN}" ] || { say "stop reason=credentials seg=${CRED_SEEN} blast15 rc=${SEG_RC} result=${res} (its log shows a failed credential refresh)"; finish 4; }
finish 12
