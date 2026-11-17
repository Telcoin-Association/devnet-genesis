#!/usr/bin/env bash
#
# devnet-firewall.sh — the HOST firewall (ufw) of the fleet, by driving tn-node-deployment's
# firewall-setup.sh on each VM over the lib transport (IAP by default, the WireGuard overlay when
# TN_SSH_TRANSPORT=overlay). Companion to setup-firewall.sh (the VPC layer). Deploy step 11.
#
# Fleet (config.sh): seven entries. Node hosts: validator-1..4-devnet (validator),
# observer-5-devnet (observer), rpc-6-devnet (rpc). gateway-4-devnet (role gateway) runs the
# standalone worker gateway in front of node4 and has no node.
#
# Two modes:
#   --enable   lockout-safe ufw bring-up on EVERY fleet VM, one at a time:
#                validator, observer host:  sudo firewall-setup.sh --json --enable
#                rpc host:                  sudo firewall-setup.sh --json --enable --p2p-anywhere
#                gateway host:              sudo firewall-setup.sh --json --enable
#              firewall-setup.sh allows SSH (on a devnet node host also the overlay SSH range and
#              the health monitor) BEFORE `ufw --force enable` and opens P2P on a node host. After
#              each VM a fresh SSH connection must work, else exit 2 "SSH LOST" and no further VM
#              is touched.
#              80/443 are opened only where Caddy already serves a public edge, and at step 11 no
#              Caddy is installed yet. On the gateway host there is also no node and no gateway yet
#              (no .node-meta, no gateway.meta): firewall-setup.sh then knows no network and opens
#              SSH from anywhere and nothing else. Nothing has to be re-run for 80/443:
#              tn-node-deployment's install-caddy.sh opens them in ufw itself when it enables a
#              site (its caddy_open_ports: the gateway block at step 13, the public RPC site at
#              step 15, the dashboard at step 17), and a later `--enable` or `--reset` keeps them
#              because the Caddyfile then holds a managed block.
#   (default)  consensus ports on node hosts only, ufw already enabled: firewall-setup.sh --json
#              --port 49590/udp on and 49594/udp on (it cannot touch sshd), then --json --status
#              must show both ports.
#
# The load balancer is gone: TN_LB_HC_RANGES is no longer passed. HEALTHCHECK_MONITOR_SRC and
# TN_KUMA_SRC stay in the configuration, untouched; they do not travel over ssh, and
# firewall-setup.sh opens the health port on a devnet node host to its own default monitor source
# (the same address). The node's health listener binds loopback now (a standalone-fronted node binds
# it for its gateway, which has its own rule), so that rule admits nothing: dead weight, harmless.
#
# Targets: instance names (validator-2-devnet), fleet indices (1) or node names (node2, gateway4).
# None = every fleet VM (--enable) or every node host (port mode). An unknown target exits 1; the
# port mode skips a named host that runs no node, with a line.
#
# Usage:
#   ./devnet-firewall.sh                          # consensus ports on every node host
#   ./devnet-firewall.sh --enable                 # lockout-safe ufw enable, all seven VMs
#   ./devnet-firewall.sh node2 5                  # port mode on node2 and index 5 (rpc-6-devnet)
#   ./devnet-firewall.sh --enable gateway-4-devnet
# Exit: 0 ok · 1 a host failed, or an unknown target · 2 SSH lost after enabling, usage, configuration.

set -euo pipefail

fw_usage() {
    echo "usage: $0 [--enable] [target …]   (target = instance name, fleet index or node name)"
}

ENABLE_HOST_FW=0
TARGETS=()
for a in "$@"; do
    case "$a" in
        --enable) ENABLE_HOST_FW=1 ;;
        -h|--help) fw_usage; exit 0 ;;
        -*) echo "❌ unknown flag '$a'" >&2; fw_usage >&2; exit 2 ;;
        *) TARGETS+=("$a") ;;
    esac
done

