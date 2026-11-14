#!/usr/bin/env bash
# orch-run-chain.sh — bench 7, orchestrator only: deploy12, the idle-window checks and blast15 as one
# chain, so a deployed fleet never waits on a session for its blast (bench 6 run 3b's fleet idled 46
# minutes after deploy12 when the session that launched each segment by hand hit its limit).
#
# Usage: tasks/bench7/orch-run-chain.sh [--live] <env-file>
#
# Without --live it is a plan: it runs the preconditions, prints every step it would take and starts
# nothing. With --live, started detached by the orchestrator so it outlives the session:
#   setsid bash tasks/bench7/orch-run-chain.sh --live <env> > <log> 2>&1 < /dev/null &
# it runs, logging each step as one line "CHAIN <step> ... <UTC>":
#   1. preconditions (both modes): `launch.sh --dry-run <env> deploy12` and `... blast15` rc 0 (the
#      launcher's own parser and refusals; the run id is read from its dry-run output), the run id is
#      new (no benchmark/results/<run>/manifest.json), the harness tree is clean apart from
#      benchmark/launch/bench5/, no fleet driver runs;
#   2. `launch.sh <env> deploy12`, then waits for "== deploy12 rc=" in the log the launcher names
#      (CHAIN_DEPLOY_DEADLINE_SECS); not rc 0, or no "BENCH_DEPLOY_RESULT rc=0 last_step=12": exit 10;
#   3. the idle checks against the bench Prometheus forward, retried for CHAIN_IDLE_WAIT_SECS: every
#      node of the manifest scraped (up == 1); each validator in mode cvv_active and each observer in
#      mode observer (tn_node_mode); every switch of manifest .param_arms[0].switches on every node with
#      the manifest's value (tn_node_switch{name}: on/off as 1/0, counts as is, durations in ms) and no
#      other switch on. The storage engine the manifest names and the deploy log's
#      "HOST_PROBE_SUMMARY ... uniform=yes" are notes. A check still failing at the end: exit 11, and
#      the fleet is left up and idle;
#   4. `launch.sh <env> blast15` the moment the checks pass, the fleet-health watch beside it
#      (orch-fleet-health.sh --until-file <blast15 log>), the wait for "== blast15 rc="
#      (CHAIN_BLAST_DEADLINE_SECS), and "CHAIN done rc=<n>".
# It never tears down, exports or archives: those stay separate, deliberate calls.
# Exit: 0 done with blast15 rc 0 and its BENCH_DEPLOY_RESULT line (or the plan), 2 usage,
# 3 a precondition, 10 deploy12, 11 an idle check, 12 blast15.
#
# Knobs (environment; the defaults are the real paths): CHAIN_ROOT [the repo], CHAIN_LAUNCH
# [benchmark/launch/launch.sh], CHAIN_PROM_URL [http://localhost:19090], CHAIN_WATCH
# [tasks/bench7/orch-fleet-health.sh], CHAIN_LOG_DIR [tasks/bench7/<run>], CHAIN_DEPLOY_DEADLINE_SECS
# [5400], CHAIN_BLAST_DEADLINE_SECS [9000], CHAIN_IDLE_WAIT_SECS [300], CHAIN_IDLE_RETRY_SECS [20],
# CHAIN_POLL_SECS [15], CHAIN_WATCH_SECS [300], CHAIN_WATCH_DISK_MAX [80], CHAIN_WATCH_MAX_SECS
# [blast deadline + 900], CHAIN_WATCH_END_SECS [watch secs + 300], CHAIN_ENGINE_KEY [a jq path; by
# default the first manifest key named storage_engine, execution_engine, execution_store, db_engine or
# engine], CHAIN_DRIVER_PAT [launch.sh's FLEET_PAT].
# The launcher refuses while a driver's file name is in a running command line (pgrep -f): nothing this
# script runs names one, and its own pgrep pattern starts each name with a bracket class.

set -uo pipefail

utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
say() { echo "CHAIN $* $(utc)"; }
usage() { echo "usage: tasks/bench7/orch-run-chain.sh [--live] <env-file>"; }

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
ROOT="${CHAIN_ROOT:-$(cd "${SELF_DIR}/../.." && pwd)}"
LAUNCH="${CHAIN_LAUNCH:-${ROOT}/benchmark/launch/launch.sh}"
PROM="${CHAIN_PROM_URL:-http://localhost:19090}"
WATCH="${CHAIN_WATCH:-${SELF_DIR}/orch-fleet-health.sh}"
DEPLOY_DEADLINE="${CHAIN_DEPLOY_DEADLINE_SECS:-5400}"
BLAST_DEADLINE="${CHAIN_BLAST_DEADLINE_SECS:-9000}"
IDLE_WAIT="${CHAIN_IDLE_WAIT_SECS:-300}"
IDLE_RETRY="${CHAIN_IDLE_RETRY_SECS:-20}"
POLL="${CHAIN_POLL_SECS:-15}"
WATCH_SECS="${CHAIN_WATCH_SECS:-300}"
WATCH_DISK_MAX="${CHAIN_WATCH_DISK_MAX:-80}"
ENGINE_KEY="${CHAIN_ENGINE_KEY:-}"
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
for v in "${DEPLOY_DEADLINE}" "${BLAST_DEADLINE}" "${IDLE_WAIT}" "${IDLE_RETRY}" "${POLL}" "${WATCH_SECS}" "${WATCH_DISK_MAX}"; do
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
finish() { FINAL=1; exit "$1"; }
stop() { local code="$1"; shift; say "stop reason=$*"; fleet_note; finish "${code}"; }
on_exit() {
    local rc=$?
    [ "${FINAL}" = 1 ] && return 0
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
    for t in jq curl git pgrep ps; do
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
    say "preconditions ok run=${RUN}"
}
preconditions

MANIFEST="${ROOT}/benchmark/results/${RUN}/manifest.json"
LOG_DIR="${CHAIN_LOG_DIR:-${ROOT}/tasks/bench7/${RUN}}"

# --- the plan (no --live): print every step and start nothing ----------------------------------------
if [ "${LIVE}" != 1 ]; then
    say "plan step=1 launch: bash ${LAUNCH} ${ENV_FILE} deploy12"
    say "plan step=2 wait: ^== deploy12 (rc=|LEFT_RUNNING ) in the log launch.sh names, deadline=${DEPLOY_DEADLINE}s; then rc=0 and BENCH_DEPLOY_RESULT rc=0 last_step=12, else stop (exit 10)"
    say "plan step=3 idle-checks: ${PROM} for up to ${IDLE_WAIT}s (every ${IDLE_RETRY}s): up, modes, the switches of benchmark/results/${RUN}/manifest.json .param_arms[0].switches on every node; notes: engine, HOST_PROBE_SUMMARY uniform=yes; a failure stops (exit 11) with the fleet up and idle"
    say "plan step=4 launch: bash ${LAUNCH} ${ENV_FILE} blast15 (the moment the checks pass)"
    say "plan step=5 watch: bash ${WATCH} ${RUN} --watch ${WATCH_SECS} --disk-max ${WATCH_DISK_MAX} --max-secs ${WATCH_MAX} --until-file <blast15 log> > ${LOG_DIR#"${ROOT}"/}/fleet-health-blast15-<UTC>.log"
    say "plan step=6 wait: ^== blast15 (rc=|LEFT_RUNNING ), deadline=${BLAST_DEADLINE}s; then CHAIN done rc=<n> (exit 0 only with rc=0 and BENCH_DEPLOY_RESULT rc=0 last_step=15)"
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

# wait_segment <seg> <deadline-secs> — 0 when the log has its end line (END_LINE, SEG_RC), 1 at the
# deadline, 2 when the wrapper is gone without one (a SIGKILL of the wrapper).
wait_segment() {
    local seg="$1" limit="$2" t0 end="" gone=0
    t0="$(date +%s)"
    END_LINE="" SEG_RC=""
    while :; do
        end="$(grep -E "^== ${seg} (rc=|LEFT_RUNNING )" "${SEG_LOG}" 2>/dev/null | tail -n 1)" || end=""
        if [ -n "${end}" ]; then
            END_LINE="${end}"
            SEG_RC="$(printf '%s\n' "${end}" | sed -n "s/^== ${seg} rc=\\([0-9]*\\).*/\\1/p")"
            [ -n "${SEG_RC}" ] || SEG_RC=125
            return 0
        fi
        if wrapper_alive "${seg}"; then gone=0; else gone=$((gone + 1)); fi
        [ "${gone}" -lt 2 ] || return 2
        [ $(( $(date +%s) - t0 )) -lt "${limit}" ] || return 1
        watch_poll
        sleep "${POLL}"
    done
}

# --- 2. deploy12 -----------------------------------------------------------------------------------
FLEET=deploying
launch_segment deploy12 || { FLEET=none; stop 10 "deploy launch-refused rc=${LAUNCH_RC}"; }
DEPLOY_LOG="${SEG_LOG}"
wait_segment deploy12 "${DEPLOY_DEADLINE}"
case $? in
    1) stop 10 "deploy deadline=${DEPLOY_DEADLINE}s no '== deploy12 rc=' line in ${SEG_LOG#"${ROOT}"/} (the segment may still run)" ;;
    2) stop 10 "deploy died: wrapper pid=${SEG_PID} gone without an rc line in ${SEG_LOG#"${ROOT}"/}" ;;
