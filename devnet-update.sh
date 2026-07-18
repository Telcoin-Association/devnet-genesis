#!/usr/bin/env bash
#
# devnet-update.sh — staggered per-node software update across the fleet, WITHOUT
# recreating any GCP instance and WITHOUT touching keys.
#
# DEFAULT (image mode): a SAFE image-only update. Per node: pull the new
# DOCKER_IMAGE (zero downtime) → stop → swap the image reference in the launch
# wrapper/unit → restart → health-gate. Chain data, keys, staged genesis and
# launch flags are ALL preserved. Driven through the SAME on-node tooling
# individual operators use (tn-node-deployment/update-node.sh --json), so every
# fleet update also exercises the operator path.
#
# Explicit opt-in modes (mutually exclusive):
#   --finalize   what --no-wipe used to do: re-stage genesis + re-run finalize
#                (rewrites the wrapper/unit + launch flags), chain preserved.
#                Use when launch flags or staged chain-config change, not just
#                the image.
#   --wipe       what the DEFAULT used to be: wipe chain data per node (keys
#                persist), then finalize. RESETS THE NETWORK'S CHAIN — never
#                again reachable by forgetting a flag.
#   --no-wipe    DEPRECATED alias of the new image-only default (prints a notice
#                pointing at --finalize, which is the old --no-wipe behavior).
#
# BFT preservation (f=1 on a 4-validator committee): at most ONE validator is
# ever down at a time. Validators are updated one at a time with a
# ${STAGGER_SECS}s settle pause between them, and the OBSERVER is done LAST (it
# carries no consensus vote, so its downtime can't stall the committee). If ANY
# node fails its step or its health gate, the whole run ABORTS — you stop with
# N-1 healthy validators, not zero.
#
# ⚠ For WIRE-PROTOCOL-BREAKING upgrades (e.g. chain-id-namespaced gossip topics
# in v0.12.0) a staggered rollout FRAGMENTS the committee: updated and
# not-yet-updated nodes cannot gossip, so each updated validator is stranded
# until quorum crosses over — which it never cleanly does one node at a time.
# Use ./devnet-update-all.sh for those (all nodes at once).
#
# --wipe-obs (default OFF, composable with any mode): before touching any node,
# wipe ONLY the obs Loki + Prometheus data once via
# common/observability/wipe-obs-data.sh --yes (Grafana + Caddy preserved).
#
# Usage:
#   ./devnet-update.sh                 # image-only staggered update (SAFE default)
#   ./devnet-update.sh --finalize      # staggered re-finalize, chain preserved
#   ./devnet-update.sh --wipe          # staggered wipe + re-finalize (CHAIN RESET)
#   ./devnet-update.sh --wipe-obs      # also wipe obs logs/metrics first
#   ./devnet-update.sh --yes           # accepted; this script is non-interactive

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${REPO_DIR}/devnet-lib.sh"

WIPE_SCRIPT="${REPO_DIR}/devnet-wipe.sh"
FINALIZE_SCRIPT="${REPO_DIR}/devnet-finalize.sh"
OBS_WIPE_SCRIPT="${REPO_DIR}/common/observability/wipe-obs-data.sh"

STAGGER_SECS=10          # pause between validators (BFT settle window)
HEALTH_TIMEOUT_SECS=120  # max wait for a node to reach HEALTHY (active + :43174 responding); read by wait_healthy
HEALTH_POLL_SECS=5
APPLY_VERIFY_TIMEOUT=120 # on-node post-restart verify window (image mode); overrides update-node.sh's 45s
                         # default because a devnet node restarting into a live committee can take longer
                         # than a quiet single-operator restart — a timeout there AUTO-ROLLS-BACK the node.

TARGET_TAG="${DOCKER_IMAGE##*:}"

# --- args ----------------------------------------------------------------------
WIPE_OBS=0
MODE="image"
MODE_FLAG=""   # which flag chose MODE (conflict detection)

