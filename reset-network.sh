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
source ./config.sh

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

# 4. Finalize: restage the (new-chainId) genesis/committee/parameters onto each node
#    and (re)start its service against the fresh genesis.
echo "==> Finalizing nodes (restage genesis chainId ${EXPECTED_CHAIN_ID} + restart)..."
./devnet-finalize.sh "${SELECTED[@]}" || { echo "Finalize failed; check logs."; exit 1; }

echo "Reset complete. Network is at chainId ${EXPECTED_CHAIN_ID}."
echo "Verify with: ./common/download-logs.sh  (or curl eth_chainId -> 0x$(printf '%x' "${EXPECTED_CHAIN_ID}"))"
