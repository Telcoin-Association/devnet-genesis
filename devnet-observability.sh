#!/usr/bin/env bash
#
# devnet-observability.sh — roll out the per-node observability sidecar (Alloy:
# logs + metrics, plus the health endpoint) across the fleet by driving each node's
# tn-node-deployment v2 setup-observability.sh --json over IAP.
#
# Each --enable-* is gated on its config.sh toggle, TN_OBS_ENABLE_LOGS / _METRICS /
# _HEALTH (default-on for devnet); with all three off there is nothing to do. The ingest
# token is fetched ONCE from Secret Manager (only when logs or metrics are on) and reaches
# each node on STDIN (--token-stdin, via tn_iap_ssh_cmd_stdin): never in the remote
# command string (remote argv: ps, sudo's log, the ssh audit trail), never in the
# environment, never echoed or logged. The command logged below is the exact one run.
#
# Enabling logs/metrics on a running node puts the reth JSON-log / --metrics flags on its
# command and RESTARTS it, behind v2's quorum guard (it refuses while another committee
# member is down: a committee of 4 has no margin) and its epoch-boundary wait. So the nodes
# go strictly ONE AT A TIME, and the next one is touched only after this one is back:
# telcoin (and telcoin-alloy.service, when a pipeline was enabled) active and the node in
# the consensus mode it had before (tn_nodeMode; a committee member is CvvActive again).
# A restart the guard deferred, or a node that does not come back, STOPS the sweep: a
# re-run would not restart that node (its flags are already on the node command).
#
# Epoch wait: skipped by default (TN_SKIP_EPOCH_WAIT=1, passed through `sudo env`), since
# on a freshly reset chain there is no boundary worth waiting for. Export
# TN_SKIP_EPOCH_WAIT=0 to keep v2's wait when re-running against a live chain.
#
# --enable-health (TN_OBS_ENABLE_HEALTH=1) makes setup-observability.sh add a BARE
# `--healthcheck <port>` to the node command when no --healthcheck is on it yet, open a ufw
# rule from the monitor's address to that port (it refuses while ufw is inactive: the host
# firewall, devnet-firewall.sh, runs first) and record ENABLE_HEALTHCHECK_MONITOR in
# .node-meta. What it no longer does: on the current node image a bare port binds
# 127.0.0.1, so a flag added HERE is not reachable by the monitor. devnet-finalize.sh bakes
# the reachable one (--enable-healthcheck-monitor); with it on the command the remote script
# adds no flag, and only the ufw rule and the meta key change. A flag it did add is reported
# as a pending restart (below) and stops the sweep.
#
# NOTE: TN_OBS_ENABLE_DASHBOARD is a HUB concern (the Grafana dashboards live on
# the obs VM, provisioned by common/create-obs-instance.sh / obs-vm). It is NOT a
# per-node setup-observability.sh flag, so this script does not act on it — it is
# informational only.
#
# setup-observability.sh --json writes JSON events on STDOUT (the done line decides the
# node's result) and its human-readable progress on STDERR, which goes to the per-node
# log under logs/<timestamp>-observability/ together with the JSON.
#
# Hosts: the node hosts only (tn_node_indices). A worker gateway (the `gateway` entry, and
# the gateway process on a same-host node) is not scraped: tn-node-deployment's Alloy takes
# ONE config file and no fragment directory (lib/observability.sh:29 and :861; docker mounts
# that one file, :949), so a gateway's metrics are read on its host:
# curl 127.0.0.1:${GATEWAY_METRICS_PORT}/metrics.
#
# --staged (deploy step 12; run it AFTER step 10 and BEFORE step 14): puts the flags and
# the Alloy agent on nodes that step 10 (devnet-finalize.sh --stage-only) left installed,
# enabled and STOPPED, and leaves them that way for the coordinated start. The installer
# cannot do that by itself: when setup-observability.sh --json adds a reth log/metrics flag
# it restarts the node unit, and a restart STARTS a stopped unit (tn-node-deployment
# lib/observability.sh:1404-1408; its confirm is forced by TN_ASSUME_YES=true at
# setup-observability.sh:651, and no switch turns the restart off). So the driver does what
# step 10 does: it lets the installer start the node and stops it again. Each node is
# briefly started ALONE (the same thing step 10 does); nothing waits for it to be healthy
# (a genesis validator alone forms no committee, node 5 has no peer yet), it only has to
# be stopped again. One host at a time:
#   1. before (read-only): the node unit exists, is enabled and inactive (an active one is
#      refused, use the normal mode; one not installed or not enabled: deploy step 10);
#      its NRestarts, start stamp and the launch file's sha256 are recorded;
#   2. the normal mode's remote command (same flags, region, push URLs, token on stdin,
#      TN_SKIP_EPOCH_WAIT=1, which --staged requires), judged by its done line. A restart
#      the quorum guard or epoch wait refused ("Not restarting") is the good case here:
#      the flags are in the file and the node never started;
#   3. if the node unit is not inactive afterwards: sudo systemctl stop, then reset-failed
#      (the docker-wrapped unit can end `failed`), never disable, and a wait until it is
#      inactive with no running container (OBS_STAGED_STOP_WAIT_SECS, default 90);
#   4. asserted (read-only): node unit inactive and enabled; telcoin-alloy.service active
#      when logs or metrics are on; the launch file carries the flags the toggles ask for
#      (logs: --log.file.format json and --log.file.directory; metrics: --metrics; health:
#      --healthcheck), read on its non-comment lines. Any failed assertion fails the host;
#   5. one line: OBS_STAGED <instance> node=inactive enabled=yes agent=<active|off>
#      started_by_installer=<yes|no> flags=<ok|not-checked>.
# A failed host stops the sweep (the rest are listed untouched) and the exit is 1: a
# half-staged fleet is looked at before step 14.
#
# Reaches nodes only via the lib's IAP helpers (the always-on wg-allow-iap-ssh door).
# Targets (index, instance name or node name) narrow the sweep; with none it sweeps every
# node host.
#
# Usage:
#   ./devnet-observability.sh                       # all node hosts (a live fleet)
#   ./devnet-observability.sh validator-1-devnet    # some, by index, instance or node name
#   TN_SKIP_EPOCH_WAIT=0 ./devnet-observability.sh  # live chain: keep v2's epoch wait
#   ./devnet-observability.sh --staged [target …]   # deploy step 12: nodes step 10 staged
#                                                   # (each started briefly by the installer,
#                                                   # stopped again here); before step 14
# Exit: 0 ok (--staged: every targeted node host staged), 1 a node failed, 2 usage or config.

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# --- truthiness helper: a toggle is "on" only when exactly "1" -----------------
tn_obs_on() { [ "${1:-0}" = "1" ]; }

