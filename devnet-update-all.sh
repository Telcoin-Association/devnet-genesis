#!/usr/bin/env bash
#
# devnet-update-all.sh — ALL-NODES-AT-ONCE image update, for WIRE-PROTOCOL-BREAKING
# upgrades where the staggered ./devnet-update.sh would fragment the committee:
# when nodes on the old and new image cannot gossip (e.g. v0.12.0's
# chain-id-namespaced gossip topics), updating one validator at a time strands
# each updated node with no peers until quorum crosses over — which a staggered
# rollout never cleanly achieves. Here every node restarts TOGETHER and quorum
# re-forms on the new protocol.
#
# ⚠ THE FLEET HALTS during phase 2: all 4 validators restart simultaneously and
# devnet produces nothing until ≥3 are back on the new image. That is the point.
#
# Same on-node tooling as individual operators (tn-node-deployment/update-node.sh
# --json), same helpers as devnet-update.sh (devnet-lib.sh tn_cmd_*/tn_json_*).
#
# Phases (per-node logs + marker files under logs/<ts>-update-all/):
#   0  refresh the tn-node-deployment clone on every node, in parallel, and
#      verify the wrapper-aware update-node.sh landed. Any failure → abort,
#      NOTHING touched.
#   1  --check + --prepare on every node in parallel (docker pull, ZERO
#      downtime). Unreadable current tag or failed pull → abort while the whole
#      fleet still runs the old image. Nodes already on the target tag get a
#      .skip marker. All skipped → jump straight to phase 3.
#   2  --apply on every node in parallel (THE downtime). No early abort: every
#      node runs to a terminal state and is judged afterwards. On-node verify
#      window ${APPLY_VERIFY_TIMEOUT}s (auto-rollback on timeout).
#   3  health-gate every node (wait_healthy: unit active + :43174 responding,
#      up to ${HEALTH_TIMEOUT_SECS}s each) — never aborts early: the summary
#      needs the FULL fleet picture.
#
# Per-node verdicts: UPDATED / SKIPPED / ROLLED BACK / APPLY FAILED / UNKNOWN /
# UNHEALTHY. Exit 0 only when every node is UPDATED or SKIPPED (and healthy).
#
# IDEMPOTENT: re-running converges the fleet — on-target nodes SKIP, failed or
# rolled-back nodes retry. It also works in REVERSE: point config.sh's
# DOCKER_IMAGE back at the old tag and re-run to downgrade across the same
# protocol boundary. Only UNKNOWN nodes (no apply verdict — SSH died mid-apply)
# need eyes before a re-run.
#
# Usage:
#   ./devnet-update-all.sh          # banner + type CONFIRM
#   ./devnet-update-all.sh --yes    # skip the confirmation gate

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
source "${REPO_DIR}/devnet-lib.sh"

APPLY_VERIFY_TIMEOUT=180 # on-node post-restart verify window; generous because ALL peers
                         # restart at once and quorum re-forms slower than a lone restart —
                         # a timeout here AUTO-ROLLS-BACK that node onto the old protocol.
HEALTH_TIMEOUT_SECS=300  # phase-3 wait_healthy budget per node (same reasoning)
HEALTH_POLL_SECS=5

TARGET_TAG="${DOCKER_IMAGE##*:}"

# --- args ----------------------------------------------------------------------
ASSUME_YES=0
for arg in "$@"; do
    case "${arg}" in
        --yes) ASSUME_YES=1 ;;
        *) echo "❌ unknown argument '${arg}' (supported: --yes)" >&2; exit 1 ;;
    esac
done

timestamp="$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${REPO_DIR}/logs/${timestamp}-update-all"
mkdir -p "${RUN_DIR}"

echo "==========================================================="
echo "devnet ALL-AT-ONCE image update (protocol-breaking upgrades)"
echo "Image:   ${DOCKER_IMAGE}"
echo "Nodes:   ${INSTANCE_NAMES[*]}"
echo "Logs:    ${RUN_DIR}"
echo ""
echo "⚠  ALL validators restart SIMULTANEOUSLY in phase 2 — devnet"
echo "   HALTS until quorum re-forms on the new image."
echo "   For a compatible (non-protocol-breaking) image, prefer the"
echo "   staggered ./devnet-update.sh, which keeps the chain live."
echo "==========================================================="
if [ "${ASSUME_YES}" -ne 1 ]; then
    printf 'Type CONFIRM to proceed: '
    read -r reply
    [ "${reply}" = "CONFIRM" ] || { echo "aborted — nothing touched."; exit 1; }
fi

