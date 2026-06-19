#!/bin/bash
#
# devnet-wipe.sh — tn-node-deployment-aware chain wipe that PRESERVES keys.
#
# Stops the node service and removes ONLY the chain/database directories under the
# role's DATA_DIR (db, consensus-db, blobstore, static_files), so the node can be
# re-synced from genesis WITHOUT re-running keygen. The rm is enumerated (never a
# wholesale `rm -rf <DATA_DIR>`) so an identity dir can never be caught in it.
#
# PRESERVED (explicitly NOT touched):
#   <DATA_DIR>/node-keys          (BLS/network/execution keystores)
#   <DATA_DIR>/node-info.yaml     (this node's committee record)
#   <DATA_DIR>/genesis            (staged genesis/committee)
#   <DATA_DIR>/parameters.yaml    (consensus parameters)
#   /etc/telcoin/<role>/bls-passphrase   (keystore passphrase)
#
# Reaches nodes only via the lib's IAP helpers (on-node ops need root → sudo).
#
# DESTRUCTIVE: refuses to run unless --yes is passed OR FORCE=true in the env. With
# neither, it prints exactly what WOULD be wiped/preserved per node and exits 1.
# Optional instance-name subset; no args = whole fleet.
#
# Usage:
#   ./devnet-wipe.sh --yes                          # wipe all nodes
#   ./devnet-wipe.sh --yes validator-3-devnet       # wipe one (or more) by name
#   ./devnet-wipe.sh validator-3-devnet             # DRY RUN (no --yes): print plan only
#   FORCE=true ./devnet-wipe.sh                      # wipe all (env-gated)

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

# Validate any requested names against INSTANCE_NAMES.
if [ "${#SELECTED[@]}" -gt 0 ]; then
    for want in "${SELECTED[@]}"; do
        found=0
        for have in "${INSTANCE_NAMES[@]}"; do
            [ "${want}" = "${have}" ] && { found=1; break; }
        done
        [ "${found}" -eq 1 ] || { echo "❌ unknown instance '${want}' (not in INSTANCE_NAMES)" >&2; exit 1; }
    done
fi
tn_wipe_selected() {
    [ "${#SELECTED[@]}" -eq 0 ] && return 0
    local inst="$1" s
    for s in "${SELECTED[@]}"; do [ "${s}" = "${inst}" ] && return 0; done
    return 1
}

# The 4 chain/db subdirs to remove (relative to DATA_DIR). Keys etc. are preserved.
WIPE_SUBDIRS=(db consensus-db blobstore static_files)

echo "=========================================="
echo "devnet chain wipe (PRESERVES keys)"
echo "Project:   ${PROJECT_ID}"
echo "Wipes:     ${WIPE_SUBDIRS[*]} (under each node's DATA_DIR)"
echo "Preserves: node-keys, node-info.yaml, genesis, parameters.yaml, /etc/telcoin/<role>/bls-passphrase"
[ "${#SELECTED[@]}" -gt 0 ] && echo "Subset:    ${SELECTED[*]}"
[ "${CONFIRM}" -eq 1 ] && echo "Mode:      APPLY (--yes/FORCE)" || echo "Mode:      DRY RUN (no --yes) — nothing will be deleted"
echo "=========================================="

rc=0
for i in "${!INSTANCE_NAMES[@]}"; do
    inst="${INSTANCE_NAMES[$i]}"
    zone="${ZONES[$i]}"
    role="$(tn_node_role "${i}")"
    ddir="$(tn_data_dir_for_role "${role}")"
    svc="$(tn_service_for_role "${role}")"

    tn_wipe_selected "${inst}" || continue

    echo ""
    echo ">>> ${inst} (${zone}, role=${role}, service=${svc})"
    echo "    DATA_DIR: ${ddir}"
    echo "    would remove:"
    for d in "${WIPE_SUBDIRS[@]}"; do echo "      - ${ddir}/${d}"; done
    echo "    PRESERVE: ${ddir}/{node-keys,node-info.yaml,genesis,parameters.yaml}, /etc/telcoin/${role}/bls-passphrase"

    if [ "${CONFIRM}" -ne 1 ]; then
        continue
    fi

    # Build the explicit rm target list (each dir spelled out — never `rm -rf ${ddir}`).
    rm_targets=""
    for d in "${WIPE_SUBDIRS[@]}"; do rm_targets+=" '${ddir}/${d}'"; done

    # Stop the service, then remove only the enumerated chain dirs. systemctl stop
    # is a no-op if the unit is already stopped, so this is safe to re-run.
    remote_cmd="set -e; sudo systemctl stop '${svc}'; sudo rm -rf${rm_targets}"
    echo "    + ${remote_cmd}"
    if tn_iap_ssh "${inst}" "${zone}" "${remote_cmd}"; then
        echo "    ✓ wiped (keys preserved); service '${svc}' left stopped"
    else
        echo "    ❌ wipe failed on ${inst}" >&2
        rc=1
    fi
done

echo ""
if [ "${CONFIRM}" -ne 1 ]; then
    echo "DRY RUN only — re-run with --yes (or FORCE=true) to actually wipe."
    # Dry run is not an error: exit 0 so callers can preview without tripping set -e.
    exit 0
fi
if [ "${rc}" -eq 0 ]; then
    echo "=========================================="
    echo "chain wipe complete on all targeted nodes (keys preserved; services stopped)."
    echo "=========================================="
else
    echo "=========================================="
    echo "chain wipe finished WITH ERRORS — see ❌ lines above." >&2
    echo "=========================================="
fi
exit "${rc}"