# --- knobs (validated: they land in a root command or in shell arithmetic) ------
# TN_SKIP_EPOCH_WAIT: v2's own variable (lib/common.sh tn_wait_restart_window skips the
# wait only for exactly "1"); default 1 here, see the header.
TN_SKIP_EPOCH_WAIT="${TN_SKIP_EPOCH_WAIT:-1}"
# OBS_SETTLE_SECS: how long a node may take to come back after its run (polled every
# OBS_POLL_SECS) before the sweep stops.
OBS_SETTLE_SECS="${OBS_SETTLE_SECS:-300}"
OBS_POLL_SECS="${OBS_POLL_SECS:-5}"
case "${TN_SKIP_EPOCH_WAIT}" in
    0|1) ;;
    *) echo "❌ TN_SKIP_EPOCH_WAIT='${TN_SKIP_EPOCH_WAIT}' must be 0 or 1" >&2; exit 1 ;;
esac
case "${OBS_SETTLE_SECS}:${OBS_POLL_SECS}" in
    *[!0-9:]*|:*|*:|*:0) echo "❌ OBS_SETTLE_SECS / OBS_POLL_SECS must be whole seconds (poll >= 1)" >&2; exit 1 ;;
esac

# --- arguments: flags, then targets (index, instance name or node name) ----------
# Validated up front so a typo fails before we touch a single node.
TARGETS=()
STAGED=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --staged) STAGED=1 ;;
        -h|--help) sed -n '/^# Usage:/,/^# Exit:/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "❌ unknown flag '$1'" >&2; exit 2 ;;
        *) TARGETS+=("$1") ;;
    esac
    shift
done
# OBS_STAGED_STOP_WAIT_SECS (--staged): how long a node the installer started may take to
# be inactive again after the stop (polled every OBS_POLL_SECS).
OBS_STAGED_STOP_WAIT_SECS="${OBS_STAGED_STOP_WAIT_SECS:-90}"
if [ "${STAGED}" -eq 1 ]; then
    case "${OBS_STAGED_STOP_WAIT_SECS}" in
        ''|*[!0-9]*) echo "❌ OBS_STAGED_STOP_WAIT_SECS='${OBS_STAGED_STOP_WAIT_SECS}' must be whole seconds" >&2; exit 2 ;;
    esac
    if [ "${TN_SKIP_EPOCH_WAIT}" != 1 ]; then
        echo "❌ --staged needs TN_SKIP_EPOCH_WAIT=1: the chain has not started, there is no epoch boundary to wait for" >&2
        exit 2
    fi
fi
tn_fleet_check || { echo "❌ the fleet arrays in config.sh are inconsistent (lines above)" >&2; exit 2; }

