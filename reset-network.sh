#!/bin/bash
# Reset the devnet to genesis under a new chain id, preserving VMs/IPs/keys.
# Sequence: verify -> confirm -> wipe DBs -> push new genesis.yaml -> restart nodes.
source ./config.sh

EXPECTED_CHAIN_ID="${1:-32285}"   # 0x7e1d

# 1. Guard: local genesis must already carry the new chain id (hand-edit step).
if ! grep -qE "^[[:space:]]*chainId:[[:space:]]*${EXPECTED_CHAIN_ID}[[:space:]]*$" "${GENESIS_FILE}"; then
    echo "ERROR: ${GENESIS_FILE} is not set to chainId: ${EXPECTED_CHAIN_ID}"
    echo "Edit line 3 to 'chainId: ${EXPECTED_CHAIN_ID}' before resetting."
    exit 1
fi

# 2. Confirm (destructive: wipes chain state on all nodes).
echo "This WIPES all ${#INSTANCE_NAMES[@]} nodes and resets to chainId ${EXPECTED_CHAIN_ID} (0x$(printf '%x' "${EXPECTED_CHAIN_ID}"))."
if [ "${FORCE:-false}" != "true" ]; then
    read -r -p "Type 'reset' to continue: " CONFIRM
    [ "${CONFIRM}" = "reset" ] || { echo "Aborted."; exit 1; }
fi

# 3. Wipe DB state (stops containers, clears old chainId=2017 chain data).
echo "==> Wiping databases..."
./wipe-databases.sh || { echo "Wipe failed; aborting."; exit 1; }

# 4. Push the new genesis.yaml to every node (overwrites the stale on-disk copy).
echo "==> Pushing new genesis (chainId ${EXPECTED_CHAIN_ID})..."
./replace-genesis.sh || { echo "Genesis push failed; aborting."; exit 1; }

# 5. Restart every container against the new genesis.
echo "==> Restarting nodes..."
./update.sh || { echo "Restart failed; check logs."; exit 1; }

echo "Reset complete. Network is at chainId ${EXPECTED_CHAIN_ID}."
echo "Verify with: ./download-logs.sh  (or curl eth_chainId -> 0x$(printf '%x' "${EXPECTED_CHAIN_ID}"))"