set_mode() {
    local mode="$1" flag="$2"
    if [ -n "${MODE_FLAG}" ]; then
        echo "❌ conflicting mode flags: ${MODE_FLAG} and ${flag} (pick one of --wipe | --finalize)" >&2
        exit 1
    fi
    MODE="${mode}"
    MODE_FLAG="${flag}"
}

for arg in "$@"; do
    case "${arg}" in
        --wipe)     set_mode wipe --wipe ;;
        --finalize) set_mode finalize --finalize ;;
        --no-wipe)
            echo "⚠  --no-wipe is DEPRECATED: the default is now an image-only update (chain preserved," >&2
            echo "   launch flags untouched) — proceeding with that. If you wanted the old --no-wipe" >&2
            echo "   behavior (re-finalize: re-stage genesis + rewrite wrapper/unit), use --finalize." >&2
            set_mode image --no-wipe ;;
        --wipe-obs) WIPE_OBS=1 ;;
        --yes) : ;;  # accepted for symmetry; this script is non-interactive already
        *) echo "❌ unknown argument '${arg}' (supported: --wipe, --finalize, --wipe-obs, --yes)" >&2; exit 1 ;;
    esac
done

# Sanity: only the modes that delegate to sub-scripts need them present. Image
# mode is self-contained (drives the on-node update-node.sh over SSH).
case "${MODE}" in
    wipe)
        for s in "${WIPE_SCRIPT}" "${FINALIZE_SCRIPT}"; do
            [ -x "${s}" ] || { echo "❌ required sub-script not executable/missing: ${s}" >&2; exit 1; }
        done ;;
    finalize)
        [ -x "${FINALIZE_SCRIPT}" ] || { echo "❌ required sub-script not executable/missing: ${FINALIZE_SCRIPT}" >&2; exit 1; } ;;
esac

case "${MODE}" in
    image)    CHAIN_DESC="PRESERVED (image-only swap; launch flags untouched)" ;;
    finalize) CHAIN_DESC="PRESERVED (--finalize: re-finalize only)" ;;
    wipe)     CHAIN_DESC="WIPED then re-finalized (--wipe)" ;;
esac

echo "=========================================="
echo "devnet STAGGERED update — mode: ${MODE}"
echo "Image:     ${DOCKER_IMAGE}"
echo "Order:     validators one-at-a-time (${STAGGER_SECS}s apart), observer LAST"
echo "Chain:     ${CHAIN_DESC}"
echo "Health:    gate on active + :${DEFAULT_HEALTHCHECK_TCP_PORT} responding, up to ${HEALTH_TIMEOUT_SECS}s/node"
echo "Wipe obs:  $([ "${WIPE_OBS}" -eq 1 ] && echo yes || echo no)"
echo ""
echo "ⓘ protocol-breaking upgrade (nodes on old+new image can't gossip)?"
echo "  Use ./devnet-update-all.sh instead — staggering would fragment the committee."
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

# --- image mode phase 0: refresh the on-node scripts clone (no service impact) --
# The image path depends on the wrapper-aware update-node.sh (v1.1.56 marker:
# TN_UPDATE_VERIFY_TIMEOUT). Refresh + verify the marker on EVERY node before
# touching ANY service, so a stale clone can never strand a half-updated fleet.
RUN_LOG_DIR=""
if [ "${MODE}" = "image" ]; then
    RUN_LOG_DIR="${REPO_DIR}/logs/$(date +%Y%m%d_%H%M%S)-update"
    mkdir -p "${RUN_LOG_DIR}"
    echo ""
    echo ">>> Phase 0: refresh tn-node-deployment clone on ALL nodes (zero service impact)"
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        zone="${ZONES[$i]}"
        echo "    refreshing ${inst}…"
        if ! tn_iap_ssh "${inst}" "${zone}" "$(tn_cmd_refresh_scripts)" >>"${RUN_LOG_DIR}/${inst}.log" 2>&1; then
            echo "❌ scripts refresh (or marker check) failed on ${inst} — see ${RUN_LOG_DIR}/${inst}.log" >&2
            echo "   The wrapper-aware update-node.sh must be on every node BEFORE any image update." >&2
            echo "   Is tn-node-deployment main pushed to GitHub? Aborting with all services untouched." >&2
            exit 1
        fi
    done
    echo "    ✓ all nodes on current scripts (wrapper-aware update-node.sh present)"