# tn_obs_resolve <target> — prints the fleet index an index, instance name or node name names.
tn_obs_resolve() {
    local i
    for i in "${!INSTANCE_NAMES[@]}"; do
        if [ "$1" = "${i}" ] || [ "$1" = "${INSTANCE_NAMES[$i]}" ] || [ "$1" = "${NODE_NAMES[$i]}" ]; then
            printf '%s\n' "${i}"; return 0
        fi
    done
    return 1
}
SELECTED=()
if [ "${#TARGETS[@]}" -gt 0 ]; then
    for want in "${TARGETS[@]}"; do
        idx="$(tn_obs_resolve "${want}")" || { echo "❌ unknown target '${want}' (not an index, instance name or node name)" >&2; exit 2; }
        SELECTED+=("${idx}")
    done
fi

# tn_obs_selected <index> — true if this index is in the subset (or no subset given).
tn_obs_selected() {
    [ "${#SELECTED[@]}" -eq 0 ] && return 0
    local s
    for s in "${SELECTED[@]}"; do [ "${s}" = "$1" ] && return 0; done
    return 1
}

# --- the enable flags (one per active toggle; the same for every node) ----------
enable_flags=()
tn_obs_on "${TN_OBS_ENABLE_LOGS}"    && enable_flags+=(--enable-logs)
tn_obs_on "${TN_OBS_ENABLE_METRICS}" && enable_flags+=(--enable-metrics)
tn_obs_on "${TN_OBS_ENABLE_HEALTH}"  && enable_flags+=(--enable-health)
# A pipeline (logs/metrics) needs the ingest token and runs telcoin-alloy.service.
want_alloy=0
if tn_obs_on "${TN_OBS_ENABLE_LOGS}" || tn_obs_on "${TN_OBS_ENABLE_METRICS}"; then
    want_alloy=1
fi

# tn_obs_cmd <region> — the remote command for one node. Every value is a local config
# value, single-quoted; the token is NOT here (it goes on stdin). --push-url /
# --metrics-push-url set the very OBS_PUSH_URL / OBS_METRICS_PUSH_URL the script reads, so
# no env prefix is needed for them; `sudo env` carries only TN_SKIP_EPOCH_WAIT past
# sudoers env_reset. stdin still reaches the script through sudo and env.
tn_obs_cmd() {
    local cmd
    cmd="sudo env TN_SKIP_EPOCH_WAIT=${TN_SKIP_EPOCH_WAIT} bash '${TN_NODE_SCRIPTS_DIR}/setup-observability.sh' --json ${enable_flags[*]}"
    if [ "${want_alloy}" -eq 1 ]; then
        cmd+=" --token-stdin"
    fi
    cmd+=" --region '${1}' --push-url '${OBS_PUSH_URL}' --metrics-push-url '${OBS_METRICS_PUSH_URL}'"
    printf '%s' "${cmd}"
}

# OBS_PROBE_CMD — one read-only round trip that runs ON THE NODE (quoted heredoc: nothing
# expands here): the node unit (telcoin), v2's Alloy unit (telcoin-alloy.service,
# lib/observability.sh OBS_ALLOY_UNIT) and the node's consensus mode from tn_nodeMode on
# its loopback RPC (RPC_PORT from the root-0600 .node-meta, hence sudo; else 8545). It
# always ends with one "__tn_obs ..." line, so ssh success reflects transport only.
IFS= read -r -d '' OBS_PROBE_CMD <<'EOF' || true
t="$(systemctl is-active telcoin 2>/dev/null)"
a="$(systemctl is-active telcoin-alloy.service 2>/dev/null)"
p="$(sudo sed -n 's/^RPC_PORT=//p' /etc/telcoin/.node-meta 2>/dev/null | tail -n 1 | tr -cd 0-9)"
m="$(curl -s --max-time 5 -H 'Content-Type: application/json' --data '{"jsonrpc":"2.0","id":1,"method":"tn_nodeMode","params":[]}' "http://127.0.0.1:${p:-8545}" 2>/dev/null | sed -n 's/.*"result":"\([A-Za-z]*\)".*/\1/p')"
echo "__tn_obs telcoin=${t:-unknown} alloy=${a:-unknown} mode=${m:-unknown}"
EOF

# tn_obs_probe <instance> <zone> <node-log> — print "telcoin=<state> alloy=<state>
# mode=<mode>"; rc 1 (nothing printed) when the node did not answer. </dev/null: a probe
# must not read the caller's stdin.
tn_obs_probe() {
    local out
    out="$(tn_iap_ssh "$1" "$2" "${OBS_PROBE_CMD}" </dev/null 2>>"$3")" || true
    out="$(printf '%s\n' "${out}" | tr -d '\r' | grep '^__tn_obs ' | tail -n 1)" || true
    [ -n "${out}" ] || return 1
    printf '%s\n' "${out#__tn_obs }"
}

# tn_obs_field <probe-fields> <key> — one field's value ("" when absent).
tn_obs_field() { printf '%s\n' "$1" | tr ' ' '\n' | sed -n "s/^$2=//p"; }

