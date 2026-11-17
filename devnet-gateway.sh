#!/usr/bin/env bash
#
# devnet-gateway.sh — the devnet's worker gateways (deploy step 13), the public RPC edge of the
# `rpc` host (deploy step 15), and a read-only look at the gateways. It drives tn-node-deployment's
# setup-gateway.sh, firewall-setup.sh, edit-config.sh and install-caddy.sh (under
# TN_NODE_SCRIPTS_DIR on each host) over the lib transport (IAP by default, the WireGuard overlay
# with TN_SSH_TRANSPORT=overlay). Interface: tasks/l2-contract.md §10.
#
# Usage:
#   ./devnet-gateway.sh [target ...]            dry run: print each remote command, touch no host
#   ./devnet-gateway.sh --yes [target ...]      install the gateways (step 13; nodes may be stopped)
#   ./devnet-gateway.sh --status [target ...]   read-only: each gateway's state, one line per host
#   ./devnet-gateway.sh --rpc-edge              dry run of the public RPC edge
#   ./devnet-gateway.sh --rpc-edge --yes        the public RPC edge on each `rpc` host (step 15)
#
#   target  an index (0-based), INSTANCE_NAME or NODE_NAME of a node that has a gateway
#           (GATEWAY_MODES same-host or standalone), or of a `gateway` entry, which stands for the
#           node it fronts. None = every node with a gateway. Nodes are visited in array order,
#           whatever order they are named in. --rpc-edge takes no target.
#
# --yes, per node in array order:
#   same-host   on the node host:
#                 sudo bash <scripts>/setup-gateway.sh --enable --yes --json --mode same-host
#                   --network devnet --image 'GATEWAY_IMAGE' --domain <tn_public_domain>
#                   --front caddy --redirect-queries 'GATEWAY_REDIRECT_URL'
#   standalone  on the validator, first the firewall rule, then the upstream bind:
#                 sudo bash <scripts>/firewall-setup.sh --json --enable --gateway-from <gateway IP>
#                 sudo bash <scripts>/edit-config.sh --json --set gateway_upstream=<gateway IP>
#               then on the gateway host (tn_gateway_host_index):
#                 sudo bash <scripts>/setup-gateway.sh --enable --yes --json --mode standalone
#                   --network devnet --image '…' --domain <tn_public_domain> --front caddy
#                   --upstream <validator IP> --rpc-port NODE_RPC_PORT
#                   --health-port DEFAULT_HEALTHCHECK_TCP_PORT --redirect-queries '…'
#               (both IPs are internal, read with tn_internal_ip before the first change; the
#               edit-config call opens a fresh ssh session, so it also proves the firewall
#               call left SSH reachable)
# A host step succeeds when ssh returns 0 AND the script's done line says "ok":true. The first
# failure stops the sweep: the steps after it are listed (`not run on …` for a host already
# visited, `UNTOUCHED <instance>` for the others) and the run exits 1. Each gateway install
# prints one line from its done line (`?` for a field the line lacks):
#   GATEWAY <instance> mode=<mode> applied=<items|none> installed=<b> active=<b> health=<b> ready=<b>
# Readiness is reported, never asserted: at step 13 the nodes are stopped (ready=false).
#
# Re-running --yes is safe. setup-gateway.sh --enable with the same inputs changes nothing
# (applied=none). firewall-setup.sh --enable re-applies the same rules (the source list persists
# in .node-meta GATEWAY_ALLOW_FROM). edit-config.sh --set gateway_upstream with the address the
# node already has changes nothing and restarts nothing; a NEW address (the gateway VM was
# recreated) edits the launch flags and gives a running validator edit-config's guarded restart,
# while a stopped validator stays stopped. A host that failed is simply visited again.
#
# --rpc-edge --yes, first a read-only `systemctl is-active <unit>` on every `rpc` host: unless
# each says `active`, exit 1 with nothing sent (rpc-enable restarts the node, which would start
# a stopped one outside the coordinated start of deploy step 14). Then, per `rpc` host:
#   sudo bash <scripts>/install-caddy.sh --json --phase rpc-enable --rpc-domain RPC_HOSTNAME --yes
# (the tn-rpc Caddy block plus the https/wss advertisement; it restarts the node ONCE, so it runs
# after devnet-finalize.sh --start-all), then the read-only
#   sudo bash <scripts>/install-caddy.sh --json --phase rpc-status
# must say "enabled":true and "domain":RPC_HOSTNAME. One line per host:
#   RPC-EDGE <instance> domain=<d> enabled=<b> advertised_http=<url> advertised_ws=<url>
# A re-run writes the same block; install-caddy.sh skips the node restart when node-info already
# advertises the wanted URLs.
#
# --status: sudo bash <scripts>/setup-gateway.sh --status --json on the gateway host of each target
# (read-only; one retry when ssh returns 255), the GATEWAY line for each, and exit 1 when any
# gateway is not installed, not active or could not be read. Every host is read.
#
# Every remote command runs with stdin from /dev/null. Remote stdout (the JSON events) and stderr
# go to logs/<stamp>-gateway/<instance>.log. A dry run writes no log and makes no gcloud call: an
# internal IP shows as <internal-ip:INSTANCE>.
#
# Refused with exit 2 before any gcloud or ssh call: an unknown option; --status with --rpc-edge
# or with --yes; --rpc-edge with a target; tn_fleet_check failing; a target that is not a fleet
# entry or has no gateway; no node with a gateway (no `rpc` host for --rpc-edge); for the
# installs, dry or not, a GATEWAY_IMAGE that still holds a placeholder or is not
# <repo>@sha256:<64 hex>, and a redirect URL, domain, port or scripts path the remote scripts
# would refuse.
#
# Exit: 0 ok; 1 a host failed (or an internal IP could not be read: then nothing was changed);
# 2 usage or config.