esac
if grep -Eq '^BENCH_DEPLOY_RESULT rc=0 last_step=12( |$)' "${DEPLOY_LOG}"; then res=ok; else res=missing; fi
say "deploy12 rc=${SEG_RC} result=${res}"
[ "${SEG_RC}" = 0 ] || stop 10 "deploy rc=${SEG_RC} (${END_LINE})"
[ "${res}" = ok ] || stop 10 "deploy result-missing: no 'BENCH_DEPLOY_RESULT rc=0 last_step=12' in ${DEPLOY_LOG#"${ROOT}"/}"
FLEET=idle
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
      + " up=\(($want | length) - ($miss | length))/\($want | length) missing=\(if ($miss | length) == 0 then "-" else ($miss | join(",")) end)"'
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

# idle_check <which> <promql> <jq> — one check; logs its line; 0 when it passed.
FAILED_WHICH="" FAILED_DETAIL=""
idle_check() {
    local which="$1" query="$2" prog="$3" body="" verdict=""
    if body="$(prom_query "${query}")"; then
        verdict="$(printf '%s\n' "${body}" | jq -r --argjson want "${WANT}" --argjson sw "${SWITCHES}" "${prog}" 2>&1)" || verdict="fail jq: $(printf '%s' "${verdict}" | head -n 1)"
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
    idle_check up "max by (node) (up{network=\"${NET}\"} == 1)" "${UP_JQ}" || ok=0
    idle_check modes "max by (node, mode) (tn_node_mode{network=\"${NET}\"} == 1)" "${MODES_JQ}" || ok=0
    idle_check switches "max by (node, name) (tn_node_switch{network=\"${NET}\"})" "${SWITCH_JQ}" || ok=0
    [ "${ok}" = 1 ] && break
    [ $(( $(date +%s) - t_idle )) -lt "${IDLE_WAIT}" ] || stop 11 "idle-check ${FAILED_WHICH} ${FAILED_DETAIL} after ${ROUND} rounds"
    sleep "${IDLE_RETRY}"
done
HP="$(host_probe_note)"
say "idle-checks ok round=${ROUND} engine=$(engine_note) host_probe=${HP}"

# --- 4. blast15 at once, the watch beside it ------------------------------------------------------
launch_segment blast15 || stop 12 "blast launch-refused rc=${LAUNCH_RC}"
FLEET=blasting
[ "${HP}" = uniform ] || say "note host-probe ${HP}: read HOST_PROBE_SUMMARY in ${DEPLOY_LOG#"${ROOT}"/}"
mkdir -p "${LOG_DIR}"
WATCH_LOG="${LOG_DIR}/fleet-health-blast15-$(date -u +%Y%m%dT%H%M%SZ).log"
bash "${WATCH}" "${RUN}" --watch "${WATCH_SECS}" --disk-max "${WATCH_DISK_MAX}" --max-secs "${WATCH_MAX}" \
    --until-file "${SEG_LOG}" > "${WATCH_LOG}" 2>&1 < /dev/null &
WATCH_PID=$!
say "watch started pid=${WATCH_PID} log=${WATCH_LOG#"${ROOT}"/}"

wait_segment blast15 "${BLAST_DEADLINE}"
case $? in
    1) stop 12 "blast deadline=${BLAST_DEADLINE}s no '== blast15 rc=' line in ${SEG_LOG#"${ROOT}"/} (the segment may still run)" ;;
    2) stop 12 "blast died: wrapper pid=${SEG_PID} gone without an rc line in ${SEG_LOG#"${ROOT}"/}" ;;
esac
if grep -Eq '^BENCH_DEPLOY_RESULT rc=0 last_step=15( |$)' "${SEG_LOG}"; then res=present; else res=missing; fi
say "blast15 rc=${SEG_RC} result=${res}"
FLEET=ended

# The watch ends at its next round after the rc line; give it that long, then leave it to --max-secs.
n=0
while [ -n "${WATCH_PID}" ] && kill -0 "${WATCH_PID}" 2>/dev/null && [ "${n}" -lt "${WATCH_END}" ]; do sleep 1; n=$((n + 1)); done
watch_poll
[ -z "${WATCH_PID}" ] || say "watch still-running pid=${WATCH_PID} (it ends by --max-secs ${WATCH_MAX}) log=${WATCH_LOG#"${ROOT}"/}"

say "done rc=${SEG_RC}"
fleet_note
if [ "${SEG_RC}" = 0 ] && [ "${res}" = present ]; then finish 0; fi
finish 12