# tn_obs_wait_back <instance> <zone> <mode> <need-alloy:0|1> <node-log> — poll until
# telcoin is active, telcoin-alloy.service too when need-alloy is 1, and the node reports
# <mode> again (not checked when <mode> is "unknown"). rc 1 after OBS_SETTLE_SECS.
tn_obs_wait_back() {
    local inst="$1" zone="$2" want_mode="$3" need_alloy="$4" nlog="$5" waited=0 probe t a m
    while :; do
        probe="$(tn_obs_probe "${inst}" "${zone}" "${nlog}")" || probe=""
        t="$(tn_obs_field "${probe}" telcoin)"
        a="$(tn_obs_field "${probe}" alloy)"
        m="$(tn_obs_field "${probe}" mode)"
        if [ "${t}" = active ] \
            && { [ "${need_alloy}" -eq 0 ] || [ "${a}" = active ]; } \
            && { [ "${want_mode}" = unknown ] || [ "${m}" = "${want_mode}" ]; }; then
            echo "    after (${waited}s): telcoin=${t} telcoin-alloy.service=${a} mode=${m}"
            return 0
        fi
        if [ "${waited}" -ge "${OBS_SETTLE_SECS}" ]; then
            echo "    ❌ ${inst} not back within ${OBS_SETTLE_SECS}s: telcoin=${t:-no-answer} telcoin-alloy.service=${a:-?} mode=${m:-?} (want telcoin=active$([ "${need_alloy}" -eq 1 ] && printf ' telcoin-alloy.service=active') mode=${want_mode})" >&2
            return 1
        fi
        echo "    … waiting for ${inst} (${waited}s/${OBS_SETTLE_SECS}s): telcoin=${t:-no-answer} telcoin-alloy.service=${a:-?} mode=${m:-?}"
        sleep "${OBS_POLL_SECS}"
        waited=$((waited + OBS_POLL_SECS))
    done
}

# tn_obs_restart_pending <stdout> — 0 when the run left the node restart that makes its
# new flags live undone: the quorum guard or the epoch wait refused it (warn "Not
# restarting: ..."; the run still ends done ok:true), or --enable-health had to add
# --healthcheck (its --json path never restarts the node).
tn_obs_restart_pending() {
    case "$1" in
        *'"event":"warn","msg":"Not restarting'*|*'"event":"warn","msg":"Added --healthcheck'*) return 0 ;;
    esac
    return 1
}

# tn_obs_judge_run <instance> <stdout> <ssh-rc> <node-log> — print the run's warn/error
# events, then judge its done line: rc 0 when it says ok and ssh exited 0.
tn_obs_judge_run() {
    local events ev done_line
    # Every warn/error event, for the operator (the rest is in the node log).
    events="$(printf '%s\n' "$2" | grep -E '"event":"(warn|error)"' || true)"
    if [ -n "${events}" ]; then
        while IFS= read -r ev; do
            echo "      [$(tn_json_str "${ev}" event)] $(tn_json_str "${ev}" msg)"
        done <<< "${events}"
    fi

    done_line="$(tn_json_done_line "$2")"
    if [ -z "${done_line}" ]; then
        echo "    ❌ no done line from setup-observability.sh on $1 (ssh rc=$3; see $4)" >&2
    elif ! tn_json_true "${done_line}" ok; then
        echo "    ❌ setup-observability.sh failed on $1: $(tn_json_str "${done_line}" msg)" >&2
    elif [ "$3" -ne 0 ]; then
        echo "    ❌ setup-observability.sh said ok on $1 but exited rc=$3 (see $4)" >&2
    else
        echo "    done: ok, applied [$(printf '%s' "${done_line}" | sed -n 's/.*"applied":\[\([^]]*\)\].*/\1/p' | tr -d '"')]"
        return 0
    fi
    return 1
}

# --- --staged helpers --------------------------------------------------------------
# The launch file step 10 leaves: the v2 docker start script (devnet-finalize.sh asserts it
# is the unit's ExecStart, its TN_START_DOCKER), the file tn-node-deployment's
# tn_node_launch_target picks and setup-observability.sh patches.
OBS_LAUNCH_FILE="/usr/local/libexec/telcoin/tn-start-docker"