# --- per-node phase jobs --------------------------------------------------------
# Run in background subshells; their stdout+stderr goes to <inst>.phaseN.log while
# the SSH stdout (the JSON stream) is captured via $(...) and persisted to
# <inst>.check.json / <inst>.apply.json for the summary. Cross-job state travels
# ONLY through marker files in ${RUN_DIR} (background jobs can't set parent vars).

phase0_one() {
    local i="$1"
    local inst="${INSTANCE_NAMES[$i]}" zone="${ZONES[$i]}"
    tn_iap_ssh "${inst}" "${zone}" "$(tn_cmd_refresh_scripts)" || {
        echo "refresh (or wrapper-aware marker check) FAILED — either tn-node-deployment main is not pushed to GitHub, or the node-side command errored (see the lines above)"
        return 1
    }
    echo "scripts clone fresh (wrapper-aware update-node.sh present)"
}

phase1_one() {
    local i="$1"
    local inst="${INSTANCE_NAMES[$i]}" zone="${ZONES[$i]}"
    local out line current
    out="$(tn_iap_ssh "${inst}" "${zone}" "$(tn_cmd_update_check)")" \
        || { echo "--check FAILED"; return 1; }
    printf '%s\n' "${out}" > "${RUN_DIR}/${inst}.check.json"
    line="$(tn_json_check_line "${out}")"
    current="$(tn_json_str "${line}" current_ref)"
    if [ -z "${current}" ]; then
        echo "--check returned no readable current image tag"
        return 1
    fi
    if [ "${current}" = "${TARGET_TAG}" ]; then
        : > "${RUN_DIR}/${inst}.skip"
        echo "already on ${TARGET_TAG} — will SKIP apply"
        return 0
    fi
    local done_line
    out="$(tn_iap_ssh "${inst}" "${zone}" "$(tn_cmd_update_prepare)")" \
        || { echo "--prepare (pull) FAILED; service untouched"; return 1; }
    done_line="$(tn_json_done_line "${out}")"
    if [ -z "${done_line}" ] || ! tn_json_true "${done_line}" ok; then
        echo "--prepare did not report ok; service untouched"
        return 1
    fi
    echo "prepared: ${current} → ${TARGET_TAG} (image pulled; service untouched)"
}

phase2_one() {
    local i="$1"
    local inst="${INSTANCE_NAMES[$i]}" zone="${ZONES[$i]}"
    if [ -f "${RUN_DIR}/${inst}.skip" ]; then
        echo "SKIP (already on ${TARGET_TAG})"
        return 0
    fi
    # rc deliberately not judged here: apply exits non-zero on failure AND on a
    # successful rollback; the done line in <inst>.apply.json (or its absence)
    # is the truth, classified in the summary.
    local out
    out="$(tn_iap_ssh "${inst}" "${zone}" "$(tn_cmd_update_apply "${APPLY_VERIFY_TIMEOUT}")")" || true
    printf '%s\n' "${out}" > "${RUN_DIR}/${inst}.apply.json"
    echo "apply finished; verdict deferred to summary"
}

# run_phase <phase-label> <job-fn> — one background job per node, barrier-wait,
# echo per-node one-liners. Returns the number of failed jobs.
run_phase() {
    local label="$1" fn="$2"
    local pids=() i inst
    for i in "${!INSTANCE_NAMES[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        ( "${fn}" "${i}" ) > "${RUN_DIR}/${inst}.${label}.log" 2>&1 &
        pids+=($!)
        echo "    started ${inst} (pid $!, log ${RUN_DIR}/${inst}.${label}.log)"
    done
    local fails=0
    for i in "${!pids[@]}"; do
        inst="${INSTANCE_NAMES[$i]}"
        if wait "${pids[$i]}"; then
            echo "    ✓ ${inst}: $(tail -1 "${RUN_DIR}/${inst}.${label}.log")"
        else
            fails=$((fails + 1))
            # last 5 lines, not tail -1: the last line is the job's own summary
            # echo — the actual remote error sits just above it.
            echo "    ❌ ${inst}: FAILED — last lines of ${RUN_DIR}/${inst}.${label}.log:"
            tail -5 "${RUN_DIR}/${inst}.${label}.log" | sed 's/^/        /'
        fi
    done
    return "${fails}"
}

# --- Phase 0: refresh scripts clones (parallel; abort => nothing touched) ------
echo ""
echo ">>> Phase 0: refresh tn-node-deployment clone on ALL nodes (zero service impact)"
if ! run_phase phase0 phase0_one; then
    echo "❌ phase 0 failed — aborting with NOTHING touched. Fix the cause in the log tails above, re-run." >&2
    exit 1
fi