set -euo pipefail

GW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${GW_DIR}/devnet-lib.sh"

GW_NETWORK="devnet"
GW_SCRIPTS="${TN_NODE_SCRIPTS_DIR:-}"
GW_RO_RETRY_SECS="${GW_RO_RETRY_SECS:-5}"
# The rules of setup-gateway.sh (SG_IMAGE_RE, the --redirect-queries check), so a value the
# host would refuse stops the run here, before the first host.
GW_IMAGE_RE='^[a-z0-9]([a-z0-9._-]*[a-z0-9])?(:[0-9]{1,5})?(/[a-z0-9]([a-z0-9._-]*[a-z0-9])?)*@sha256:[0-9a-f]{64}$'
GW_URL_RE='^https?://[A-Za-z0-9.-]+(:[0-9]+)?(/[A-Za-z0-9._~/-]*)?$'
GW_DOMAIN_RE='^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$'
GW_IPV4_RE='^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$'

_gw_usage() {
    cat >&2 <<'EOF'
usage: ./devnet-gateway.sh [--yes] [target ...]     gateway installs (no --yes: dry run)
       ./devnet-gateway.sh --status [target ...]    read-only state of each gateway
       ./devnet-gateway.sh --rpc-edge [--yes]       public RPC edge on each rpc host (no --yes: dry run)
  target  an index (0-based), INSTANCE_NAME or NODE_NAME of a node with a gateway, or of a
          gateway entry (= the node it fronts); none = every node with a gateway
Exit: 0 ok, 1 a host failed, 2 usage or config. Details: the header of this script.
EOF
}
_gw_usage_error() { echo "❌ $*" >&2; _gw_usage; exit 2; }
_gw_config_error() { echo "❌ $*" >&2; exit 2; }