# tn_obs_staged_probe_cmd <unit> — one read-only round trip ON THE NODE: the unit's
# ActiveState, is-enabled, NRestarts and ActiveEnterTimestampMonotonic (it moves on every
# start, so a start is seen even when the node is down again), the Alloy unit, whether a
# container named <unit> runs, the launch file's sha256 and which of the flags the remote
# script adds stand on a non-comment line of it (lib/observability.sh:146 and :195,
# health: --healthcheck). Ends with one "__tn_obs_st ..." line.
tn_obs_staged_probe_cmd() {
    printf "svc='%s'\nlf='%s'\n" "$1" "${OBS_LAUNCH_FILE}"
    cat <<'EOF'
st="$(systemctl show -p ActiveState --value "$svc" 2>/dev/null)"
en="$(systemctl is-enabled "$svc" 2>/dev/null)"
nr="$(systemctl show -p NRestarts --value "$svc" 2>/dev/null)"
at="$(systemctl show -p ActiveEnterTimestampMonotonic --value "$svc" 2>/dev/null)"
al="$(systemctl is-active telcoin-alloy.service 2>/dev/null)"
ct="$(sudo docker inspect -f '{{.State.Running}}' "$svc" 2>/dev/null)"
sum="$(sudo sha256sum "$lf" 2>/dev/null | cut -c1-64)"
body="$(sudo grep -v '^[[:space:]]*#' "$lf" 2>/dev/null)"
L="(^|[[:space:]\"'(])"; R="([[:space:]=\"')]|\$)"
has() { printf '%s\n' "$body" | grep -Eq -- "$1"; }
f=""
has "${L}--log\\.file\\.format[\"']?[[:space:]=]+[\"']?json${R}" && f="${f},log-json"
has "${L}--log\\.file\\.directory${R}" && f="${f},log-dir"
has "${L}--metrics${R}" && f="${f},metrics"
has "${L}--healthcheck${R}" && f="${f},healthcheck"
f="${f#,}"
echo "__tn_obs_st state=${st:-unknown} enabled=${en:-unknown} nrestarts=${nr:-?} enter=${at:-?} alloy=${al:-unknown} container=${ct:-none} sum=${sum:-none} flags=${f:-none}"
EOF
}

# tn_obs_staged_probe <instance> <zone> <unit> <node-log> — the fields of that line; one
# retry on ssh rc 255 (read-only); rc 1 (nothing printed) when the node did not answer.
tn_obs_staged_probe() {
    local cmd out r=0
    cmd="$(tn_obs_staged_probe_cmd "$3")"
    out="$(tn_iap_ssh "$1" "$2" "${cmd}" </dev/null 2>>"$4")" || r=$?
    if [ "${r}" -eq 255 ]; then
        out="$(tn_iap_ssh "$1" "$2" "${cmd}" </dev/null 2>>"$4")" || true
    fi
    out="$(printf '%s\n' "${out}" | tr -d '\r' | grep '^__tn_obs_st ' | tail -n 1)" || true
    [ -n "${out}" ] || return 1
    printf '%s\n' "${out#__tn_obs_st }"
    printf '%s\n' "--- probe: ${out#__tn_obs_st }" >>"$4"
}

# tn_obs_staged_down <probe-fields> — rc 0 when the node is down: unit inactive and no
# running container.
tn_obs_staged_down() {
    [ "$(tn_obs_field "$1" state)" = inactive ] && [ "$(tn_obs_field "$1" container)" != true ]
}