# --- Phase 1: check + prepare (parallel; abort => fleet still on old image) ----
echo ""
echo ">>> Phase 1: check current tags + pre-pull ${TARGET_TAG} (zero downtime)"
if ! run_phase phase1 phase1_one; then
    echo "❌ phase 1 failed — aborting BEFORE any downtime: every node still runs its old image." >&2
    echo "   Fix the node(s) above (logs in ${RUN_DIR}) and re-run." >&2
    exit 1
fi

skip_count=0
for i in "${!INSTANCE_NAMES[@]}"; do
    if [ -f "${RUN_DIR}/${INSTANCE_NAMES[$i]}.skip" ]; then
        skip_count=$((skip_count + 1))
    fi
done

# --- Phase 2: apply everywhere at once (THE downtime; no early abort) ----------
if [ "${skip_count}" -eq "${#INSTANCE_NAMES[@]}" ]; then
    echo ""
    echo ">>> Phase 2: SKIPPED — every node already on ${TARGET_TAG}"
else
    echo ""
    echo ">>> Phase 2: APPLY on ALL nodes simultaneously — devnet halts until quorum re-forms"
    run_phase phase2 phase2_one || true   # verdicts come from the summary, not job rc
fi

# --- Phase 3: health-gate every node (sequential probe; recovery overlaps) -----
echo ""
echo ">>> Phase 3: health gate (active + :${DEFAULT_HEALTHCHECK_TCP_PORT}, up to ${HEALTH_TIMEOUT_SECS}s/node)"
declare -a NODE_HEALTHY
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    svc="$(tn_service_for_role "$(tn_node_role "${i}")")"
    echo "--- ${inst} ---"
    if wait_healthy "${inst}" "${zone}" "${svc}"; then
        NODE_HEALTHY[i]=1
    else
        NODE_HEALTHY[i]=0   # keep going — the summary needs the full fleet picture
    fi
done

# --- Summary -------------------------------------------------------------------
cat "${RUN_DIR}"/*.phase*.log > "${RUN_DIR}/combined.log" 2>/dev/null || true

echo ""
echo "==========================================================="
echo "ALL-AT-ONCE update summary — target ${DOCKER_IMAGE}"
echo "==========================================================="
overall=0
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    healthy="${NODE_HEALTHY[$i]}"
    class="" detail=""
    if [ -f "${RUN_DIR}/${inst}.skip" ]; then
        if [ "${healthy}" -eq 1 ]; then
            class="SKIPPED"; detail="already on ${TARGET_TAG}; healthy"
        else
            class="UNHEALTHY"; overall=1
            detail="already on ${TARGET_TAG} but NOT healthy — inspect journalctl -u telcoin"
        fi
    else
        done_line=""
        if [ -f "${RUN_DIR}/${inst}.apply.json" ]; then
            done_line="$(tn_json_done_line "$(cat "${RUN_DIR}/${inst}.apply.json")")"
        fi
        if [ -z "${done_line}" ]; then
            class="UNKNOWN"; overall=1
            detail="NO apply verdict (SSH died mid-apply?) — inspect journalctl -u telcoin NOW, before re-running"
        elif tn_json_true "${done_line}" rolled_back; then
            class="ROLLED BACK"; overall=1
            detail="verify timed out on the new image → node is BACK ON THE OLD IMAGE; it cannot rejoin a breaking-upgraded committee — re-run this script to converge it"
        elif ! tn_json_true "${done_line}" ok; then
            class="APPLY FAILED"; overall=1
            detail="$(tn_json_str "${done_line}" msg)"
        elif [ "${healthy}" -eq 1 ]; then
            class="UPDATED"; detail="now on ${TARGET_TAG}; healthy"
        else
            class="UNHEALTHY"; overall=1
            detail="apply reported ok but node not HEALTHY within ${HEALTH_TIMEOUT_SECS}s — inspect journalctl -u telcoin"
        fi
    fi
    printf '  %-22s %-13s %s\n' "${inst}" "${class}" "${detail}"
done
echo ""
echo "logs: ${RUN_DIR} (per-node phase logs, .check.json/.apply.json verdicts, combined.log)"

if [ "${overall}" -eq 0 ]; then
    echo ""
    echo "🎉 fleet converged on ${DOCKER_IMAGE} — every node UPDATED/SKIPPED and healthy."
    echo "   next: ./tn-node-deployment on-node check-node.sh, Grafana/Kuma, consensus height advancing."
else
    echo ""
    echo "⚠  fleet NOT converged. This script is IDEMPOTENT — re-run it: on-target nodes SKIP,"
    echo "   ROLLED BACK / APPLY FAILED nodes retry. UNKNOWN nodes need eyes FIRST (state unclear)."
    exit 1
fi