# shellcheck source=devnet-lib.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

if ! tn_fleet_check; then
    echo "❌ the fleet arrays are inconsistent (lines above); nothing was touched" >&2
    exit 2
fi

FW="${TN_NODE_SCRIPTS_DIR}/firewall-setup.sh"

# --- targets -> SEL, a list of fleet indices ",i,j," (empty = no subset) ------------------------
SEL=""
for want in ${TARGETS[@]+"${TARGETS[@]}"}; do
    found=""
    for i in "${!INSTANCE_NAMES[@]}"; do
        if [ "${want}" = "${i}" ] || [ "${want}" = "${INSTANCE_NAMES[$i]}" ] || [ "${want}" = "${NODE_NAMES[$i]:-}" ]; then
            found="${i}"
            break
        fi
    done
    [ -n "${found}" ] || { echo "❌ unknown target '${want}' (not an instance name, fleet index or node name)" >&2; exit 1; }
    SEL="${SEL:-,}${found},"
done
_fw_selected() { [ -z "${SEL}" ] && return 0; case "${SEL}" in *",$1,"*) return 0 ;; esac; return 1; }
_fw_subset_names() {
    local i out=""
    for i in "${!INSTANCE_NAMES[@]}"; do _fw_selected "${i}" && out="${out} ${INSTANCE_NAMES[$i]}"; done
    printf '%s' "${out# }"
}

# --- --enable: lockout-safe ufw bring-up, ONE VM AT A TIME, every fleet VM ----------------------
# A-7(e): this mode means every VM, so it loops over all indices (the gateway host included).
if [ "${ENABLE_HOST_FW}" -eq 1 ]; then
    echo "=========================================="
    echo "devnet HOST firewall (ufw) — lockout-safe ENABLE (one VM at a time)"
    echo "Project:    ${PROJECT_ID}"
    echo "Method:     firewall-setup.sh --json --enable (SSH allowed BEFORE enable; rpc: --p2p-anywhere)"
    echo "Safety:     re-verify SSH after each VM; ABORT on loss (no further VM touched)"
    [ -n "${SEL}" ] && echo "Subset:     $(_fw_subset_names)"
    echo "=========================================="
    erc=0
    for i in "${!INSTANCE_NAMES[@]}"; do
        _fw_selected "${i}" || continue
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"; role="${NODE_ROLES[$i]}"
        cmd="sudo ${FW} --json --enable"
        [ "${role}" = "rpc" ] && cmd="${cmd} --p2p-anywhere"
        echo ""
        echo ">>> ${inst} (${zone}, role=${role}): ${cmd}"
        if json="$(tn_iap_ssh "${inst}" "${zone}" "${cmd}")"; then
            echo "    result: ${json}"
        else
            echo "    ❌ enable failed on ${inst}" >&2
            erc=1
            continue
        fi
        # CRITICAL lockout check: a fresh SSH connection must still succeed before moving on.
        if tn_iap_ssh "${inst}" "${zone}" true >/dev/null 2>&1; then
            echo "    ✓ SSH still reachable after enable"
        else
            echo "    ❌❌ SSH LOST after enabling UFW on ${inst} — ABORTING (no further VM touched)" >&2
            exit 2
        fi
        if [ "${role}" = "gateway" ]; then
            echo "    note: 80/443 stay closed here until the gateway is installed (step 13): install-caddy.sh opens them itself"
        fi
    done
    echo ""
    if [ "${erc}" -eq 0 ]; then
        echo "host ufw enabled (lockout-safe) on all targeted VMs."
    else
        echo "host ufw enable finished WITH ERRORS — see ❌ lines above." >&2
    fi
    exit "${erc}"
fi