# tn_obs_stage_host <index> — --staged on one node host (steps 1-5 of the header). rc 0
# when it ends staged (prints the OBS_STAGED line); rc 1 when not (why, on stderr).
tn_obs_stage_host() {
    local i="$1" inst zone region nlog unit pre post st en sum remote_cmd out ssh_rc=0 done_ok=0
    local started=no waited=0 agent=off flags_res=ok want missing="" w bad=""
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    region="$(tn_region_from_zone "${zone}")"
    unit="$(tn_service_for_role "$(tn_node_role "${i}")")"
    nlog="${RUN_LOG_DIR}/${inst}.log"
    echo ""
    echo ">>> ${inst} (${zone}, region=${region}): staged: setup-observability.sh ${enable_flags[*]}"

    # (1) Before (read-only): installed, enabled and stopped, as step 10 leaves it.
    pre="$(tn_obs_staged_probe "${inst}" "${zone}" "${unit}" "${nlog}")" || {
        echo "    ❌ ${inst} did not answer the state probe (see ${nlog}); nothing was changed there." >&2
        return 1
    }
    st="$(tn_obs_field "${pre}" state)"
    en="$(tn_obs_field "${pre}" enabled)"
    sum="$(tn_obs_field "${pre}" sum)"
    case "${st}" in
        active|activating|reloading|deactivating)
            echo "    ❌ ${unit} is ${st} on ${inst}: --staged takes a node step 10 left stopped; a running node takes" >&2
            echo "       the normal mode (./devnet-observability.sh ${inst}). Nothing was changed there." >&2
            return 1 ;;
    esac
    if [ "${st}" != inactive ] || [ "${en}" != enabled ] || [ "${sum}" = none ]; then
        echo "    ❌ ${inst} is not staged (${unit} ActiveState=${st} is-enabled=${en}, launch file ${OBS_LAUNCH_FILE}" >&2
        echo "       $([ "${sum}" = none ] && echo 'missing or unreadable' || echo present)): run deploy step 10 (devnet-finalize.sh --stage-only) first. Nothing was changed there." >&2
        return 1
    fi
    echo "    before: ${unit} inactive, enabled, NRestarts=$(tn_obs_field "${pre}" nrestarts); launch file sha256 $(printf '%.12s' "${sum}")…"

    # (2) The run: the normal mode's command; stdout = JSON (parsed), stderr = node log.
    remote_cmd="$(tn_obs_cmd "${region}")"
    echo "    + ${remote_cmd}$([ "${want_alloy}" -eq 1 ] && printf '   [token on stdin]')"
    out="$(printf '%s\n' "${token}" | tn_iap_ssh_cmd_stdin "${inst}" "${zone}" "${remote_cmd}" 2>>"${nlog}")" || ssh_rc=$?
    { echo "--- setup-observability.sh --json stdout (rc=${ssh_rc})"; printf '%s\n' "${out}"; } >>"${nlog}"
    tn_obs_judge_run "${inst}" "${out}" "${ssh_rc}" "${nlog}" && done_ok=1
    case "${out}" in
        *'"event":"warn","msg":"Not restarting'*)
            echo "    the installer did not restart the node (its guard refused): the flags are in the file and the node never started" ;;
    esac
    case "${out}" in
        *'"event":"warn","msg":"Added --healthcheck'*)
            echo "    --healthcheck added to the launch file: the node binds it at its first start (step 14)" ;;
    esac

    # (3) After: whatever the run's result, a node it started is stopped again (never
    # disabled). One stop, then read-only polls.
    post="$(tn_obs_staged_probe "${inst}" "${zone}" "${unit}" "${nlog}")" || {
        echo "    ❌ ${inst} did not answer after the run: ${unit} may be RUNNING. On the host: sudo systemctl stop ${unit} (see ${nlog})." >&2
        return 1
    }
    if ! tn_obs_staged_down "${post}"; then
        started=yes
        echo "    the installer started ${unit} ($(tn_obs_field "${post}" state)): stopping it again"
        echo "    + sudo systemctl stop ${unit}; sudo systemctl reset-failed ${unit}"
        tn_iap_ssh "${inst}" "${zone}" "sudo systemctl stop '${unit}'; echo \"__tn_obs_stop rc=\$?\"; sudo systemctl reset-failed '${unit}' >/dev/null 2>&1 || true" \
            </dev/null >>"${nlog}" 2>&1 || true
        while :; do
            post="$(tn_obs_staged_probe "${inst}" "${zone}" "${unit}" "${nlog}")" || post=""
            tn_obs_staged_down "${post}" && break
            if [ "${waited}" -ge "${OBS_STAGED_STOP_WAIT_SECS}" ]; then
                echo "    ❌ ${unit} on ${inst} not inactive ${OBS_STAGED_STOP_WAIT_SECS}s after the stop (state=$(tn_obs_field "${post}" state) container=$(tn_obs_field "${post}" container)): it may be RUNNING ALONE. Stop it by hand before step 14." >&2
                return 1
            fi
            sleep "${OBS_POLL_SECS}"
            waited=$((waited + OBS_POLL_SECS))
        done
        echo "    stopped (${waited}s after the stop)"
    elif [ "$(tn_obs_field "${post}" enter)" != "$(tn_obs_field "${pre}" enter)" ] \
        || [ "$(tn_obs_field "${post}" nrestarts)" != "$(tn_obs_field "${pre}" nrestarts)" ]; then
        started=yes
        echo "    ⚠️  ${unit} was started during the run and is down again (start stamp/NRestarts moved): see ${nlog}"
    fi

    # (4) Asserted on the last probe (read-only).
    [ "$(tn_obs_field "${post}" enabled)" = enabled ] || bad="${bad} is-enabled=$(tn_obs_field "${post}" enabled);"
    if [ "${want_alloy}" -eq 1 ]; then
        agent="$(tn_obs_field "${post}" alloy)"
        [ "${agent}" = active ] || bad="${bad} telcoin-alloy.service=${agent};"
    fi
    want=""
    tn_obs_on "${TN_OBS_ENABLE_LOGS}"    && want="${want} log-json log-dir"
    tn_obs_on "${TN_OBS_ENABLE_METRICS}" && want="${want} metrics"
    tn_obs_on "${TN_OBS_ENABLE_HEALTH}"  && want="${want} healthcheck"
    if [ "$(tn_obs_field "${post}" sum)" = none ]; then
        flags_res=not-checked
        echo "    ⚠️  ${OBS_LAUNCH_FILE} unreadable after the run: its flags were NOT checked"
    else
        for w in ${want}; do
            case ",$(tn_obs_field "${post}" flags)," in *",${w},"*) ;; *) missing="${missing} ${w}" ;; esac
        done
        [ -z "${missing}" ] || bad="${bad} launch file lacks:${missing};"
        [ "$(tn_obs_field "${post}" sum)" = "${sum}" ] && echo "    launch file unchanged (its flags were already on it)"
    fi
    [ "${done_ok}" -eq 1 ] || bad="${bad} setup-observability.sh did not end ok;"
    if [ -n "${bad}" ]; then
        echo "    ❌ ${inst} not staged:${bad} (node is stopped; see ${nlog})" >&2
        return 1
    fi
    echo "OBS_STAGED ${inst} node=inactive enabled=yes agent=${agent} started_by_installer=${started} flags=${flags_res}"
}

