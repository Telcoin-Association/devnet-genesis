#!/bin/bash
#
# devnet-observability.sh — roll out the per-node observability sidecar (Alloy:
# logs + metrics + the health endpoint) across the fleet by driving each node's
# tn-node-deployment setup-observability.sh over IAP.
#
# Per node it gates on the config.sh toggles TN_OBS_ENABLE_LOGS / _METRICS /
# _HEALTH (default-on for devnet); a node whose three toggles are all off is
# skipped entirely. The ingest token is fetched ONCE from Secret Manager and
# passed to setup-observability.sh via --token — it is NEVER echoed (we log a
# redacted form of the command, and the on-node script reads --json output only).
#
# NOTE: TN_OBS_ENABLE_DASHBOARD is a HUB concern (the Grafana dashboards live on
# the obs VM, provisioned by common/create-obs-instance.sh / obs-vm). It is NOT a
# per-node setup-observability.sh flag, so this script does not act on it — it is
# informational only.
#
# Reaches nodes only via the lib's IAP helpers (the always-on wg-allow-iap-ssh
# door). Pass an optional subset of instance names to target just those nodes;
# with no args it sweeps the whole fleet.
#
# Usage:
#   ./devnet-observability.sh                       # all nodes
#   ./devnet-observability.sh validator-1-devnet    # one (or more) by name

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# --- truthiness helper: a toggle is "on" only when exactly "1" -----------------
tn_obs_on() { [ "${1:-0}" = "1" ]; }

# --- optional instance subset (positional args) --------------------------------
# Validate any names up front so a typo fails before we touch a single node.
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

# tn_obs_selected <instance> — true if this instance is in the subset (or no subset given).
tn_obs_selected() {
    [ "${#SELECTED[@]}" -eq 0 ] && return 0
    local inst="$1" s
    for s in "${SELECTED[@]}"; do [ "${s}" = "${inst}" ] && return 0; done
    return 1
}

echo "=========================================="
echo "devnet observability rollout (Alloy logs/metrics/health)"
echo "Project:   ${PROJECT_ID}"
echo "Push URL:  ${OBS_PUSH_URL}"
echo "Metrics:   ${OBS_METRICS_PUSH_URL}"
echo "Toggles:   logs=${TN_OBS_ENABLE_LOGS} metrics=${TN_OBS_ENABLE_METRICS} health=${TN_OBS_ENABLE_HEALTH} (dashboard=${TN_OBS_ENABLE_DASHBOARD}: hub-only, not applied here)"
[ "${#SELECTED[@]}" -gt 0 ] && echo "Subset:    ${SELECTED[*]}"
echo "=========================================="

# Fetch the ingest token ONCE (read-only). Fail loud if empty so we never push a
# blank --token (which would silently disable auth on the agent).
echo ""
echo ">>> fetching obs ingest token from Secret Manager (${OBS_SECRET_NAME}) — value is NEVER printed"
token="$(tn_secret "${OBS_SECRET_NAME}")"
if [ -z "${token}" ]; then
    echo "❌ obs ingest token (${OBS_SECRET_NAME}) is empty — refusing to roll out without it." >&2
    exit 1
fi
echo "    token retrieved (redacted)"

rc=0
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"

    tn_obs_selected "${inst}" || continue

    # Skip the node entirely when none of the three per-node toggles are on.
    if ! tn_obs_on "${TN_OBS_ENABLE_LOGS}" && ! tn_obs_on "${TN_OBS_ENABLE_METRICS}" && ! tn_obs_on "${TN_OBS_ENABLE_HEALTH}"; then
        echo ""
        echo ">>> ${inst}: all obs toggles off — skipping"
        continue
    fi

    region="$(tn_region_from_zone "${zone}")"

    # Build the enable-flag list from the toggles (one --enable-* per active toggle).
    enable_flags=()
    tn_obs_on "${TN_OBS_ENABLE_LOGS}"    && enable_flags+=(--enable-logs)
    tn_obs_on "${TN_OBS_ENABLE_METRICS}" && enable_flags+=(--enable-metrics)
    tn_obs_on "${TN_OBS_ENABLE_HEALTH}"  && enable_flags+=(--enable-health)

    echo ""
    echo ">>> ${inst} (${zone}, region=${region}): setup-observability.sh ${enable_flags[*]}"

    # The on-node script needs root. Build the command around a placeholder for
    # the token slot, then materialize the real command for execution and a
    # redacted copy for the log SEPARATELY — the token is only ever spliced into
    # the run copy, never matched/substituted, so its character set can't matter
    # and it can never reach a log line.
    cmd_pre="sudo OBS_PUSH_URL='${OBS_PUSH_URL}' OBS_METRICS_PUSH_URL='${OBS_METRICS_PUSH_URL}'"
    cmd_pre+=" ${TN_NODE_SCRIPTS_DIR}/setup-observability.sh --json ${enable_flags[*]}"
    cmd_pre+=" --region '${region}' --token '"
    cmd_post="' --push-url '${OBS_PUSH_URL}' --metrics-push-url '${OBS_METRICS_PUSH_URL}'"

    remote_cmd="${cmd_pre}${token}${cmd_post}"          # for execution (carries the secret)
    redacted_cmd="${cmd_pre}***REDACTED***${cmd_post}"  # for the log (no secret)
    echo "    + ${redacted_cmd}"

    # Run it; capture the returned JSON to log per node. Don't let one node abort
    # the whole sweep — record the failure and continue, exit non-zero at the end.
    if json="$(tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}")"; then
        echo "    result: ${json}"
    else
        echo "    ❌ setup-observability.sh failed on ${inst}" >&2
        rc=1
    fi
done

echo ""
if [ "${rc}" -eq 0 ]; then
    echo "=========================================="
    echo "observability rollout complete on all targeted nodes."
    echo "=========================================="
else
    echo "=========================================="
    echo "observability rollout finished WITH ERRORS — see the ❌ lines above." >&2
    echo "=========================================="
fi
exit "${rc}"
