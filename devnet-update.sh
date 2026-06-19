#!/bin/bash
#
# devnet-update.sh — staggered software redeploy across the fleet, WITHOUT
# recreating any GCP instance and WITHOUT touching keys.
#
# BFT preservation (f=1 on a 4-validator committee): at most ONE validator is
# ever down at a time. Validators are updated one at a time with a 10s settle
# pause between them, and the OBSERVER is done LAST (it carries no consensus
# vote, so its downtime can't stall the committee).
#
# Per node the cycle is:
#   (a) wipe chain data    -> ./devnet-wipe.sh --yes <instance>   (keys persist)
#   (b) redeploy software  -> ./devnet-finalize.sh <instance>     (re-pull/restage
#                              the possibly-new DOCKER_IMAGE; finalize accepts an
#                              optional instance subset — see its --help)
#   (c) settle ~10s, then poll `systemctl is-active <svc>` until the node reports
#       active before moving to the next node.
#
# Keygen is SKIPPED entirely — keys persist across the wipe, and keygen would
# refuse to clobber an existing keystore. This script ALSO never runs any
# `gcloud compute instances create|delete`.
#
# If ANY node fails to come back active within the timeout, the whole run ABORTS
# (set -e + explicit exit) so a single bad image can't cascade into a fleet-wide
# outage — you stop with N-1 healthy validators, not zero.
#
# --wipe-obs (default OFF): before touching any node, wipe ONLY the obs Loki +
# Prometheus data once via common/observability/wipe-obs-data.sh --yes (fresh
# logs/metrics for the new image; Grafana + Caddy preserved).
#
# Usage:
#   ./devnet-update.sh                 # staggered redeploy, all nodes
#   ./devnet-update.sh --wipe-obs      # also wipe obs logs/metrics first
#   ./devnet-update.sh --yes           # alias accepted; this script is already non-interactive

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${REPO_DIR}/devnet-lib.sh"

WIPE_SCRIPT="${REPO_DIR}/devnet-wipe.sh"
FINALIZE_SCRIPT="${REPO_DIR}/devnet-finalize.sh"
OBS_WIPE_SCRIPT="${REPO_DIR}/common/observability/wipe-obs-data.sh"

STAGGER_SECS=10          # pause between validators (BFT settle window)
HEALTH_TIMEOUT_SECS=120  # max wait for a node to report `systemctl is-active` == active
HEALTH_POLL_SECS=5

# --- args ----------------------------------------------------------------------
WIPE_OBS=0
for arg in "$@"; do
    case "${arg}" in
        --wipe-obs) WIPE_OBS=1 ;;
        --yes) : ;;  # accepted for symmetry; this script is non-interactive already
        *) echo "❌ unknown argument '${arg}' (supported: --wipe-obs, --yes)" >&2; exit 1 ;;
    esac
done

# Sanity: the sub-scripts we delegate to must exist and be runnable.
for s in "${WIPE_SCRIPT}" "${FINALIZE_SCRIPT}"; do
    [ -x "${s}" ] || { echo "❌ required sub-script not executable/missing: ${s}" >&2; exit 1; }
done

echo "=========================================="
echo "devnet STAGGERED redeploy (no instance recreate, keys preserved)"
echo "Image:     ${DOCKER_IMAGE}"
echo "Order:     validators one-at-a-time (${STAGGER_SECS}s apart), observer LAST"
echo "Health:    poll systemctl is-active up to ${HEALTH_TIMEOUT_SECS}s/node"
echo "Wipe obs:  $([ "${WIPE_OBS}" -eq 1 ] && echo yes || echo no)"
echo "=========================================="

# --- optional one-time obs data wipe -------------------------------------------
if [ "${WIPE_OBS}" -eq 1 ]; then
    echo ""
    echo ">>> --wipe-obs: wiping obs Loki + Prometheus once (Grafana + Caddy preserved)"
    [ -x "${OBS_WIPE_SCRIPT}" ] || { echo "❌ missing ${OBS_WIPE_SCRIPT}" >&2; exit 1; }
    "${OBS_WIPE_SCRIPT}" --yes || { echo "❌ obs data wipe failed — aborting before touching nodes." >&2; exit 1; }
fi

# wait_active <instance> <zone> <service> — poll until the unit is active, or fail.
wait_active() {
    local inst="$1" zone="$2" svc="$3"
    local waited=0 state
    while [ "${waited}" -lt "${HEALTH_TIMEOUT_SECS}" ]; do
        # is-active exits non-zero when not active; capture the text either way.
        state="$(tn_iap_ssh "${inst}" "${zone}" "systemctl is-active '${svc}' || true")"
        state="$(printf '%s' "${state}" | tr -d '[:space:]')"
        if [ "${state}" = "active" ]; then
            echo "      ✓ ${svc} is active on ${inst} (after ${waited}s)"
            return 0
        fi
        echo "      …${svc} on ${inst} is '${state:-unknown}' (waited ${waited}s/${HEALTH_TIMEOUT_SECS}s)"
        sleep "${HEALTH_POLL_SECS}"
        waited=$((waited + HEALTH_POLL_SECS))
    done
    echo "      ❌ ${svc} on ${inst} did not reach 'active' within ${HEALTH_TIMEOUT_SECS}s" >&2
    return 1
}

# redeploy_one <index> — wipe + finalize + health-gate a single node.
redeploy_one() {
    local i="$1"
    local inst="${INSTANCE_NAMES[$i]}"
    local zone="${ZONES[$i]}"
    local role
    role="$(tn_node_role "${i}")"
    local svc
    svc="$(tn_service_for_role "${role}")"

    echo ""
    echo "------------------------------------------"
    echo ">>> redeploy ${inst} (${zone}, role=${role}, service=${svc})"
    echo "------------------------------------------"

    echo "    (a) wipe chain data (keys preserved)"
    "${WIPE_SCRIPT}" --yes "${inst}" || { echo "    ❌ wipe failed on ${inst} — aborting run." >&2; return 1; }

    echo "    (b) redeploy software via finalize (image ${DOCKER_IMAGE})"
    "${FINALIZE_SCRIPT}" "${inst}" || { echo "    ❌ finalize failed on ${inst} — aborting run." >&2; return 1; }

    echo "    (c) settle ${STAGGER_SECS}s then poll service health"
    sleep "${STAGGER_SECS}"
    wait_active "${inst}" "${zone}" "${svc}" || { echo "    ❌ ${inst} did not come back healthy — aborting run." >&2; return 1; }
}

# --- Pass 1: validators, one at a time, with a stagger pause between -----------
echo ""
echo ">>> Pass 1: validators (staggered, one down at most)"
first_validator=1
for i in "${!INSTANCE_NAMES[@]}"; do
    [ "$(tn_node_role "${i}")" = "validator" ] || continue

    # Stagger: pause BEFORE each validator except the first, so consecutive
    # validators are spaced and the prior one has settled.
    if [ "${first_validator}" -eq 0 ]; then
        echo ""
        echo ">>> staggering ${STAGGER_SECS}s before the next validator (BFT settle)"
        sleep "${STAGGER_SECS}"
    fi
    first_validator=0

    redeploy_one "${i}" || exit 1
done

# --- Pass 2: observer(s) LAST --------------------------------------------------
echo ""
echo ">>> Pass 2: observer(s) last"
for i in "${!INSTANCE_NAMES[@]}"; do
    [ "$(tn_node_role "${i}")" = "observer" ] || continue
    redeploy_one "${i}" || exit 1
done

echo ""
echo "=========================================="
echo "staggered redeploy complete — every node back to 'active' on ${DOCKER_IMAGE}."
echo "=========================================="