# --- arguments --------------------------------------------------------------------------------
GW_YES=0
GW_STATUS=0
GW_RPC_EDGE=0
GW_TARGETS=()
for _a in "$@"; do
    case "${_a}" in
        --yes) GW_YES=1 ;;
        --status) GW_STATUS=1 ;;
        --rpc-edge) GW_RPC_EDGE=1 ;;
        -h|--help) _gw_usage; exit 0 ;;
        -*) _gw_usage_error "unknown option: ${_a}" ;;
        *) GW_TARGETS+=("${_a}") ;;
    esac
done
unset _a
if [ "${GW_STATUS}" -eq 1 ] && [ "${GW_RPC_EDGE}" -eq 1 ]; then
    _gw_usage_error "--status and --rpc-edge are separate invocations"
fi
if [ "${GW_STATUS}" -eq 1 ] && [ "${GW_YES}" -eq 1 ]; then
    _gw_usage_error "--status is read-only and takes no --yes"
fi
if [ "${GW_RPC_EDGE}" -eq 1 ] && [ "${#GW_TARGETS[@]}" -gt 0 ]; then
    _gw_usage_error "--rpc-edge takes no target (it visits every rpc host); gateway targets are a separate invocation"
fi

if ! tn_fleet_check; then
    _gw_config_error "the fleet arrays in config.sh are inconsistent (see above)"
fi
case "${GW_SCRIPTS}" in
    /*) ;;
    *) _gw_config_error "TN_NODE_SCRIPTS_DIR must be an absolute path (got '${GW_SCRIPTS}')" ;;
esac
case "${GW_SCRIPTS}" in
    *[!A-Za-z0-9/._-]*) _gw_config_error "TN_NODE_SCRIPTS_DIR holds a character the remote command line cannot carry bare: '${GW_SCRIPTS}'" ;;
esac

# --- targets ----------------------------------------------------------------------------------
# _gw_node_for <i> — the node index fleet entry i stands for: i itself for a node, the node whose
# gateway runs on entry i for a `gateway` entry. rc 1, no output, when there is none.
_gw_node_for() {
    local k
    if tn_is_node_index "$1"; then
        printf '%s\n' "$1"
        return 0
    fi
    [ "${NODE_ROLES[$1]}" = "gateway" ] || return 1
    for k in $(tn_node_indices); do
        if [ "$(tn_gateway_host_index "${k}" 2>/dev/null || true)" = "$1" ]; then
            printf '%s\n' "${k}"
            return 0
        fi
    done
    return 1
}

# _gw_select [target ...] — prints, one per line in array order, the node indices with a gateway
# that the targets name (all of them with no target). rc 1 with a message for a target that is
# not a fleet entry or whose node has no gateway.
_gw_select() {
    local arg i k matched want=" "
    for arg in "$@"; do
        matched=""
        for i in "${!INSTANCE_NAMES[@]}"; do
            if [ "${arg}" = "${i}" ] || [ "${arg}" = "${INSTANCE_NAMES[$i]}" ] || [ "${arg}" = "${NODE_NAMES[$i]}" ]; then
                matched="${i}"
                break
            fi
        done
        if [ -z "${matched}" ]; then
            echo "❌ unknown target: ${arg} (expected an index, INSTANCE_NAME or NODE_NAME)" >&2
            return 1
        fi
        if ! k="$(_gw_node_for "${matched}")" || ! tn_gateway_host_index "${k}" >/dev/null; then
            echo "❌ target ${arg}: ${INSTANCE_NAMES[$matched]} (role ${NODE_ROLES[$matched]}, gateway mode $(tn_gateway_mode "${matched}")) has no worker gateway" >&2
            return 1
        fi
        want="${want}${k} "
    done
    for k in $(tn_node_indices); do
        tn_gateway_host_index "${k}" >/dev/null || continue
        if [ "$#" -eq 0 ]; then
            printf '%s\n' "${k}"
            continue
        fi
        case "${want}" in *" ${k} "*) printf '%s\n' "${k}" ;; esac
    done
}

# --- JSON fields of a done line ---------------------------------------------------------------
# _gw_val <json> <key> — the field as text: true, false, null, a number or the string; ? when absent.
_gw_val() {
    local v
    v="$(printf '%s' "$1" | sed -n -E "s/.*\"$2\":(true|false|null|[0-9]+)[,}].*/\1/p")"
    [ -n "${v}" ] || v="$(tn_json_str "$1" "$2")"
    printf '%s' "${v:-?}"
}
# _gw_applied <json> — the "applied" items without quotes, comma separated; none for []; ? when absent.
_gw_applied() {
    local v
    case "$1" in *'"applied":['*) ;; *) printf '?'; return 0 ;; esac
    v="$(printf '%s' "$1" | sed -n -E 's/.*"applied":\[([^]]*)\].*/\1/p' | tr -d '"')"
    printf '%s' "${v:-none}"
}
_gw_summary() {   # <instance> <done line>
    printf 'GATEWAY %s mode=%s applied=%s installed=%s active=%s health=%s ready=%s\n' "$1" \
        "$(_gw_val "$2" mode)" "$(_gw_applied "$2")" "$(_gw_val "$2" installed)" \
        "$(_gw_val "$2" active)" "$(_gw_val "$2" health)" "$(_gw_val "$2" ready)"
}