RUN_LOG_DIR="${DEVNET_LIB_DIR}/logs/$(date +%Y%m%d_%H%M%S)-observability"

echo "=========================================="
echo "devnet observability rollout (Alloy logs/metrics/health)"
echo "Project:    ${PROJECT_ID}"
echo "Push URL:   ${OBS_PUSH_URL}"
echo "Metrics:    ${OBS_METRICS_PUSH_URL}"
echo "Toggles:    logs=${TN_OBS_ENABLE_LOGS} metrics=${TN_OBS_ENABLE_METRICS} health=${TN_OBS_ENABLE_HEALTH} (dashboard=${TN_OBS_ENABLE_DASHBOARD}: hub-only, not applied here)"
echo "Epoch wait: $([ "${TN_SKIP_EPOCH_WAIT}" = 1 ] && echo "skipped (TN_SKIP_EPOCH_WAIT=1)" || echo "v2 default (TN_SKIP_EPOCH_WAIT=0)")"
[ "${#TARGETS[@]}" -gt 0 ] && echo "Subset:     ${TARGETS[*]}"
[ "${STAGED}" -eq 1 ] && echo "Mode:       --staged (deploy step 12): stopped nodes stay stopped; a node the installer starts is stopped again (wait ${OBS_STAGED_STOP_WAIT_SECS}s)"
echo "Gateways:   not scraped (Alloy takes one config file); on the host: curl 127.0.0.1:${GATEWAY_METRICS_PORT}/metrics"
echo "Logs:       ${RUN_LOG_DIR}"
echo "=========================================="

if [ "${#enable_flags[@]}" -eq 0 ]; then
    echo ""
    echo ">>> all obs toggles off — nothing to do"
    exit 0
fi
mkdir -p "${RUN_LOG_DIR}"

# Fetch the ingest token ONCE (read-only), only when a pipeline needs it. Fail loud if
# empty so we never enable a pipeline without auth. v2's --token-stdin reads ONE line,
# so a multi-line value is refused here rather than silently cut.
token=""
if [ "${want_alloy}" -eq 1 ]; then
    echo ""
    echo ">>> fetching obs ingest token from Secret Manager (${OBS_SECRET_NAME}) — value is NEVER printed"
    token="$(tn_secret "${OBS_SECRET_NAME}")"
    if [ -z "${token}" ]; then
        echo "❌ obs ingest token (${OBS_SECRET_NAME}) is empty — refusing to roll out without it." >&2
        exit 1
    fi
    case "${token}" in
        *$'\n'*) echo "❌ obs ingest token (${OBS_SECRET_NAME}) spans several lines; --token-stdin reads one — refusing." >&2; exit 1 ;;
    esac
    echo "    token retrieved (redacted)"
fi

rc=0
stop=0
ok_nodes=()
failed_nodes=()
untouched_nodes=()
for i in $(tn_indices_by_role gateway); do
    if tn_obs_selected "${i}"; then
        echo ""
        echo "↪ ${INSTANCE_NAMES[$i]}: gateway host, no node: skipped (metrics on the host: curl 127.0.0.1:${GATEWAY_METRICS_PORT}/metrics)"
    fi
done

# --staged: one host after another; the first that is not staged stops the sweep.
if [ "${STAGED}" -eq 1 ]; then
    for i in $(tn_node_indices); do
        tn_obs_selected "${i}" || continue
        if [ "${stop}" -eq 1 ]; then
            untouched_nodes+=("${INSTANCE_NAMES[$i]}")
        elif tn_obs_stage_host "${i}"; then
            ok_nodes+=("${INSTANCE_NAMES[$i]}")
        else
            echo "    ❌ stopping the sweep: a half-staged fleet is looked at before step 14." >&2
            failed_nodes+=("${INSTANCE_NAMES[$i]}")
            rc=1
            stop=1
        fi
    done
    echo ""
    echo "=========================================="
    [ "${#ok_nodes[@]}" -gt 0 ]        && echo "staged:    ${ok_nodes[*]}"
    [ "${#failed_nodes[@]}" -gt 0 ]    && echo "FAILED:    ${failed_nodes[*]}"
    [ "${#untouched_nodes[@]}" -gt 0 ] && echo "untouched: ${untouched_nodes[*]} (sweep stopped; re-run with these names once the failure is fixed)"
    echo "per-node logs: ${RUN_LOG_DIR}"
    if [ "${rc}" -eq 0 ]; then
        echo "every targeted node host is staged (stopped, enabled, flags on): ready for step 14."
    else
        echo "staged observability finished WITH ERRORS — see the ❌ lines above; do not run step 14 yet." >&2
    fi
    echo "=========================================="
    exit "${rc}"
