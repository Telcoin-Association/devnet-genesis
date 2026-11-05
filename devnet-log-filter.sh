#!/usr/bin/env bash
#
# devnet-log-filter.sh — set the level of each devnet node's JSON file log (the reth log Alloy
# ships to Loki) by putting `--log.file.filter <filter>` on the node command in its v2 start script
# (/usr/local/libexec/telcoin/tn-start-docker), then restarting the node, one node at a time, so the
# new level is live. The launch line devnet-finalize.sh renders sets no --log.file.filter, so the file
# log runs at the level of the -vvv stdout flags (DEBUG), which is most of obs-devnet's Loki volume.
#
# Order: observers first, then validators, each group in index order, whatever order the targets are
# given in. After a node it restarted (and only then), the sweep waits LOGFILTER_SETTLE_SECS (90)
# before the next node, so the restarted one is voting again before the next one's guard counts.
#
# Per node, session 1 (`# logfilter: apply`, a root script on stdin through tn_iap_ssh_stdin) sources
# the node's v2 lib (${TN_NODE_SCRIPTS_DIR}/lib/common.sh) and:
#   1. pre-checks, before any change: the lib is there with the functions used below, telcoin is
#      active, the start script is readable, and its node command already writes the JSON file log
#      (`--log.file.format json`, from setup-observability.sh); unless --no-restart, the host path
#      of that log can be found (see the verify session);
#   2. when the flag does not read <filter> yet, backs the start script up to
#      <script>.bak-logfilter-<UTC stamp> (cp -p); then tn_launch_flag_set <script>
#      --log.file.filter <filter> (an atomic root write; it never restarts anything; rc 1 = the
#      flag already reads that value, and any backup is removed);
#   3. when the running container's arguments already carry the flag: done, no restart;
#      with --no-restart: done, the new level takes effect at the node's next restart;
#   4. otherwise v2's committee guard (tn_committee_down_guard), v2's epoch-boundary wait
#      (tn_wait_restart_window; --skip-epoch-wait exports TN_SKIP_EPOCH_WAIT=1 inside this session
#      script only, never in the operator's shell), the guard again (the wait can be long), and
#      `systemctl restart telcoin`. The session unsets TN_ALLOW_QUORUM_RISK. The guard counts the
#      members that are up from ONE consensus commit, whose sub-DAG often carries only n-1 authors
#      with nobody down (a committee of 4 then reads as one member down, and is refused), so a
#      refusal is resampled: up to LOGFILTER_GUARD_TRIES (8) calls, LOGFILTER_GUARD_SECS (10) s
#      apart, and the node is deferred only when every call refused. A guard that passes with a
#      warning (on devnet it goes ahead when it cannot count the committee: no committee or commit
#      readable, a commit over 120 s old or from another epoch) defers the node at once.
# After a restart the driver waits for the node (wait_healthy: unit active and the healthcheck port
# answering, HEALTH_TIMEOUT_SECS) and opens session 2 (`# logfilter: verify`): the restarted
# container's arguments must carry the flag, and the last 300 lines of the node's JSON file log that
# were written after the container started must hold no "level":"DEBUG" line (and at least one line).
# The log's host path is derived on the node, never assumed: the container directory the start script
# gives --log.file.directory, mapped through the running container's bind mounts, plus the
# telcoin-network-logs/reth.log the node appends to it (on devnet: <DATA_DIR>/logs/...).
#
# Every session prints one marker line per step on stdout; the last one decides the node:
#   LOGFILTER_SET <inst> flag=--log.file.filter value=<f> rc=<0|1> was=<old value|-> backup=<path|none>
#   LOGFILTER_OK <inst> restarted=no                     the flag was already live (when a LOGFILTER_WAIT
#                                                        or LOGFILTER_RESTART line precedes it, or a
#                                                        precheck_active failure, devnet-lib re-sent the
#                                                        session after a drop past the restart: the
#                                                        driver still waits for the node and verifies it)
#   LOGFILTER_OK <inst> restarted=no level_check=skipped --no-restart
#   LOGFILTER_DEFERRED <inst> reason=guard               the committee guard refused the restart
#   LOGFILTER_DEFERRED <inst> reason=guard_blind         the guard could not count the committee
#   LOGFILTER_WAIT <inst> secs=<n>                       the node's reading of the seconds to the epoch
#                                                        boundary (unknown when unreadable, 0 with
#                                                        --skip-epoch-wait), printed before the wait
#   LOGFILTER_RESTART <inst> at=<ISO-8601 UTC>
#   LOGFILTER_VERIFY <inst> flag=<yes|no> debug_lines=<n> lines=<n>
#   LOGFILTER_OK <inst> restarted=yes level_check=ok     printed by the driver after a good verify
#   LOGFILTER_FAIL <inst> reason=<why>                   from either side
# A DEFERRED or FAIL node STOPS the sweep: the nodes after it are not touched, and the driver prints
# the command that resumes with the remaining nodes. A failed node whose start script this run
# changed (LOGFILTER_SET rc=0) gets the rollback (put the old value back, or restore the named
# backup, then restart); any other failed node gets "nothing changed". A deferred
# node's start script already carries the flag; the resume run finds it set (rc 1) and restarts it
# once the guard allows.
#
# Re-run after any devnet-finalize.sh or devnet-update.sh --finalize / --wipe: those re-render the
# start script from v2 without --log.file.filter, and the file log is back at DEBUG from the node's
# next start.
#
# Usage:
#   ./devnet-log-filter.sh                      # dry run: the per-node plan, no ssh
#   ./devnet-log-filter.sh --yes                # every node in INSTANCE_NAMES
#   ./devnet-log-filter.sh --yes node5 1        # a subset: index (0-based), INSTANCE_NAME or NODE_NAME
#   ./devnet-log-filter.sh --yes --filter 'info,tn_primary=debug'
#   ./devnet-log-filter.sh --yes --skip-epoch-wait
#   ./devnet-log-filter.sh --yes --no-restart   # write the flag only; it is live after the next restart
# Knobs (env): DEVNET_NODE_LOG_FILTER (default filter, info), LOGFILTER_SETTLE_SECS (90),
# LOGFILTER_GUARD_TRIES (8) / LOGFILTER_GUARD_SECS (10) (the guard's resampling, see 4. above),
# HEALTH_TIMEOUT_SECS / HEALTH_POLL_SECS (wait_healthy, devnet-lib.sh), TN_IAP_RETRIES (devnet-lib.sh).
# Exit: 0 every targeted node ended LOGFILTER_OK (or the dry run printed its plan); 1 a node was
# deferred or failed (the sweep stopped there); 2 a bad option, value or target (nothing touched).

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# The v2 start script of a docker install (lib/common.sh tn_start_script_path docker).
LF_START_SCRIPT="/usr/local/libexec/telcoin/tn-start-docker"

