#!/usr/bin/env bash
#
# devnet-teardown.sh — DESTROY the 5 devnet node VMs (and their boot disks) so the
# fleet can be rebuilt from scratch on a brand-new genesis.
#
# This is the counterpart to devnet-wipe.sh. Where wipe removes only chain data and
# deliberately PRESERVES keys, teardown removes the machines themselves — which is the
# only way to get fresh BLS/network/execution keys:
#
#   * common/create-instances.sh SKIPS instances that already exist, so a redeploy
#     against the live fleet would silently reuse the old VMs.
#   * setup-node.sh refuses keygen when ${DATA_DIR}/node-keys is present, and
#     devnet-keygen.sh always passes --json (non-interactive), so the run would then
#     abort at deploy step 5 with:
#         node-keys already exist at /var/lib/telcoin/node-keys -- refusing to overwrite
#
# Deleting the instance with --delete-disks=all takes the keys with it. Each node has
# exactly ONE disk (the 100GB pd-ssd boot disk created inline by create-instances.sh);
# there are no separate node data disks to enumerate.
#
# PRESERVED — this script does NOT touch any of these:
#   * the reserved static external IPs (validator-{1..4}-devnet-ip, observer-5-devnet-ip).
#     They drop to RESERVED and are re-attached by name on recreate, so DNS A-records for
#     node{1..5}/admin.node*/obs./rpc. stay correct and deploy step 4 is a no-op.
#   * GCP Secret Manager secrets (obs-ingest-token, obs-grafana-admin,
#     devnet-admin-dashboard-hash)
#   * obs-devnet + its obs-devnet-data persistent disk (redeployed by deploy step 8)
#   * the RPC load balancer (devnet-rpc-fr / -backend / -hc / -ip) and its URL map/cert
#   * DNS records, VPC firewall rules
#   * the WireGuard hub in tn-devops-sandbox
#   * devnet-indexer (terminated, out of scope) and txgen-devnet
#
# Reaches GCP only through the control plane (instances delete). It never SSHes to a
# node — the node is about to stop existing.
#
# DESTRUCTIVE AND IRREVERSIBLE: refuses to run unless --yes is passed OR FORCE=true is
# in the env. With neither, it prints exactly what WOULD be deleted and what is
# preserved, then exits 0. Optional instance-name subset; no args = whole fleet.
#
# Usage:
#   ./devnet-teardown.sh                          # DRY RUN: print the plan, delete nothing
#   ./devnet-teardown.sh --yes                    # delete all 5 node VMs + boot disks
#   ./devnet-teardown.sh --yes validator-3-devnet # delete one (or more) by name
#   FORCE=true ./devnet-teardown.sh               # delete all (env-gated)

set -euo pipefail

source "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/devnet-lib.sh"

# --- args: --yes flag (anywhere) + optional instance-name subset ---------------
CONFIRM=0
SELECTED=()
for arg in "$@"; do
    case "${arg}" in
        --yes) CONFIRM=1 ;;
        -*) echo "❌ unknown flag '${arg}' (only --yes is supported)" >&2; exit 1 ;;
        *)  SELECTED+=("${arg}") ;;
    esac
done
[ "${FORCE:-}" = "true" ] && CONFIRM=1

# Validate any requested names against INSTANCE_NAMES — never delete something this
# config does not own.
if [ "${#SELECTED[@]}" -gt 0 ]; then
    for want in "${SELECTED[@]}"; do
        found=0
        for have in "${INSTANCE_NAMES[@]}"; do
            [ "${want}" = "${have}" ] && { found=1; break; }
        done
        [ "${found}" -eq 1 ] || { echo "❌ unknown instance '${want}' (not in INSTANCE_NAMES)" >&2; exit 1; }
    done
fi
tn_teardown_selected() {
    [ "${#SELECTED[@]}" -eq 0 ] && return 0
    local inst="$1" s
    for s in "${SELECTED[@]}"; do [ "${s}" = "${inst}" ] && return 0; done
    return 1
}

echo "=========================================="
echo "devnet fleet TEARDOWN — destroys node VMs + boot disks"
echo "Project:   ${PROJECT_ID}"
echo "Method:    gcloud compute instances delete --delete-disks=all"
[ "${#SELECTED[@]}" -gt 0 ] && echo "Subset:    ${SELECTED[*]}"
if [ "${CONFIRM}" -eq 1 ]; then
    echo "Mode:      APPLY (--yes/FORCE) — THIS IS IRREVERSIBLE"
else
    echo "Mode:      DRY RUN (no --yes) — nothing will be deleted"
fi
echo "=========================================="

# --- the plan ------------------------------------------------------------------
# Resolve current state first so the dry run reflects reality (an already-deleted
# instance is reported as such rather than silently "planned").
echo ""
echo "DELETE plan:"
targets=()
target_zones=()
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    role="$(tn_node_role "${i}")"

    tn_teardown_selected "${inst}" || continue

    if gcloud compute instances describe "${inst}" \
        --project="${PROJECT_ID}" --zone="${zone}" --format='value(name)' >/dev/null 2>&1; then
        printf '  - %-20s %-26s role=%-9s + its boot disk\n' "${inst}" "(${zone})" "${role}"
        targets+=("${inst}")
        target_zones+=("${zone}")
    else
        printf '  - %-20s %-26s ALREADY ABSENT — nothing to do\n' "${inst}" "(${zone})"
    fi
done