fi
for i in $(tn_node_indices); do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"

    tn_obs_selected "${i}" || continue
    if [ "${stop}" -eq 1 ]; then
        untouched_nodes+=("${inst}")
        continue
    fi

    region="$(tn_region_from_zone "${zone}")"
    nlog="${RUN_LOG_DIR}/${inst}.log"

    echo ""
    echo ">>> ${inst} (${zone}, region=${region}): setup-observability.sh ${enable_flags[*]}"

    # (1) Before: the node must be up (else the guard on every node after it counts it as
    # down), and its consensus mode is what it must return to.
    probe="$(tn_obs_probe "${inst}" "${zone}" "${nlog}")" || probe=""
    pre_state="$(tn_obs_field "${probe}" telcoin)"
    pre_mode="$(tn_obs_field "${probe}" mode)"
    if [ "${pre_state}" != active ]; then
        echo "    ❌ telcoin is not active on ${inst} before the run (${pre_state:-no answer}) — stopping the sweep (see ${nlog})." >&2
        failed_nodes+=("${inst}")
        rc=1
        stop=1
        continue
    fi
    [ -n "${pre_mode}" ] || pre_mode=unknown
    echo "    before: telcoin=active mode=${pre_mode}"
    [ "${pre_mode}" = unknown ] && echo "    ⚠️  tn_nodeMode unreadable on ${inst}: only telcoin being active is checked after the run"

    # (2) The run. stdout = JSON (parsed); stderr = progress (node log).
    remote_cmd="$(tn_obs_cmd "${region}")"
    echo "    + ${remote_cmd}$([ "${want_alloy}" -eq 1 ] && printf '   [token on stdin]')"
    out=""
    ssh_rc=0
    out="$(printf '%s\n' "${token}" | tn_iap_ssh_cmd_stdin "${inst}" "${zone}" "${remote_cmd}" 2>>"${nlog}")" || ssh_rc=$?
    { echo "--- setup-observability.sh --json stdout (rc=${ssh_rc})"; printf '%s\n' "${out}"; } >>"${nlog}"

    done_ok=0
    tn_obs_judge_run "${inst}" "${out}" "${ssh_rc}" "${nlog}" && done_ok=1

    pending=0
    if tn_obs_restart_pending "${out}"; then
        pending=1
        echo "    ❌ the node restart that makes the new flags live did NOT happen on ${inst} (events above)." >&2
        echo "       A re-run will not restart it (the flags are already on the node command). Once the" >&2
        echo "       committee is whole: sudo bash ${TN_NODE_SCRIPTS_DIR}/edit-config.sh, item 12 (Restart node)." >&2
    fi

    # (3) After: back (telcoin active, Alloy active when a pipeline was enabled, same mode)
    # before the next node, whose quorum guard counts this one.
    back=1
    need_alloy=0
    [ "${want_alloy}" -eq 1 ] && [ "${done_ok}" -eq 1 ] && need_alloy=1
    tn_obs_wait_back "${inst}" "${zone}" "${pre_mode}" "${need_alloy}" "${nlog}" || back=0

    if [ "${done_ok}" -eq 1 ] && [ "${pending}" -eq 0 ] && [ "${back}" -eq 1 ]; then
        ok_nodes+=("${inst}")
    else
        failed_nodes+=("${inst}")
        rc=1
    fi
    if [ "${pending}" -eq 1 ] || [ "${back}" -eq 0 ]; then
        echo "    ❌ stopping the sweep: the next node's quorum guard would count ${inst} as down." >&2
        stop=1
    fi
done

echo ""
echo "=========================================="
[ "${#ok_nodes[@]}" -gt 0 ]        && echo "ok:        ${ok_nodes[*]}"
[ "${#failed_nodes[@]}" -gt 0 ]    && echo "FAILED:    ${failed_nodes[*]}"
[ "${#untouched_nodes[@]}" -gt 0 ] && echo "untouched: ${untouched_nodes[*]} (sweep stopped; re-run with these names once the failure is fixed)"
echo "per-node logs: ${RUN_LOG_DIR}"
if [ "${rc}" -eq 0 ]; then
    echo "observability rollout complete on all targeted nodes."
else
    echo "observability rollout finished WITH ERRORS — see the ❌ lines above." >&2
fi
echo "=========================================="
exit "${rc}"