_usage() {
    cat <<'EOF'
usage: ./devnet-log-filter.sh [--yes] [--filter <f>] [--skip-epoch-wait] [--no-restart] [target ...]
  --yes              apply (without it: print the per-node plan and open no ssh)
  --filter <f>       the --log.file.filter value, any reth directive string (default
                     ${DEVNET_NODE_LOG_FILTER:-info})
  --skip-epoch-wait  do not wait for the epoch boundary before a restart (TN_SKIP_EPOCH_WAIT=1 in the
                     node's session only)
  --no-restart       write the flag into each start script and restart nothing
  target             an index (0-based), an INSTANCE_NAME or a NODE_NAME; none = every node
Order: observers first, then validators, each in index order. Re-run after any devnet-finalize.sh or
devnet-update.sh --finalize / --wipe (they re-render the launch line without the flag).
EOF
}

# Same selector as devnet-finalize.sh: no args → all nodes; args may be an index (0-based), an
# INSTANCE_NAME or a NODE_NAME. A node named twice is visited once. An unknown target is an error
# (rc 1, the list of known targets on stderr), never a silent empty run.
tn_select_indices() {
    local out=() arg i matched
    if [ "$#" -eq 0 ]; then
        for i in "${!INSTANCE_NAMES[@]}"; do out+=("$i"); done
        printf '%s\n' "${out[@]}"; return 0
    fi
    for arg in "$@"; do
        matched=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            if [ "${arg}" = "${i}" ] || [ "${arg}" = "${INSTANCE_NAMES[$i]}" ] || [ "${arg}" = "${NODE_NAMES[$i]}" ]; then
                case " ${out[*]+"${out[*]}"} " in *" ${i} "*) ;; *) out+=("$i") ;; esac
                matched=1; break
            fi
        done
        if [ -z "${matched}" ]; then
            echo "❌ unknown target: ${arg} (expected an index, INSTANCE_NAME, or NODE_NAME)" >&2
            for i in "${!INSTANCE_NAMES[@]}"; do
                echo "     ${i}  ${INSTANCE_NAMES[$i]}  ${NODE_NAMES[$i]}  (${NODE_ROLES[$i]})" >&2
            done
            return 1
        fi
    done
    printf '%s\n' "${out[@]}"
}