fi

# redeploy_one <index> — legacy modes: [wipe] + finalize + health-gate a single node.
# Under --finalize the wipe is skipped, turning this into a staggered RE-FINALIZE that
# preserves the chain (the finalize step is what re-bakes the launch flags either way).
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

    if [ "${MODE}" = "finalize" ]; then
        echo "    (a) --finalize: SKIP chain wipe (chain preserved)"
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
    # --finalize the service was never stopped, so finalize's 'start' is a no-op and the OLD
    # container keeps running (old image, no --healthcheck). An explicit restart swaps in the
    # new wrapper (new image + flags). The wipe path gets a fresh start for free, so skip it
    # there. Pre-pull first (both paths) so the start/restart never races the image download
    # against wait_healthy's timeout.
    echo "    (b2) pre-pull ${DOCKER_IMAGE}"
    tn_iap_ssh "${inst}" "${zone}" "sudo docker pull '${DOCKER_IMAGE}'" >/dev/null 2>&1 \
        || { echo "    ❌ image pull failed on ${inst} — aborting run." >&2; return 1; }
    if [ "${MODE}" = "finalize" ]; then
        echo "         --finalize: restart ${svc} to apply the new wrapper (finalize 'start' is a no-op on a running svc)"
        tn_iap_ssh "${inst}" "${zone}" "sudo systemctl restart '${svc}'" \
            || { echo "    ❌ restart failed on ${inst} — aborting run." >&2; return 1; }
    fi

    echo "    (c) settle ${STAGGER_SECS}s then gate on endpoint health"
    sleep "${STAGGER_SECS}"
    wait_healthy "${inst}" "${zone}" "${svc}" || { echo "    ❌ ${inst} did not come back healthy — aborting run." >&2; return 1; }
}

