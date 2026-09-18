#!/usr/bin/env bash
#
# devnet-firewall.sh — manage the HOST (UFW) firewall on each node by driving its
# tn-node-deployment firewall-setup.sh over the lib transport (IAP by default, or the
# WireGuard overlay when TN_SSH_TRANSPORT=overlay). Companion to setup-firewall.sh
# (which manages the GCP/VPC layer).
#
# Two modes:
#   (default)  apply consensus ingress rules on an ALREADY-enabled UFW:
#                - validator: open primary (49590/udp) + worker (49594/udp)
#                - observer:  none (it dials OUT; health 43174/tcp is opened by
#                             --enable-health in devnet-observability.sh, not here)
#              Goes through firewall-setup.sh --json --port, which STRUCTURALLY cannot
#              touch sshd. After applying, --json --status asserts the ports show open.
#
#   --enable   lockout-safe host-UFW bring-up (Step 10), ONE NODE AT A TIME: run
#              firewall-setup.sh --json --enable (it allows SSH + the overlay
#              10.100.0.0/16 + the kuma monitor BEFORE `ufw --force enable`, and opens
#              validator P2P), then RE-VERIFY SSH still works before touching the next
#              node — ABORT immediately if SSH is lost. Removes the old "enable UFW by
#              hand first" precondition.
#
# Reaches nodes via the lib's transport helpers (tn_iap_ssh -> IAP or overlay).
# Optional instance-name subset; no args = whole fleet.
#
# Usage:
#   ./devnet-firewall.sh                       # consensus ports, all nodes (UFW already enabled)
#   ./devnet-firewall.sh --enable              # lockout-safe UFW enable, all nodes, one at a time
#   ./devnet-firewall.sh validator-2-devnet    # one (or more) by name
#   ./devnet-firewall.sh --enable observer-5-devnet

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

FW="${TN_NODE_SCRIPTS_DIR}/firewall-setup.sh"

# --- args: optional --enable (lockout-safe host-UFW bring-up) + instance subset ---
ENABLE_HOST_FW=0
SELECTED=()
for a in "$@"; do
    case "$a" in
        --enable) ENABLE_HOST_FW=1 ;;
        *)        SELECTED+=("$a") ;;
    esac
done
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

# --- --enable: lockout-safe host-UFW bring-up, ONE NODE AT A TIME -----------------
# Delegates the actual enable to firewall-setup.sh --json --enable (which allows SSH +
# overlay + kuma BEFORE `ufw --force enable`). After each node, a NEW SSH connection must
# succeed or we ABORT — so a lockout can never propagate past the first affected node.
if [ "${ENABLE_HOST_FW}" -eq 1 ]; then
    echo "=========================================="
    echo "devnet HOST firewall (UFW) — lockout-safe ENABLE (one node at a time)"
    echo "Project:    ${PROJECT_ID}"
    echo "Method:     firewall-setup.sh --json --enable (SSH + overlay + kuma allowed BEFORE enable)"
    echo "LB health:  $([ -n "${GOOGLE_HC_RANGES:-}" ] && echo "open ${DEFAULT_HEALTHCHECK_TCP_PORT}/tcp to Google HC ranges (${GOOGLE_HC_RANGES})" || echo "none (GOOGLE_HC_RANGES empty)")"
    echo "Safety:     re-verify SSH after each node; ABORT on loss (no further nodes touched)"
    [ "${#SELECTED[@]}" -gt 0 ] && echo "Subset:     ${SELECTED[*]}"
    echo "=========================================="
    # Open the health port to the GCP LB health-check ranges as part of the lockout-safe
    # enable (firewall-setup.sh -> apply_lb_hc_rule). Empty -> omitted -> generic enable.
    lb_hc_env=""
    [ -n "${GOOGLE_HC_RANGES:-}" ] && lb_hc_env="env TN_LB_HC_RANGES='${GOOGLE_HC_RANGES}' "
    erc=0
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"; zone="${ZONES[$i]}"
        tn_fw_selected "${inst}" || continue
        echo ""
        echo ">>> ${inst} (${zone}): sudo ${lb_hc_env}${FW} --json --enable"
        if json="$(tn_iap_ssh "${inst}" "${zone}" "sudo ${lb_hc_env}${FW} --json --enable")"; then
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
            echo "    ❌❌ SSH LOST after enabling UFW on ${inst} — ABORTING (no further nodes touched)" >&2
            exit 2
        fi
    done
    echo ""
    if [ "${erc}" -eq 0 ]; then
        echo "host UFW enabled (lockout-safe) on all targeted nodes."
    else
        echo "host UFW enable finished WITH ERRORS — see ❌ lines above." >&2
    fi
    exit "${erc}"
fi

echo "=========================================="
echo "devnet HOST firewall (UFW) consensus rules"
echo "Project:    ${PROJECT_ID}"
echo "Ports:      primary=${DEFAULT_PRIMARY_UDP_PORT}/udp worker=${DEFAULT_WORKER_UDP_PORT}/udp (validators only)"
echo "Precond:    UFW already enabled per node (run './devnet-firewall.sh --enable' first;"
echo "            THIS mode never enables UFW -- it only adds consensus ingress rules)"
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
        # An observer DIALS OUT; it never needs inbound consensus P2P. We now actively CLOSE
        # those ports rather than merely skipping the node, because the lockout-safe
        # `--enable` path opens validator P2P unconditionally (firewall-setup.sh has no role
        # awareness), so after Step 10 the observer would otherwise sit with 49590/49594 open
        # to the world. The old manual `ufw allow 22/tcp && ufw --force enable` recipe never
        # opened them, so skipping was previously enough. `--port <p> off` is idempotent.
        # Health (${DEFAULT_HEALTHCHECK_TCP_PORT}/tcp) stays: it is applied by
        # --enable-health in devnet-observability.sh and is what the LB/Kuma probe.
        echo "    observer — closing consensus ingress (it dials out; --enable opens P2P role-blind)"
        for port in "${DEFAULT_PRIMARY_UDP_PORT}/udp" "${DEFAULT_WORKER_UDP_PORT}/udp"; do
            echo "    + sudo ${FW} --json --port ${port} off"
            if json="$(tn_iap_ssh "${inst}" "${zone}" "sudo ${FW} --json --port ${port} off")"; then
                echo "      result: ${json}"
            else
                echo "      ❌ firewall-setup.sh --port ${port} off failed on ${inst}" >&2
                rc=1
            fi
        done
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