# --- arguments: options anywhere among the targets ---------------------------------------
LF_APPLY=0
LF_FILTER="${DEVNET_NODE_LOG_FILTER:-info}"
LF_FILTER_GIVEN=0
LF_SKIP_EPOCH_WAIT=0
LF_NO_RESTART=0
_targets=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --yes) LF_APPLY=1 ;;
        --filter)
            if [ "$#" -lt 2 ]; then echo "❌ --filter needs a value" >&2; _usage >&2; exit 2; fi
            LF_FILTER="$2"; LF_FILTER_GIVEN=1; shift ;;
        --filter=*) LF_FILTER="${1#--filter=}"; LF_FILTER_GIVEN=1 ;;
        --skip-epoch-wait) LF_SKIP_EPOCH_WAIT=1 ;;
        --no-restart) LF_NO_RESTART=1 ;;
        -h|--help) _usage; exit 0 ;;
        -*) echo "❌ unknown option: $1" >&2; _usage >&2; exit 2 ;;
        *) _targets+=("$1") ;;
    esac
    shift
done
set -- ${_targets[@]+"${_targets[@]}"}
unset _targets

# The filter lands single-quoted in a root script and, verbatim, in the node command. v2's
# tn_launch_flag_set refuses what is not one shell word; refuse here what could leave the quotes.
case "${LF_FILTER}" in
    ""|-*|"#"*|*[[:space:]]*|*"'"*|*'"'*|*'\'*|*'$'*|*'`'*)
        echo "❌ --filter '${LF_FILTER}': one reth directive string (no spaces, quotes, \\, \$ or backticks; not starting with - or #)" >&2
        exit 2 ;;
esac
# Each comma-separated directive is a level, a target, or target=level (any case): the node does
# not start on a directive it cannot parse, and systemd would restart it in a loop.
if printf '%s\n' "${LF_FILTER}" | tr ',' '\n' \
    | grep -Eiqv '^(([A-Za-z0-9_:.-]+=)?(off|error|warn|info|debug|trace)|[A-Za-z0-9_:.-]+)$'; then
    echo "❌ --filter '${LF_FILTER}': every comma-separated directive must be <level>, <target> or <target>=<level>" >&2
    echo "   (level: off|error|warn|info|debug|trace); reth would crash-loop on an unparsable directive." >&2
    exit 2
fi
LOGFILTER_SETTLE_SECS="${LOGFILTER_SETTLE_SECS:-90}"
LOGFILTER_GUARD_TRIES="${LOGFILTER_GUARD_TRIES:-8}"
LOGFILTER_GUARD_SECS="${LOGFILTER_GUARD_SECS:-10}"
case "${LOGFILTER_GUARD_TRIES}:${LOGFILTER_GUARD_SECS}" in
    *[!0123456789:]*|:*|*:|0:*|00*:*) echo "❌ LOGFILTER_GUARD_TRIES must be a whole number of calls (1 or more) and LOGFILTER_GUARD_SECS whole seconds" >&2; exit 2 ;;
esac
case "${LOGFILTER_SETTLE_SECS}" in
    ""|*[!0123456789]*) echo "❌ LOGFILTER_SETTLE_SECS must be whole seconds" >&2; exit 2 ;;
esac
case "${TN_NODE_SCRIPTS_DIR:-}" in
    /*) case "${TN_NODE_SCRIPTS_DIR}" in *"'"*) echo "❌ TN_NODE_SCRIPTS_DIR holds a quote" >&2; exit 2 ;; esac ;;
    *) echo "❌ TN_NODE_SCRIPTS_DIR (config.sh) must be an absolute path" >&2; exit 2 ;;
esac

# Resolve the targets first: an unknown one stops the run (exit 2) before anything else.
if ! SELECTION="$(tn_select_indices "$@")"; then exit 2; fi
SELECTED=" $(printf '%s ' ${SELECTION}) "
# Observers first, then validators, each group in index order.
ORDER=()
for _role in observer validator; do
    for _i in "${!INSTANCE_NAMES[@]}"; do
        case "${SELECTED}" in *" ${_i} "*) ;; *) continue ;; esac
        if [ "${_role}" = observer ]; then
            if [ "${NODE_ROLES[$_i]}" = observer ]; then ORDER+=("${_i}"); fi
        elif [ "${NODE_ROLES[$_i]}" != observer ]; then
            ORDER+=("${_i}")
        fi
    done
done
unset _i _role
if [ "${#ORDER[@]}" -eq 0 ]; then
    echo "❌ no target nodes (INSTANCE_NAMES is empty?)" >&2
    exit 2
fi

# --- the two remote session scripts ------------------------------------------------------

# lf_script_head <header> <instance> — the lines both sessions start with: the header the node
# never reads (a log and test anchor), strict mode, the v2 lib, the values (expanded and
# single-quoted here), the helpers. Quoted heredoc: nothing in the helpers expands locally.
lf_script_head() {
    printf '%s\n' "$1"
    printf '%s\n' "set -euo pipefail"
    printf "[ -r '%s/lib/common.sh' ] || { echo 'LOGFILTER_FAIL %s reason=precheck_lib'; exit 1; }\n" \
        "${TN_NODE_SCRIPTS_DIR}" "$2"
    printf ". '%s/lib/common.sh'\n" "${TN_NODE_SCRIPTS_DIR}"
    printf "I='%s'\n" "$2"
    printf "F='%s'\n" "${LF_FILTER}"
    printf 'S=%s\n' "${LF_START_SCRIPT}"
    cat <<'LF_HELPERS'
fail() { echo "LOGFILTER_FAIL ${I} reason=$*"; exit 1; }
declare -F tn_launch_flag_get tn_launch_flag_set tn_launch_flag_unset tn_committee_down_guard \
    tn_wait_restart_window tn_epoch_secs_left >/dev/null || fail precheck_lib
# lf_live <docker .Args> - rc 0 when the running container's arguments carry --log.file.filter F.
lf_live() {
    local a="${1#\[}"
    a="${a%\]}"
    case " ${a} " in *" --log.file.filter ${F} "*) return 0 ;; esac
    return 1
}
# lf_log - the host path of the node's JSON file log: the --log.file.directory of the start
# script, mapped through the running container's bind mounts (longest destination prefix),
# plus the telcoin-network-logs/reth.log the node writes below it.
lf_log() {
    local d dst src best="" host=""
    d="$(tn_launch_flag_get "${S}" --log.file.directory 2>/dev/null)" || return 1
    case "${d}" in /*) ;; *) return 1 ;; esac
    d="${d%/}"
    while read -r dst src; do
        [ -n "${dst}" ] && [ -n "${src}" ] || continue
        case "${d}/" in
            "${dst%/}"/*)
                if [ "${#dst}" -gt "${#best}" ]; then best="${dst}"; host="${src%/}${d#"${dst%/}"}"; fi ;;
        esac
    done < <(docker inspect telcoin --format '{{range .Mounts}}{{.Destination}} {{.Source}}{{"\n"}}{{end}}' 2>/dev/null || true)
    [ -n "${host}" ] || return 1
    printf '%s/telcoin-network-logs/reth.log\n' "${host}"
}
LF_HELPERS
}

# lf_apply_script <instance> — session 1 (see the header).
lf_apply_script() {
    lf_script_head "# logfilter: apply" "$1"
    if [ "${LF_SKIP_EPOCH_WAIT}" -eq 1 ]; then
        echo "export TN_SKIP_EPOCH_WAIT=1"
    else
        echo "unset TN_SKIP_EPOCH_WAIT"
    fi
    echo "unset TN_ALLOW_QUORUM_RISK"
    cat <<'LF_PRECHECK'
[ "$(systemctl is-active telcoin 2>/dev/null || true)" = active ] || fail precheck_active
[ -r "${S}" ] || fail precheck_start_script
fmt="$(tn_launch_flag_get "${S}" --log.file.format 2>/dev/null)" || fmt=""
[ "${fmt}" = json ] || fail precheck_json_format
LF_PRECHECK
    if [ "${LF_NO_RESTART}" -eq 0 ]; then
        echo 'lf_log >/dev/null || fail precheck_log_path'
    fi
    cat <<'LF_SET'
wrc=0
was="$(tn_launch_flag_get "${S}" --log.file.filter 2>/dev/null)" || wrc=$?
case "${wrc}" in
    0) [ -n "${was}" ] || was="(boolean)" ;;
    1) was="-" ;;
    *) fail "precheck_flag_read rc=${wrc}" ;;
esac
B=none
if [ "${was}" != "${F}" ]; then
    B="${S}.bak-logfilter-$(date -u +%Y%m%dT%H%M%SZ)"
    cp -p "${S}" "${B}" || fail backup
fi
rc=0
LF_SET
    printf "tn_launch_flag_set \"\${S}\" --log.file.filter '%s' || rc=\$?\n" "${LF_FILTER}"
    cat <<'LF_SET'
if [ "${rc}" != 0 ] && [ "${B}" != none ]; then rm -f "${B}"; B=none; fi
case "${rc}" in
    0|1) echo "LOGFILTER_SET ${I} flag=--log.file.filter value=${F} rc=${rc} was=${was} backup=${B}" ;;
    *) fail "flag_set rc=${rc}" ;;
esac
a="$(docker inspect telcoin --format '{{.Args}}' 2>/dev/null)" || a=""
if lf_live "${a}"; then echo "LOGFILTER_OK ${I} restarted=no"; exit 0; fi
LF_SET
    if [ "${LF_NO_RESTART}" -eq 1 ]; then
        echo 'echo "LOGFILTER_OK ${I} restarted=no level_check=skipped"'
        echo 'exit 0'
        return 0
    fi
    printf 'GT=%s\nGS=%s\n' "${LOGFILTER_GUARD_TRIES}" "${LOGFILTER_GUARD_SECS}"
    cat <<'LF_GUARD'
# lf_gs - the guard's progress function: its messages on stderr; a warning means the guard could
# not count the committee (or was overridden) and went ahead anyway, which this script refuses.
lf_gs() { printf '%s\n' "$2" >&2; if [ "$1" = warn ]; then LF_BLIND=1; fi; return 0; }
# lf_guard - v2's committee guard, called up to GT times GS s apart: one commit's authors can miss a
# member that is up, so a refusal is resampled and the node deferred only when every call refused.
# A pass that came with a warning defers the node at once.
lf_guard() {
    local g t=1
    while :; do
        g=0
        LF_BLIND=0
        tn_committee_down_guard "" lf_gs || g=$?
        if [ "${g}" = 0 ]; then
            if [ "${LF_BLIND}" != 0 ]; then echo "LOGFILTER_DEFERRED ${I} reason=guard_blind"; exit 0; fi
            return 0
        fi
        if [ "${t}" -ge "${GT}" ]; then
            echo "guard try ${t}/${GT} refused — deferring" >&2
            echo "LOGFILTER_DEFERRED ${I} reason=guard"
            exit 0
        fi
        echo "guard try ${t}/${GT} refused — resampling in ${GS} s" >&2
        sleep "${GS}"
        t=$((t + 1))
    done
}
lf_guard
LF_GUARD
    if [ "${LF_SKIP_EPOCH_WAIT}" -eq 1 ]; then
        echo 'echo "LOGFILTER_WAIT ${I} secs=0"'
    else
        cat <<'LF_WAIT'
w="$(tn_epoch_secs_left 2>/dev/null)" || w=""
w="${w%% *}"
echo "LOGFILTER_WAIT ${I} secs=${w:-unknown}"
LF_WAIT
    fi
    cat <<'LF_RESTART'
tn_wait_restart_window || true
lf_guard
r=0
systemctl restart telcoin || r=$?
[ "${r}" = 0 ] || fail "restart rc=${r}"
echo "LOGFILTER_RESTART ${I} at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LF_RESTART
}

# lf_verify_script <instance> — session 2, after wait_healthy. Lines written before the restarted
# container started (the old process's DEBUG lines, still in the tail when the new one has written
# fewer than 300) do not count: only lines whose "timestamp" second is after its StartedAt second.
lf_verify_script() {
    lf_script_head "# logfilter: verify" "$1"
    cat <<'LF_VERIFY'
a="$(docker inspect telcoin --format '{{.Args}}' 2>/dev/null)" || a=""
fl=no
if lf_live "${a}"; then fl=yes; fi
L="$(lf_log)" || fail log_path
[ -r "${L}" ] || fail "no_log path=${L}"
t0="$(docker inspect telcoin --format '{{.State.StartedAt}}' 2>/dev/null)" || t0=""
case "${t0}" in [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T*) ;; *) fail started_at ;; esac
c="$(tail -n 300 "${L}" | awk -v t0="${t0}" '
    BEGIN { t0 = substr(t0, 1, 19); n = 0; d = 0 }
    match($0, /"timestamp":"[^"]*"/) {
        if (substr($0, RSTART + 13, 19) > t0) { n++; if (index($0, "\"level\":\"DEBUG\"")) d++ }
    }
    END { printf "%d %d\n", d, n }')" || fail log_read
echo "LOGFILTER_VERIFY ${I} flag=${fl} debug_lines=${c% *} lines=${c#* }"
LF_VERIFY
}

# --- the driver ------------------------------------------------------------------------------

# lf_field <marker-line> <key> — one key=value field's value ("" when absent).
lf_field() { printf '%s\n' "$1" | tr ' ' '\n' | sed -n "s/^$2=//p" | head -n 1; }

# lf_show <session-stdout> — echo what a session printed: marker lines as they are, anything
# else indented.
lf_show() {
    local line
    while IFS= read -r line; do
        case "${line}" in
            "") ;;
            LOGFILTER_*) printf '%s\n' "${line}" ;;
            *) printf '    | %s\n' "${line}" ;;
        esac
    done <<< "$1"
}

# lf_rollback_hint <instance> <session-1 stdout> — what to do after a failure. Only a node whose
# start script this run changed (a LOGFILTER_SET … rc=0 line) gets a rollback, built from that
# line: the value the flag had before (was=) and the copy of the file as it was (backup=).
lf_rollback_hint() {
    local inst="$1" set0 was b lib="${TN_NODE_SCRIPTS_DIR}/lib/common.sh"
    set0="$(printf '%s\n' "$2" | grep "^LOGFILTER_SET ${inst} .* rc=0 " | head -n 1)" || set0=""
    if [ -z "${set0}" ]; then
        if printf '%s\n' "$2" | grep -q "^LOGFILTER_SET ${inst} "; then
            echo "    nothing changed in ${LF_START_SCRIPT} on ${inst} by this run (it already read --log.file.filter ${LF_FILTER})"
        else
            echo "    nothing changed on ${inst}"
        fi
        return 0
    fi
    was="$(lf_field "${set0}" was)"
    b="$(lf_field "${set0}" backup)"
    echo "    rollback on ${inst} (this run changed ${LF_START_SCRIPT}; --log.file.filter was ${was}):"
    case "${was}" in
        -) echo "      sudo bash -c '. ${lib}; tn_launch_flag_unset ${LF_START_SCRIPT} --log.file.filter'" ;;
        "(boolean)"|"") ;;
        *) echo "      sudo bash -c '. ${lib}; tn_launch_flag_set ${LF_START_SCRIPT} --log.file.filter ${was}'" ;;
    esac
    case "${b}" in
        ""|none) ;;
        *) echo "      or restore the copy taken first: sudo cp -p ${b} ${LF_START_SCRIPT}" ;;
    esac
    echo "      then: sudo systemctl restart telcoin (a plain restart bypasses the committee guard: on a"
    echo "      committee member, check that every other member is up and voting first)"
}

# lf_resume_cmd <first-position> — the command that resumes the sweep with ORDER[first..].
lf_resume_cmd() {
    local cmd="./devnet-log-filter.sh --yes" p
    [ "${LF_FILTER_GIVEN}" -eq 1 ] && cmd+=" --filter '${LF_FILTER}'"
    [ "${LF_SKIP_EPOCH_WAIT}" -eq 1 ] && cmd+=" --skip-epoch-wait"
    [ "${LF_NO_RESTART}" -eq 1 ] && cmd+=" --no-restart"
    for p in "${!ORDER[@]}"; do
        [ "${p}" -ge "$1" ] && cmd+=" ${INSTANCE_NAMES[${ORDER[$p]}]}"
    done
    printf '%s\n' "${cmd}"
}

# lf_stop <position> — the sweep stops at ORDER[position] (deferred or failed): say so, and how
# to resume with it and every node after it.
lf_stop() {
    local inst="${INSTANCE_NAMES[${ORDER[$1]}]}"
    stopped="${inst} (${st})"
    echo "    ❌ stopping the sweep at ${inst} (${st}): the nodes after it are untouched."
    echo "    resume: $(lf_resume_cmd "$1")"
}

# lf_restart_began <session-1 stdout> <instance> — rc 0 when the session got as far as the
# restart path (a LOGFILTER_WAIT or LOGFILTER_RESTART line). With a LOGFILTER_OK restarted=no or a
# precheck_active failure after it, devnet-lib re-sent the session after a transport drop, and the
# earlier attempt restarted the node (or was restarting it).
lf_restart_began() { printf '%s\n' "$1" | grep -Eq "^LOGFILTER_(WAIT|RESTART) $2 "; }

# lf_node <index> <position 1..n> — one node, both sessions. Sets st (ok|deferred|fail) and
# restarted (0|1), adds an ok node to ok_nodes; always rc 0.
lf_node() {
    local i="$1" k="$2" inst zone out out1 ssh_rc last fl dl nl
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    st=fail
    restarted=0
    echo ""
    echo ">>> [${k}/${#ORDER[@]}] ${inst} (${zone}, ${NODE_ROLES[$i]}): --log.file.filter ${LF_FILTER}"
    if [ "${NODE_ROLES[$i]}" = validator ] && [ "${LF_NO_RESTART}" -eq 0 ] && [ "${LF_SKIP_EPOCH_WAIT}" -eq 0 ]; then
        echo "    this session may wait up to 1800 s for the epoch boundary (v2's TN_EPOCH_WAIT_MAX default);"
        echo "    the node's progress shows on stderr, its marker lines when the session ends"
    fi

    ssh_rc=0
    out1="$(lf_apply_script "${inst}" | tn_iap_ssh_stdin "${inst}" "${zone}")" || ssh_rc=$?
    out1="$(printf '%s\n' "${out1}" | tr -d '\r')"
    lf_show "${out1}"
    last="$(printf '%s\n' "${out1}" | grep '^LOGFILTER_' | tail -n 1)" || last=""
    case "${last}" in
        "LOGFILTER_OK ${inst} restarted=no"|"LOGFILTER_FAIL ${inst} reason=precheck_active")
            if ! lf_restart_began "${out1}" "${inst}"; then
                case "${last}" in
                    LOGFILTER_OK*) st=ok; ok_nodes+=("${inst}") ;;
                    *) lf_rollback_hint "${inst}" "${out1}" ;;
                esac
                return 0
            fi
            echo "    the session was re-sent after its restart path began: checking ${inst} as restarted" ;;
        "LOGFILTER_OK ${inst} "*)
            st=ok; ok_nodes+=("${inst}"); return 0 ;;
        "LOGFILTER_DEFERRED ${inst} reason=guard_blind")
            st=deferred
            echo "    ⚠️  the committee guard could not count the committee (its warning is above, on stderr), so"
            echo "       ${inst} was not restarted: --log.file.filter is in its start script but not live."
            echo "       Run the resume command below once the node's RPC and the chain answer again."
            return 0 ;;
        "LOGFILTER_DEFERRED ${inst} "*)
            st=deferred
            echo "    ⚠️  the committee guard refused to restart ${inst}: --log.file.filter is in its start script but not live."
            echo "       Run the resume command below once every committee member is up and voting."
            return 0 ;;
        "LOGFILTER_FAIL ${inst} "*)
            lf_rollback_hint "${inst}" "${out1}"; return 0 ;;
        "LOGFILTER_RESTART ${inst} "*) ;;
        *)
            echo "LOGFILTER_FAIL ${inst} reason=no_outcome ssh_rc=${ssh_rc}"
            lf_rollback_hint "${inst}" "${out1}"; return 0 ;;
    esac
    restarted=1

    if ! wait_healthy "${inst}" "${zone}" telcoin; then
        echo "LOGFILTER_FAIL ${inst} reason=not_healthy"
        lf_rollback_hint "${inst}" "${out1}"; return 0
    fi

    ssh_rc=0
    out="$(lf_verify_script "${inst}" | tn_iap_ssh_stdin "${inst}" "${zone}")" || ssh_rc=$?
    out="$(printf '%s\n' "${out}" | tr -d '\r')"
    lf_show "${out}"
    last="$(printf '%s\n' "${out}" | grep '^LOGFILTER_' | tail -n 1)" || last=""
    case "${last}" in
        "LOGFILTER_VERIFY ${inst} "*) ;;
        "LOGFILTER_FAIL ${inst} "*)
            lf_rollback_hint "${inst}" "${out1}"; return 0 ;;
        *)
            echo "LOGFILTER_FAIL ${inst} reason=verify_no_answer ssh_rc=${ssh_rc}"
            lf_rollback_hint "${inst}" "${out1}"; return 0 ;;
    esac
    fl="$(lf_field "${last}" flag)"
    dl="$(lf_field "${last}" debug_lines)"
    nl="$(lf_field "${last}" lines)"
    case "${dl}:${nl}" in
        *[!0123456789:]*|:*|*:)
            echo "LOGFILTER_FAIL ${inst} reason=verify_unreadable"
            lf_rollback_hint "${inst}" "${out1}"; return 0 ;;
    esac
    if [ "${fl}" != yes ]; then
        echo "LOGFILTER_FAIL ${inst} reason=flag_not_live"
    elif [ "${nl}" -eq 0 ]; then
        echo "LOGFILTER_FAIL ${inst} reason=no_new_log_lines"
    elif [ "${dl}" -ne 0 ]; then
        echo "LOGFILTER_FAIL ${inst} reason=debug_lines debug_lines=${dl} lines=${nl}"
    else
        echo "LOGFILTER_OK ${inst} restarted=yes level_check=ok"
        st=ok; ok_nodes+=("${inst}"); return 0
    fi
    lf_rollback_hint "${inst}" "${out1}"
    return 0
}

echo "=========================================="
echo "devnet node file-log level (--log.file.filter)"
echo "Project:    ${PROJECT_ID}"
echo "Filter:     --log.file.filter ${LF_FILTER}"
if [ "${LF_NO_RESTART}" -eq 1 ]; then
    echo "Restart:    none (--no-restart): the level is live from each node's next restart"
else
    echo "Restart:    one node at a time when the flag is not live yet, behind v2's committee guard"
fi
if [ "${LF_SKIP_EPOCH_WAIT}" -eq 1 ]; then
    echo "Epoch wait: skipped (--skip-epoch-wait: TN_SKIP_EPOCH_WAIT=1 inside each node's session)"
else
    echo "Epoch wait: v2 policy (tn_wait_restart_window) before each restart"
fi
echo "Settle:     ${LOGFILTER_SETTLE_SECS}s after each node that was restarted"
echo "Guard:      up to ${LOGFILTER_GUARD_TRIES} samples, ${LOGFILTER_GUARD_SECS} s apart (deferred only when every sample refuses; a blind pass defers at once)"
echo "Mode:       $([ "${LF_APPLY}" -eq 1 ] && echo apply || echo "dry run (no ssh; --yes applies)")"
echo "=========================================="
echo "plan (observers first, then validators, each in index order):"
_k=0
for _i in "${ORDER[@]}"; do
    _k=$((_k + 1))
    echo "  ${_k}. ${INSTANCE_NAMES[$_i]} (${ZONES[$_i]}, ${NODE_ROLES[$_i]}): flag=--log.file.filter value=${LF_FILTER}" \
        "restart=$([ "${LF_NO_RESTART}" -eq 1 ] && echo no || echo yes)" \
        "epoch_wait=$([ "${LF_SKIP_EPOCH_WAIT}" -eq 1 ] && echo skipped || echo v2)"
done
unset _i _k

if [ "${LF_APPLY}" -ne 1 ]; then
    echo ""
    echo "dry run: nothing touched, no ssh opened. Apply: $(lf_resume_cmd 0)"
    exit 0
fi

ok_nodes=()
st=fail
restarted=0
stopped=""
for k in "${!ORDER[@]}"; do
    lf_node "${ORDER[$k]}" "$((k + 1))" || st=fail
    [ "${st}" = ok ] || { lf_stop "${k}"; break; }
    if [ "${restarted}" -eq 1 ] && [ "$((k + 1))" -lt "${#ORDER[@]}" ] && [ "${LOGFILTER_SETTLE_SECS}" -gt 0 ]; then
        echo "    settling ${LOGFILTER_SETTLE_SECS}s after the restart, before the next node"
        sleep "${LOGFILTER_SETTLE_SECS}"
    fi
done

echo ""
echo "=========================================="
echo "ok:      ${#ok_nodes[@]}/${#ORDER[@]} ${ok_nodes[*]+"${ok_nodes[*]}"}"
[ -n "${stopped}" ] && echo "stopped: ${stopped}"
echo "Re-run after any devnet-finalize.sh or devnet-update.sh --finalize / --wipe (they re-render the launch line)."
echo "=========================================="
if [ "${#ok_nodes[@]}" -eq "${#ORDER[@]}" ]; then exit 0; fi
exit 1