# --- remote calls -----------------------------------------------------------------------------
# _gw_ssh <index> <command> — one remote command on fleet entry <index>, stdin from /dev/null;
# stderr and the output go to the host's log, the output also to stdout. Returns ssh's rc.
_gw_ssh() {
    local inst="${INSTANCE_NAMES[$1]}" zone="${ZONES[$1]}" log out rc=0
    log="${GW_LOG_DIR}/${inst}.log"
    printf '### %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$2" >>"${log}"
    out="$(tn_iap_ssh "${inst}" "${zone}" "$2" </dev/null 2>>"${log}")" || rc=$?
    printf '%s\n### rc=%s\n' "${out}" "${rc}" >>"${log}"
    printf '%s\n' "${out}"
    return "${rc}"
}
# _gw_ssh_ro <index> <command> — _gw_ssh for a read-only probe: when ssh returns 255, wait
# GW_RO_RETRY_SECS and send it once more. Never used for a command that changes the host.
_gw_ssh_ro() {
    local out rc=0
    out="$(_gw_ssh "$1" "$2")" || rc=$?
    if [ "${rc}" -eq 255 ]; then
        echo "    … ssh rc 255 from ${INSTANCE_NAMES[$1]}; one retry in ${GW_RO_RETRY_SECS}s" >&2
        sleep "${GW_RO_RETRY_SECS}"
        rc=0
        out="$(_gw_ssh "$1" "$2")" || rc=$?
    fi
    printf '%s\n' "${out}"
    return "${rc}"
}

# _gw_ip <index> — entry <index>'s internal IP (tn_internal_ip); in a dry run the stand-in
# <internal-ip:INSTANCE>, with no gcloud call.
_gw_ip() {
    local ip
    if [ "${GW_YES}" -ne 1 ]; then
        printf '<internal-ip:%s>' "${INSTANCE_NAMES[$1]}"
        return 0
    fi
    ip="$(tn_internal_ip "$1")" || return 1
    if ! [[ "${ip}" =~ ${GW_IPV4_RE} ]]; then
        echo "❌ ${INSTANCE_NAMES[$1]}: the internal IP lookup returned '${ip}'" >&2
        return 1
    fi
    printf '%s' "${ip}"
}

# --- the plan: one entry per remote step, all built before the first change --------------------
P_HOST=()   # fleet index of the host the step runs on
P_WHAT=()   # what the step is
P_KIND=()   # gw: a gateway install (GATEWAY line); rpc: rpc-enable (then the rpc-status check); step
P_CMD=()    # the remote command
_gw_add() { P_HOST+=("$1"); P_WHAT+=("$2"); P_KIND+=("$3"); P_CMD+=("$4"); }