echo "=========================================="
echo "devnet HOST firewall (ufw) consensus rules"
echo "Project:    ${PROJECT_ID}"
echo "Ports:      primary=${DEFAULT_PRIMARY_UDP_PORT}/udp worker=${DEFAULT_WORKER_UDP_PORT}/udp (node hosts only)"
echo "Precond:    ufw already enabled per host (run './devnet-firewall.sh --enable' first;"
echo "            THIS mode never enables ufw -- it only adds consensus ingress rules)"
[ -n "${SEL}" ] && echo "Subset:     $(_fw_subset_names)"
echo "=========================================="

rc=0
for i in "${!INSTANCE_NAMES[@]}"; do
    _fw_selected "${i}" || continue
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    role="${NODE_ROLES[$i]}"
    if ! tn_is_node_index "${i}"; then
        # Only reached when named: without targets, hosts without a node are passed over silently.
        [ -n "${SEL}" ] && echo "" && echo ">>> ${inst} (role=${role}): skipped, it runs no node (no consensus ports)"
        continue
    fi

    echo ""
    echo ">>> ${inst} (${zone}, role=${role})"

    # NO ROLE BRANCH among node hosts. Every node -- observer and rpc included -- gets the
    # consensus ports opened.
    #
    # An observer is not a permanent category: it is a full node that can be STAKED into the
    # committee at any time (devnet's node-5 is staked post-genesis by design). The moment it
    # is, peers dial IT, and a host firewall that drops 49590/49594 makes it an unreachable
    # committee member. Worse, the failure is delayed and misattributed -- the ports would be
    # closed by the NEXT routine run of this script, long after the staking change that
    # actually needed them, so it would look like a staking or consensus bug.
    #
    # An earlier revision of this script closed these ports on observers, reasoning that an
    # observer only dials out. That is wrong even before staking (the P2P mesh expects inbound
    # reachability) and actively harmful after it. The VPC rule devnet-allow-consensus opens
    # udp:49590/49594 from any source to the `devnet-p2p` tag that every node host carries
    # (setup-firewall.sh); the host firewall is where the sources are narrowed.
    # Open primary then worker. Both go through firewall-setup.sh --json,
    # so neither can touch sshd.
    for port in "${DEFAULT_PRIMARY_UDP_PORT}/udp" "${DEFAULT_WORKER_UDP_PORT}/udp"; do
        echo "    + sudo ${FW} --json --port ${port} on"
        if json="$(tn_iap_ssh "${inst}" "${zone}" "sudo ${FW} --json --port ${port} on")"; then
            echo "      result: ${json}"
        else
            echo "      ❌ firewall-setup.sh --port ${port} on failed on ${inst}" >&2
            rc=1
        fi
    done

    # Assert: re-read status and confirm both consensus ports show as open.
    echo "    + sudo ${FW} --json --status"
    if status_json="$(tn_iap_ssh "${inst}" "${zone}" "sudo ${FW} --json --status")"; then
        echo "      status: ${status_json}"
        missing=()
        case "${status_json}" in
            *"${DEFAULT_PRIMARY_UDP_PORT}"*) : ;;
            *) missing+=("${DEFAULT_PRIMARY_UDP_PORT}/udp") ;;
        esac
        case "${status_json}" in
            *"${DEFAULT_WORKER_UDP_PORT}"*) : ;;
            *) missing+=("${DEFAULT_WORKER_UDP_PORT}/udp") ;;
        esac
        if [ "${#missing[@]}" -gt 0 ]; then
            echo "      ⚠️  WARNING: status on ${inst} does not confirm: ${missing[*]} — verify UFW is enabled and rules applied." >&2
        else
            echo "      ✓ both consensus ports present in status"
        fi
    else
        echo "      ⚠️  could not read firewall status on ${inst} (is UFW enabled?)" >&2
        rc=1
    fi
done

echo ""
if [ "${rc}" -eq 0 ]; then
    echo "=========================================="
    echo "host firewall rules applied on all targeted node hosts."
    echo "=========================================="
else
    echo "=========================================="
    echo "host firewall pass finished WITH ERRORS — see ❌/⚠️ lines above." >&2
    echo "=========================================="
fi
exit "${rc}"