# update_one_image <index> — image mode: update ONE node via the on-node
# update-node.sh JSON contract (check → prepare → apply → health-gate). Chain,
# keys, staged genesis and launch flags untouched; only the image ref changes.
# JSON arrives on the SSH stdout; all human noise goes to the per-node log.
update_one_image() {
    local i="$1"
    local inst="${INSTANCE_NAMES[$i]}"
    local zone="${ZONES[$i]}"
    local role
    role="$(tn_node_role "${i}")"
    local svc
    svc="$(tn_service_for_role "${role}")"
    local nlog="${RUN_LOG_DIR}/${inst}.log"

    echo ""
    echo "------------------------------------------"
    echo ">>> image update ${inst} (${zone}, role=${role}, service=${svc})"
    echo "------------------------------------------"

    # (1) --check: read the node's current tag. Empty = the wrapper-aware detect
    # failed (should be impossible after phase 0) — abort rather than guess.
    echo "    (1) check current image"
    local check_out check_line current_ref
    check_out="$(tn_iap_ssh "${inst}" "${zone}" "$(tn_cmd_update_check)" 2>>"${nlog}")" \
        || { echo "    ❌ --check failed on ${inst} (see ${nlog}) — aborting run." >&2; return 1; }
    check_line="$(tn_json_check_line "${check_out}")"
    current_ref="$(tn_json_str "${check_line}" current_ref)"
    if [ -z "${current_ref}" ]; then
        echo "    ❌ ${inst}: --check returned no current image tag (see ${nlog}) — aborting run." >&2
        return 1
    fi
    if [ "${current_ref}" = "${TARGET_TAG}" ]; then
        echo "    ✓ already on ${TARGET_TAG} — SKIP update, health-gate only (idempotent re-run)"
        wait_healthy "${inst}" "${zone}" "${svc}" || { echo "    ❌ ${inst} not healthy — aborting run." >&2; return 1; }
        return 0
    fi
    echo "        current=${current_ref} → target=${TARGET_TAG}"

    # (2) --prepare: docker pull on the node. ZERO downtime; service untouched.
    echo "    (2) prepare (pull ${DOCKER_IMAGE}; zero downtime)"
    local prep_out prep_done
    prep_out="$(tn_iap_ssh "${inst}" "${zone}" "$(tn_cmd_update_prepare)" 2>>"${nlog}")" \
        || { echo "    ❌ prepare failed on ${inst} (service untouched; see ${nlog}) — aborting run." >&2; return 1; }
    prep_done="$(tn_json_done_line "${prep_out}")"
    if [ -z "${prep_done}" ] || ! tn_json_true "${prep_done}" ok; then
        echo "    ❌ prepare did not report ok on ${inst} (service untouched; see ${nlog}) — aborting run." >&2
        return 1
    fi

    # (3) --apply: stop → swap image ref → restart → on-node verify (window
    # ${APPLY_VERIFY_TIMEOUT}s, auto-rollback on timeout). The apply exits
    # non-zero on failure/rollback, so capture FIRST and judge from the done
    # line — its ABSENCE means SSH died mid-apply and the node's true state is
    # unknown: eyes on the node before any retry.
    echo "    (3) apply (stop → swap → restart; on-node verify ${APPLY_VERIFY_TIMEOUT}s)"
    local apply_out apply_done
    apply_out="$(tn_iap_ssh "${inst}" "${zone}" "$(tn_cmd_update_apply "${APPLY_VERIFY_TIMEOUT}")" 2>>"${nlog}")" || true
    apply_done="$(tn_json_done_line "${apply_out}")"
    if [ -z "${apply_done}" ]; then
        echo "    ❌ ${inst}: NO apply result — SSH dropped mid-apply? Node state UNKNOWN." >&2
        echo "       Inspect it NOW (journalctl -u ${svc}, sudo docker ps) before re-running. Aborting." >&2
        return 1
    fi
    if tn_json_true "${apply_done}" rolled_back; then
        echo "    ❌ ${inst}: health verify FAILED on the new image — node auto-ROLLED-BACK to ${current_ref}." >&2
        echo "       ${apply_done}" >&2
        echo "       Aborting run. Investigate before retrying (see ${nlog})." >&2
        return 1
    fi
    if ! tn_json_true "${apply_done}" ok; then
        echo "    ❌ ${inst}: apply failed: ${apply_done}" >&2
        echo "       Inspect the node (journalctl -u ${svc}; ${nlog}) — aborting run." >&2
        return 1
    fi
    echo "    ✓ applied — now on ${DOCKER_IMAGE}"

    # (4) settle, then the fleet-side health gate (unit active + :43174).
    echo "    (4) settle ${STAGGER_SECS}s then gate on endpoint health"
    sleep "${STAGGER_SECS}"
    wait_healthy "${inst}" "${zone}" "${svc}" || { echo "    ❌ ${inst} did not come back healthy — aborting run." >&2; return 1; }
}

# node_update <index> — dispatch one node on MODE.
node_update() {
    if [ "${MODE}" = "image" ]; then
        update_one_image "$1"
    else
        redeploy_one "$1"
    fi
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

    node_update "${i}" || exit 1
done

# --- Pass 2: observer(s) LAST --------------------------------------------------
echo ""
echo ">>> Pass 2: observer(s) last"
for i in "${!INSTANCE_NAMES[@]}"; do
    [ "$(tn_node_role "${i}")" = "observer" ] || continue
    node_update "${i}" || exit 1
done

echo ""
echo "=========================================="
echo "staggered update complete (mode: ${MODE}) — every node HEALTHY on ${DOCKER_IMAGE}."
[ -n "${RUN_LOG_DIR}" ] && echo "per-node logs: ${RUN_LOG_DIR}"
echo "=========================================="
