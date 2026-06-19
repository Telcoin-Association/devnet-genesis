#!/bin/bash
#
# devnet-firewall.sh — apply the HOST (UFW) consensus rules on each validator by
# driving its tn-node-deployment firewall-setup.sh over IAP. This is the host-fw
# companion to setup-firewall.sh (which manages the GCP/VPC layer).
#
# *** PRECONDITION: UFW must already be ENABLED once, interactively, per node ***
# from an IAP/console session (sudo ufw allow 22/tcp && sudo ufw --force enable).
# This script NEVER runs `ufw enable`/`ufw disable`; it only ever calls
# firewall-setup.sh --json, which by construction can only toggle the three
# permitted ports (49590/udp, 49594/udp, 43174/tcp) and STRUCTURALLY cannot touch
# sshd — so it can never lock you out of the IAP door.
#
# Per node:
#   - validator: open consensus primary (49590/udp) + worker (49594/udp).
#   - observer:  NO consensus ingress rule — the observer dials OUT to validators
#                and listens for nothing inbound on the consensus ports. Health
#                (43174/tcp) is opened by --enable-health in devnet-observability.sh,
#                NOT here.
# After applying, re-query --json --status and assert 49590/49594 show open on
# each validator; warn (do not hard-fail) if the status text doesn't confirm them.
#
# Reaches nodes only via the lib's IAP helpers. Optional instance-name subset; no
# args = whole fleet.
#
# Usage:
#   ./devnet-firewall.sh                       # all nodes
#   ./devnet-firewall.sh validator-2-devnet    # one (or more) by name

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

FW="${TN_NODE_SCRIPTS_DIR}/firewall-setup.sh"

# --- optional instance subset (positional args) --------------------------------
SELECTED=("$@")
if [ "${#SELECTED[@]}" -gt 0 ]; then
    for want in "${SELECTED[@]}"; do
        found=0
        for have in "${INSTANCE_NAMES[@]}"; do
            [ "${want}" = "${have}" ] && { found=1; break; }
        done
        [ "${found}" -eq 1 ] || { echo "❌ unknown instance '${want}' (not in INSTANCE_NAMES)" >&2; exit 1; }
    done
fi
tn_fw_selected() {
    [ "${#SELECTED[@]}" -eq 0 ] && return 0
    local inst="$1" s
    for s in "${SELECTED[@]}"; do [ "${s}" = "${inst}" ] && return 0; done
    return 1
}

echo "=========================================="
echo "devnet HOST firewall (UFW) consensus rules"
echo "Project:    ${PROJECT_ID}"
echo "Ports:      primary=${DEFAULT_PRIMARY_UDP_PORT}/udp worker=${DEFAULT_WORKER_UDP_PORT}/udp (validators only)"
echo "Precond:    UFW already enabled per node (this script never runs ufw enable)"
[ "${#SELECTED[@]}" -gt 0 ] && echo "Subset:     ${SELECTED[*]}"
echo "=========================================="

rc=0
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    role="$(tn_node_role "${i}")"

    tn_fw_selected "${inst}" || continue

    echo ""
    echo ">>> ${inst} (${zone}, role=${role})"

    if [ "${role}" = "observer" ]; then
        echo "    observer — no consensus ingress rule (it dials out). Health (${DEFAULT_HEALTHCHECK_TCP_PORT}/tcp)"
        echo "    is handled by --enable-health in devnet-observability.sh, not here. Nothing to apply."
        continue
    fi

    # validator: open primary then worker. Both go through firewall-setup.sh --json,
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
    echo "host firewall rules applied on all targeted validators."
    echo "=========================================="
else
    echo "=========================================="
    echo "host firewall pass finished WITH ERRORS — see ❌/⚠️ lines above." >&2
    echo "=========================================="
fi
exit "${rc}"
