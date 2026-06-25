#!/usr/bin/env bash
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
#                             SKIPPED under --no-wipe (re-finalize only; chain preserved).
#   (b) redeploy software  -> ./devnet-finalize.sh <instance>     (re-pull/restage
#                              the possibly-new DOCKER_IMAGE; finalize accepts an
#                              optional instance subset — see its --help). This step
#                              re-bakes the `telcoin node` launch flags either way.
#   (c) settle ~10s, then gate on wait_healthy (devnet-lib.sh): the unit must be active
#       AND the on-node healthcheck endpoint (:43174) must respond before the next node.
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
#   ./devnet-update.sh                 # staggered redeploy, all nodes (wipes chain each)
#   ./devnet-update.sh --no-wipe       # staggered RE-FINALIZE, chain preserved (health-gated)
#   ./devnet-update.sh --wipe-obs      # also wipe obs logs/metrics first
#   ./devnet-update.sh --yes           # alias accepted; this script is already non-interactive

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${REPO_DIR}/devnet-lib.sh"

WIPE_SCRIPT="${REPO_DIR}/devnet-wipe.sh"
FINALIZE_SCRIPT="${REPO_DIR}/devnet-finalize.sh"
OBS_WIPE_SCRIPT="${REPO_DIR}/common/observability/wipe-obs-data.sh"

STAGGER_SECS=10          # pause between validators (BFT settle window)
HEALTH_TIMEOUT_SECS=120  # max wait for a node to reach HEALTHY (active + :43174 responding); read by wait_healthy
HEALTH_POLL_SECS=5

# --- args ----------------------------------------------------------------------
WIPE_OBS=0
NO_WIPE=0
for arg in "$@"; do
    case "${arg}" in
        --wipe-obs) WIPE_OBS=1 ;;
        --no-wipe)  NO_WIPE=1 ;;   # re-finalize WITHOUT wiping chain data (preserve the chain)
        --yes) : ;;  # accepted for symmetry; this script is non-interactive already
        *) echo "❌ unknown argument '${arg}' (supported: --wipe-obs, --no-wipe, --yes)" >&2; exit 1 ;;
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
echo "Chain:     $([ "${NO_WIPE}" -eq 1 ] && echo 'PRESERVED (--no-wipe: re-finalize only)' || echo 'WIPED then re-finalized')"
echo "Health:    gate on active + :${DEFAULT_HEALTHCHECK_TCP_PORT} responding, up to ${HEALTH_TIMEOUT_SECS}s/node"
echo "Wipe obs:  $([ "${WIPE_OBS}" -eq 1 ] && echo yes || echo no)"
echo "=========================================="

# --- optional one-time obs data wipe -------------------------------------------
if [ "${WIPE_OBS}" -eq 1 ]; then
    echo ""
    echo ">>> --wipe-obs: wiping obs Loki + Prometheus once (Grafana + Caddy preserved)"
    [ -x "${OBS_WIPE_SCRIPT}" ] || { echo "❌ missing ${OBS_WIPE_SCRIPT}" >&2; exit 1; }
    "${OBS_WIPE_SCRIPT}" --yes || { echo "❌ obs data wipe failed — aborting before touching nodes." >&2; exit 1; }
fi

# Health gate is wait_healthy (active + :43174 responding) from devnet-lib.sh — shared with
# reset-network.sh, and reading HEALTH_TIMEOUT_SECS / HEALTH_POLL_SECS set above.

# redeploy_one <index> — [wipe] + finalize + health-gate a single node. With --no-wipe the
# wipe is skipped, turning this into a staggered RE-FINALIZE that preserves the chain (the
# finalize step is what re-bakes the launch flags either way).
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

    if [ "${NO_WIPE}" -eq 1 ]; then
        echo "    (a) --no-wipe: SKIP chain wipe (chain preserved)"
    else
        echo "    (a) wipe chain data (keys preserved)"
        "${WIPE_SCRIPT}" --yes "${inst}" || { echo "    ❌ wipe failed on ${inst} — aborting run." >&2; return 1; }
    fi

    echo "    (b) redeploy software via finalize (image ${DOCKER_IMAGE})"
    # A VALIDATOR finalize exits rc=1 BENIGNLY: it writes the wrapper/unit and the service
    # runs, then fails only the post-start on-chain address check (finalize passes no
    # --validator-address). So do NOT abort on the finalize rc — wait_healthy (step c) is the
    # real gate: it confirms the node is active AND actually serving :43174.
    if ! "${FINALIZE_SCRIPT}" "${inst}"; then
        echo "    ⓘ finalize rc≠0 (expected for validators: benign on-chain address check) — gating on health instead."
    fi

    # (b2) Apply the freshly-written wrapper. finalize only WRITES the wrapper/unit; under
    # --no-wipe the service was never stopped, so finalize's 'start' is a no-op and the OLD
    # container keeps running (old image, no --healthcheck). An explicit restart swaps in the
    # new wrapper (new image + flags). The wipe path gets a fresh start for free, so skip it
    # there. Pre-pull first (both paths) so the start/restart never races the image download
    # against wait_healthy's timeout.
    echo "    (b2) pre-pull ${DOCKER_IMAGE}"
    tn_iap_ssh "${inst}" "${zone}" "sudo docker pull '${DOCKER_IMAGE}'" >/dev/null 2>&1 \
        || { echo "    ❌ image pull failed on ${inst} — aborting run." >&2; return 1; }
    if [ "${NO_WIPE}" -eq 1 ]; then
        echo "         --no-wipe: restart ${svc} to apply the new wrapper (finalize 'start' is a no-op on a running svc)"
        tn_iap_ssh "${inst}" "${zone}" "sudo systemctl restart '${svc}'" \
            || { echo "    ❌ restart failed on ${inst} — aborting run." >&2; return 1; }
    fi

    echo "    (c) settle ${STAGGER_SECS}s then gate on endpoint health"
    sleep "${STAGGER_SECS}"
    wait_healthy "${inst}" "${zone}" "${svc}" || { echo "    ❌ ${inst} did not come back healthy — aborting run." >&2; return 1; }
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