_gw_enable_cmd() {   # <mode> <domain> <extra flags, each with a leading space>
    printf "sudo bash %s/setup-gateway.sh --enable --yes --json --mode %s --network %s --image '%s' --domain %s --front caddy%s --redirect-queries '%s'" \
        "${GW_SCRIPTS}" "$1" "${GW_NETWORK}" "${GATEWAY_IMAGE}" "$2" "$3" "${GATEWAY_REDIRECT_URL}"
}
GW_RPC_STATUS_CMD="sudo bash ${GW_SCRIPTS}/install-caddy.sh --json --phase rpc-status"

# _gw_rpc_check <index> — rpc-status on an rpc host; prints the RPC-EDGE line; rc 0 when it says
# enabled with RPC_HOSTNAME.
_gw_rpc_check() {
    local out rc=0 st
    out="$(_gw_ssh_ro "$1" "${GW_RPC_STATUS_CMD}")" || rc=$?
    st="$(printf '%s\n' "${out}" | grep '"enabled"' | tail -1 || true)"
    printf 'RPC-EDGE %s domain=%s enabled=%s advertised_http=%s advertised_ws=%s\n' "${INSTANCE_NAMES[$1]}" \
        "$(_gw_val "${st}" domain)" "$(_gw_val "${st}" enabled)" \
        "$(_gw_val "${st}" advertised_http)" "$(_gw_val "${st}" advertised_ws)"
    if [ "${rc}" -ne 0 ] || ! tn_json_true "${st}" enabled || [ "$(tn_json_str "${st}" domain)" != "${RPC_HOSTNAME}" ]; then
        echo "    ❌ rpc-status on ${INSTANCE_NAMES[$1]} does not say enabled with ${RPC_HOSTNAME} (ssh rc ${rc})" >&2
        return 1
    fi
}

# _gw_not_run <first step not run> — after a failure: the steps left, as `not run on <host>` for
# a host a step already ran on, and `UNTOUCHED <host>` (once) for every other host.
_gw_not_run() {
    local s ran=" " told=" " inst
    for ((s = 0; s < $1; s++)); do ran="${ran}${P_HOST[$s]} "; done
    for ((s = $1; s < ${#P_CMD[@]}; s++)); do
        inst="${INSTANCE_NAMES[${P_HOST[$s]}]}"
        case "${ran}" in
            *" ${P_HOST[$s]} "*) echo "    not run on ${inst}: ${P_WHAT[$s]}" ;;
            *)
                case "${told}" in
                    *" ${P_HOST[$s]} "*) ;;
                    *) echo "UNTOUCHED ${inst}"; told="${told}${P_HOST[$s]} " ;;
                esac ;;
        esac
    done
}