if [ "${#targets[@]}" -eq 0 ]; then
    echo "  (no live instances match — nothing to delete)"
fi

cat <<EOF

PRESERVE (explicitly NOT touched by this script):
  - reserved static external IPs: ${STATIC_IP_NAMES[*]}
      -> they return to RESERVED and are re-attached by name on recreate, so DNS stays valid
  - GCP secrets: ${OBS_SECRET_NAME}, obs-grafana-admin, ${TN_ADMIN_HASH_SECRET}
  - obs VM + data disk: ${OBS_INSTANCE_NAME}, ${OBS_DATA_DISK_NAME}
  - load balancer: ${LB_FORWARDING_RULE}, ${LB_BACKEND_SERVICE}, ${LB_HEALTH_CHECK_NAME}, ${LB_GLOBAL_IP_NAME}
  - DNS records, VPC firewall rules, the WireGuard hub
  - devnet-indexer (out of scope), txgen-devnet

AFTER teardown the node keys are GONE. That is the point: deploy step 5 (devnet-keygen.sh)
mints brand-new BLS/network/execution keys, and step 6 seals them into a new genesis.
EOF

if [ "${CONFIRM}" -ne 1 ]; then
    echo ""
    echo "DRY RUN only — re-run with --yes (or FORCE=true) to actually delete."
    # Dry run is not an error: exit 0 so callers can preview without tripping set -e.
    exit 0
fi

if [ "${#targets[@]}" -eq 0 ]; then
    echo ""
    echo "Nothing to delete — exiting cleanly."
    exit 0
fi

# --- apply: parallel delete ----------------------------------------------------
# Warm gcloud's token cache serially first. Parallel gcloud invocations race on
# one-time SQLite schema migrations after an SDK update; one serial call completes
# the migration before the background jobs start (same guard create-instances.sh uses).
gcloud auth print-access-token >/dev/null || {
    echo "❌ gcloud auth failed — run 'gcloud auth login' and retry" >&2; exit 1; }

LOGS_DIR="${REPO_ROOT}/logs/instance-teardown/$(date +%Y%m%d_%H%M%S)"
mkdir -p "${LOGS_DIR}"

echo ""
echo "Deleting ${#targets[@]} instance(s) in parallel. Logs: ${LOGS_DIR}"
echo ""

pids=()
exit_statuses=()
launched_names=()
launched_logs=()

for i in "${!targets[@]}"; do
    inst="${targets[$i]}"
    zone="${target_zones[$i]}"
    log="${LOGS_DIR}/${inst}_delete.log"

    (
        # `if gcloud ...` rather than `gcloud ...; rc=$?`: this subshell inherits set -e,
        # under which a bare failing command would exit before the status could be read
        # and the FAILED marker would never reach the log.
        echo "=== deleting ${inst} (${zone}) at $(date) ==="
        if gcloud compute instances delete "${inst}" \
               --zone="${zone}" \
               --project="${PROJECT_ID}" \
               --delete-disks=all \
               --quiet 2>&1; then
            echo "=== ${inst} deleted at $(date) ==="
            exit 0
        else
            rc=$?
            echo "=== FAILED to delete ${inst} (rc=${rc}) at $(date) ==="
            exit "${rc}"
        fi
    ) > "${log}" 2>&1 &

    pids+=($!)
    launched_names+=("${inst}")
    launched_logs+=("${log}")
    echo "  started delete of ${inst} (PID: $!, log: ${log})"
done

echo ""
echo "All delete jobs launched. Waiting for completion..."
echo ""

rc=0
for i in "${!pids[@]}"; do
    wait "${pids[$i]}"
    exit_statuses+=($?)
    if [ "${exit_statuses[$i]}" -ne 0 ]; then
        echo "❌ failed to delete ${launched_names[$i]} — see ${launched_logs[$i]}" >&2
        echo "   last 10 lines:"
        tail -10 "${launched_logs[$i]}" | sed 's/^/   /'
        rc=1
    else
        echo "  ✓ deleted ${launched_names[$i]}"
    fi
done

# --- post-conditions -----------------------------------------------------------
# Assert what the operator actually cares about rather than trusting the delete's own
# success line: the instances are gone AND the static IPs survived as RESERVED with
# unchanged addresses (that is what keeps DNS correct and deploy step 4 a no-op).
echo ""
echo ">>> post-teardown verification"
for i in "${!targets[@]}"; do
    inst="${targets[$i]}"; zone="${target_zones[$i]}"
    if gcloud compute instances describe "${inst}" \
        --project="${PROJECT_ID}" --zone="${zone}" --format='value(name)' >/dev/null 2>&1; then
        echo "  ❌ ${inst} STILL EXISTS" >&2
        rc=1
    else
        echo "  ✓ ${inst} gone"
    fi
done

echo ""
echo "  reserved static IPs (expect STATUS=RESERVED, addresses unchanged):"
gcloud compute addresses list --project="${PROJECT_ID}" \
    --filter="name~'-devnet-ip$'" \
    --format='table(name, region, address, status)' | sed 's/^/    /'

echo ""
if [ "${rc}" -eq 0 ]; then
    echo "=========================================="
    echo "teardown complete. Next: ./devnet-deploy.sh --yes"
    echo "=========================================="
else
    echo "=========================================="
    echo "teardown finished WITH ERRORS — see ❌ lines above." >&2
    echo "=========================================="
fi
exit "${rc}"
