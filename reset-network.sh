#!/bin/bash
# Reset the devnet to genesis under a new chain id, preserving VMs/IPs/keys.
# Sequence: verify -> confirm -> wipe chain data (keys preserved) -> finalize (restage + restart).
#
# tn-node-deployment model: chain data lives under /var/lib/telcoin/<role> and the
# node runs as a systemd service, NOT the old docker-image layout under
# /home/validator/telcoin/. So this drives ./devnet-wipe.sh (enumerated chain-dir
# wipe, keys preserved) + ./devnet-finalize.sh (restage genesis/committee/params +
# restart the service) instead of common/wipe-databases.sh + common/update.sh,
# which target the legacy /home/validator paths and would silently no-op here.
# devnet-lib.sh (which sources config.sh) adds the role helpers + wait_healthy used below.
source ./devnet-lib.sh

EXPECTED_CHAIN_ID="${1:-32285}"   # 0x7e1d
shift || true                      # remaining args (if any) = optional instance-name subset
SELECTED=("$@")

# 1. Guard: local genesis must already carry the new chain id (hand-edit step).
if ! grep -qE "^[[:space:]]*chainId:[[:space:]]*${EXPECTED_CHAIN_ID}[[:space:]]*$" "${GENESIS_FILE}"; then
    echo "ERROR: ${GENESIS_FILE} is not set to chainId: ${EXPECTED_CHAIN_ID}"
    echo "Edit line 3 to 'chainId: ${EXPECTED_CHAIN_ID}' before resetting."
    exit 1
fi

# 2. Confirm (destructive: wipes chain state). Default targets all nodes; an
#    optional instance-name subset narrows it (passed through to both sub-scripts).
if [ "${#SELECTED[@]}" -gt 0 ]; then
    SCOPE_DESC="${#SELECTED[@]} node(s): ${SELECTED[*]}"
else
    SCOPE_DESC="all ${#INSTANCE_NAMES[@]} nodes"
fi
echo "This WIPES ${SCOPE_DESC} and resets to chainId ${EXPECTED_CHAIN_ID} (0x$(printf '%x' "${EXPECTED_CHAIN_ID}"))."
if [ "${FORCE:-false}" != "true" ]; then
    read -r -p "Type 'reset' to continue: " CONFIRM
    [ "${CONFIRM}" = "reset" ] || { echo "Aborted."; exit 1; }
fi

# 3. Wipe chain data (stops the service, clears db/consensus-db/blobstore/static_files;
#    PRESERVES node-keys, node-info.yaml, genesis, parameters.yaml, bls-passphrase).
echo "==> Wiping chain data (keys preserved)..."
./devnet-wipe.sh --yes "${SELECTED[@]}" || { echo "Wipe failed; aborting."; exit 1; }

# 4. Finalize: restage the (new-chainId) genesis/committee/parameters onto each node and
#    (re)start its service against the fresh genesis — validators first, observer LAST, each
#    gated on wait_healthy (active + :43174 responding) before the next, so a genesis reset
#    comes online VERIFIED rather than fire-and-forget. The endpoint gate works pre-quorum:
#    the healthcheck listener binds at node startup, before consensus advances.
echo "==> Finalizing nodes (restage genesis chainId ${EXPECTED_CHAIN_ID} + restart), health-gated..."

# Indices to finalize: all nodes, or the SELECTED instance-name subset (same scope as the wipe).
reset_indices() {
    local i s
    if [ "${#SELECTED[@]}" -eq 0 ]; then
        for i in "${!INSTANCE_NAMES[@]}"; do printf '%s\n' "$i"; done
        return 0
    fi
    for i in "${!INSTANCE_NAMES[@]}"; do
        for s in "${SELECTED[@]}"; do
            [ "${s}" = "${INSTANCE_NAMES[$i]}" ] && { printf '%s\n' "$i"; break; }
        done
    done
}
mapfile -t RESET_IDX < <(reset_indices)

finalize_and_gate() {  # <index> — finalize one node, then gate on endpoint health.
    local i="$1" inst="${INSTANCE_NAMES[$i]}" zone="${ZONES[$i]}" role svc
    role="$(tn_node_role "$i")"; svc="$(tn_service_for_role "$role")"
    echo "--> finalize ${inst} (role=${role}, service=${svc})"
    ./devnet-finalize.sh "${inst}" || { echo "Finalize failed on ${inst}; check logs."; return 1; }
    wait_healthy "${inst}" "${zone}" "${svc}" || { echo "${inst} did not come back healthy; aborting."; return 1; }
}

for i in "${RESET_IDX[@]}"; do
    [ "$(tn_node_role "$i")" = "validator" ] || continue
    finalize_and_gate "$i" || exit 1
done
for i in "${RESET_IDX[@]}"; do
    [ "$(tn_node_role "$i")" = "observer" ] || continue
    finalize_and_gate "$i" || exit 1
done

echo "Reset complete. Network is at chainId ${EXPECTED_CHAIN_ID}."
echo "Verify with: ./common/download-logs.sh  (or curl eth_chainId -> 0x$(printf '%x' "${EXPECTED_CHAIN_ID}"))"