# _gw_sweep — run the plan in order; rc 1 at the first step that fails (the rest is not run).
_gw_sweep() {
    local s inst out rc done_line
    for ((s = 0; s < ${#P_CMD[@]}; s++)); do
        inst="${INSTANCE_NAMES[${P_HOST[$s]}]}"
        echo ""
        echo ">>> [${inst}] ${P_WHAT[$s]}"
        echo "    ${P_CMD[$s]}"
        rc=0
        out="$(_gw_ssh "${P_HOST[$s]}" "${P_CMD[$s]}")" || rc=$?
        done_line="$(tn_json_done_line "${out}")"
        if [ "${rc}" -eq 0 ] && tn_json_true "${done_line}" ok; then
            echo "    ✓ ok: $(tn_json_str "${done_line}" msg)"
            if [ "${P_KIND[$s]}" = "gw" ]; then _gw_summary "${inst}" "${done_line}"; fi
            if [ "${P_KIND[$s]}" != "rpc" ] || _gw_rpc_check "${P_HOST[$s]}"; then continue; fi
        else
            if [ -n "${done_line}" ]; then
                echo "    ❌ failed on ${inst}: ssh rc ${rc}, done ok=$(_gw_val "${done_line}" ok): $(tn_json_str "${done_line}" msg)" >&2
            else
                echo "    ❌ failed on ${inst}: ssh rc ${rc}, no done line" >&2
            fi
            if [ "${P_KIND[$s]}" = "gw" ]; then _gw_summary "${inst}" "${done_line}"; fi
        fi
        echo "    log: ${GW_LOG_DIR}/${inst}.log" >&2
        _gw_not_run $((s + 1))
        return 1
    done
}

_gw_print_plan() {
    local s
    echo "DRY RUN (no --yes): nothing below runs; no host is touched and no gcloud call is made."
    for ((s = 0; s < ${#P_CMD[@]}; s++)); do
        echo ""
        echo ">>> [${INSTANCE_NAMES[${P_HOST[$s]}]}] ${P_WHAT[$s]}"
        echo "    ${P_CMD[$s]}"
        if [ "${P_KIND[$s]}" = "rpc" ]; then
            echo ">>> [${INSTANCE_NAMES[${P_HOST[$s]}]}] then assert rpc-status: enabled, domain ${RPC_HOSTNAME} (read-only)"
            echo "    ${GW_RPC_STATUS_CMD}"
        fi
    done
    echo ""
    echo "dry run: ${#P_CMD[@]} remote step(s); run again with --yes to apply."
}

_gw_check_port() {   # <name> <value>
    case "$2" in
        ''|*[!0-9]*) _gw_config_error "$1 must be a port number (got '$2')" ;;
    esac
    if [ "$2" -lt 1 ] || [ "$2" -gt 65535 ]; then _gw_config_error "$1 must be 1-65535 (got '$2')"; fi
}

# --- --rpc-edge ---------------------------------------------------------------------------------
if [ "${GW_RPC_EDGE}" -eq 1 ]; then
    if ! [[ "${RPC_HOSTNAME:-}" =~ ${GW_DOMAIN_RE} ]]; then
        _gw_config_error "RPC_HOSTNAME is not a lower-case host name: '${RPC_HOSTNAME:-}'"
    fi
    for _r in $(tn_indices_by_role rpc); do
        _gw_add "${_r}" "install-caddy.sh rpc-enable (public RPC edge; restarts the node once)" rpc \
            "sudo bash ${GW_SCRIPTS}/install-caddy.sh --json --phase rpc-enable --rpc-domain ${RPC_HOSTNAME} --yes"
    done
    unset _r
    if [ "${#P_CMD[@]}" -eq 0 ]; then _gw_config_error "no fleet entry has role rpc"; fi
    echo "=========================================="
    echo "devnet public RPC edge (install-caddy.sh rpc-enable)"
    echo "Project:    ${PROJECT_ID}"
    echo "Domain:     ${RPC_HOSTNAME}"
    echo "Note:       restarts each rpc node once: run after devnet-finalize.sh --start-all"
    echo "=========================================="
    if [ "${GW_YES}" -ne 1 ]; then _gw_print_plan; exit 0; fi
    GW_LOG_DIR="${GW_DIR}/logs/$(date +%Y%m%d_%H%M%S)-gateway"
    mkdir -p "${GW_LOG_DIR}"
    echo ">>> per-host logs: ${GW_LOG_DIR}"
    # rpc-enable restarts the node (`systemctl restart`), which STARTS a stopped unit: on a
    # stopped fleet it would start the rpc node alone, outside the coordinated start. Read the
    # unit's state first (read-only) and send nothing unless it is active on every rpc host.
    _gw_inactive=""
    for _r in $(tn_indices_by_role rpc); do
        _svc="$(tn_service_for_role "${NODE_ROLES[$_r]}")"
        _st="$(_gw_ssh_ro "${_r}" "systemctl is-active ${_svc} 2>/dev/null || true" | tr -d '\r' | sed '/^$/d' | tail -n 1)" || _st=""
        echo "    ${INSTANCE_NAMES[$_r]}: ${_svc} is ${_st:-unreadable}"
        [ "${_st}" = active ] || _gw_inactive="${_gw_inactive} ${INSTANCE_NAMES[$_r]} (${_st:-unreadable})"
    done
    if [ -n "${_gw_inactive}" ]; then
        echo "❌ the node unit is not active on:${_gw_inactive}. install-caddy.sh rpc-enable restarts the node and would start a stopped one by itself. The public RPC edge is installed after the coordinated start (deploy step 14, devnet-finalize.sh --start-all). Nothing was sent." >&2
        exit 1
    fi
    unset _r _svc _st _gw_inactive
    if ! _gw_sweep; then
        echo ""
        echo "public RPC edge FAILED — see the ❌ lines above." >&2
        exit 1
    fi
    echo ""
    echo "public RPC edge enabled on every rpc host."
    exit 0
fi

# --- gateway installs and --status: the nodes ------------------------------------------------------
if ! GW_SELECTION="$(_gw_select ${GW_TARGETS[@]+"${GW_TARGETS[@]}"})"; then exit 2; fi
GW_NODES=()
while IFS= read -r _idx; do
    if [ -n "${_idx}" ]; then GW_NODES+=("${_idx}"); fi
done <<< "${GW_SELECTION}"
unset _idx
if [ "${#GW_NODES[@]}" -eq 0 ]; then
    _gw_config_error "no node has a worker gateway (TN_GATEWAY_ENABLE=${TN_GATEWAY_ENABLE:-unset}, GATEWAY_MODES=(${GATEWAY_MODES[*]:-}))"
fi

# --- --status -------------------------------------------------------------------------------------
if [ "${GW_STATUS}" -eq 1 ]; then
    GW_LOG_DIR="${GW_DIR}/logs/$(date +%Y%m%d_%H%M%S)-gateway"
    mkdir -p "${GW_LOG_DIR}"
    echo "devnet worker gateways: status (read-only); per-host logs: ${GW_LOG_DIR}"
    bad=0
    for n in "${GW_NODES[@]}"; do
        h="$(tn_gateway_host_index "${n}")"
        rc=0
        out="$(_gw_ssh_ro "${h}" "sudo bash ${GW_SCRIPTS}/setup-gateway.sh --status --json")" || rc=$?
        done_line="$(tn_json_done_line "${out}")"
        _gw_summary "${INSTANCE_NAMES[$h]}" "${done_line}"
        if [ "${rc}" -ne 0 ] || ! tn_json_true "${done_line}" ok; then
            echo "    ❌ ${INSTANCE_NAMES[$h]}: status could not be read (ssh rc ${rc})" >&2
            bad=1
        elif ! tn_json_true "${done_line}" installed || ! tn_json_true "${done_line}" active; then
            echo "    ❌ ${INSTANCE_NAMES[$h]}: the gateway of ${NODE_NAMES[$n]} is not installed and active" >&2
            bad=1
        fi
    done
    exit "${bad}"
fi

# --- gateway installs: check the inputs, then build the whole plan -------------------------------
case "${GATEWAY_IMAGE:-}" in
    *PLACEHOLDER*) _gw_config_error "GATEWAY_IMAGE still holds a placeholder (${GATEWAY_IMAGE}): fill in the pushed digest in config.sh" ;;
esac
if ! [[ "${GATEWAY_IMAGE:-}" =~ ${GW_IMAGE_RE} ]]; then
    _gw_config_error "GATEWAY_IMAGE must be <repo>@sha256:<64 lowercase hex> (got '${GATEWAY_IMAGE:-}')"
fi
if ! [[ "${GATEWAY_REDIRECT_URL:-}" =~ ${GW_URL_RE} ]]; then
    _gw_config_error "GATEWAY_REDIRECT_URL is not a URL setup-gateway.sh accepts: '${GATEWAY_REDIRECT_URL:-}'"
fi
_gw_check_port NODE_RPC_PORT "${NODE_RPC_PORT:-}"
_gw_check_port DEFAULT_HEALTHCHECK_TCP_PORT "${DEFAULT_HEALTHCHECK_TCP_PORT:-}"
GW_DOMAINS=()
for n in "${GW_NODES[@]}"; do
    d="$(tn_public_domain "${n}")" || _gw_config_error "no public domain for ${INSTANCE_NAMES[$n]}"
    [[ "${d}" =~ ${GW_DOMAIN_RE} ]] || _gw_config_error "${INSTANCE_NAMES[$n]}: '${d}' is not a lower-case host name"
    GW_DOMAINS+=("${d}")
done

echo "=========================================="
echo "devnet worker gateways (setup-gateway.sh --enable)"
echo "Project:    ${PROJECT_ID}"
echo "Image:      ${GATEWAY_IMAGE}"
echo "Redirect:   ${GATEWAY_REDIRECT_URL} (every call but a submission)"
echo "Nodes:      $(for n in "${GW_NODES[@]}"; do printf '%s(%s) ' "${INSTANCE_NAMES[$n]}" "$(tn_gateway_mode "${n}")"; done)"
echo "Readiness:  reported, not asserted (the nodes may be stopped)"
echo "=========================================="
if [ "${GW_YES}" -ne 1 ]; then
    echo "Internal IPs are not looked up in a dry run: <internal-ip:INSTANCE> stands for the address"
    echo "--yes reads with tn_internal_ip before the first change."
fi

i=0
for n in "${GW_NODES[@]}"; do
    d="${GW_DOMAINS[$i]}"
    i=$((i + 1))
    h="$(tn_gateway_host_index "${n}")"
    case "$(tn_gateway_mode "${n}")" in
        same-host)
            _gw_add "${n}" "setup-gateway.sh --enable (same-host, ${d})" gw "$(_gw_enable_cmd same-host "${d}" "")" ;;
        standalone)
            if ! gip="$(_gw_ip "${h}")" || ! nip="$(_gw_ip "${n}")"; then
                echo "❌ could not read the internal IPs of ${INSTANCE_NAMES[$h]} and ${INSTANCE_NAMES[$n]}: nothing was changed" >&2
                exit 1
            fi
            _gw_add "${n}" "firewall-setup.sh --gateway-from ${gip} (for ${INSTANCE_NAMES[$h]})" step \
                "sudo bash ${GW_SCRIPTS}/firewall-setup.sh --json --enable --gateway-from ${gip}"
            _gw_add "${n}" "edit-config.sh gateway_upstream=${gip} (a stopped node stays stopped)" step \
                "sudo bash ${GW_SCRIPTS}/edit-config.sh --json --set gateway_upstream=${gip}"
            _gw_add "${h}" "setup-gateway.sh --enable (standalone, ${d}, upstream ${INSTANCE_NAMES[$n]})" gw \
                "$(_gw_enable_cmd standalone "${d}" " --upstream ${nip} --rpc-port ${NODE_RPC_PORT} --health-port ${DEFAULT_HEALTHCHECK_TCP_PORT}")" ;;
    esac
done

if [ "${GW_YES}" -ne 1 ]; then _gw_print_plan; exit 0; fi

GW_LOG_DIR="${GW_DIR}/logs/$(date +%Y%m%d_%H%M%S)-gateway"
mkdir -p "${GW_LOG_DIR}"
echo ">>> per-host logs: ${GW_LOG_DIR}"
if ! _gw_sweep; then
    echo ""
    echo "gateway installs FAILED — see the ❌ lines above; the run stopped there." >&2
    exit 1
fi
echo ""
echo "worker gateways installed (or already in place) for: $(for n in "${GW_NODES[@]}"; do printf '%s ' "${NODE_NAMES[$n]}"; done)"
exit 0
