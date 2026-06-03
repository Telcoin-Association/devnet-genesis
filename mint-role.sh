#!/usr/bin/env bash
set -euo pipefail

# Constants
SAFE="0x00000000000000000000000000000000000007a0"
TEL="0x00000000000000000000000000000000000007e1"
STABLECOIN_MANAGER="0x981be5999e322cb3f21511d043e8c314fda5da55"
RPC="https://node3.telcoin.network"
FROM="${FROM:-0xfeCeE4Ab07127fFf4EE4a3BA61dF5fD7B906F84C}"
ZERO_ADDR="0x0000000000000000000000000000000000000000"

# Pre-approved signature: 12 zero bytes + address + 32 zero bytes + 0x01
FROM_LOWER=$(echo "${FROM#0x}" | tr '[:upper:]' '[:lower:]')
SIG="0x000000000000000000000000${FROM_LOWER}000000000000000000000000000000000000000000000000000000000000000001"

# Step 1: Pre-check — exit early if already granted
echo "==> Checking if StablecoinManager already has mint role..."
HAS_ROLE=$(cast call "$TEL" "hasMintRole(address)(bool)" "$STABLECOIN_MANAGER" --rpc-url "$RPC")
if [ "$HAS_ROLE" = "true" ]; then
    echo "Mint role already granted. Nothing to do."
    exit 0
fi
echo "Mint role not yet granted. Proceeding..."

# Step 2: Fetch Safe nonce
echo ""
echo "==> Fetching Safe nonce..."
NONCE=$(cast call "$SAFE" "nonce()(uint256)" --rpc-url "$RPC")
echo "Nonce: $NONCE"

# Step 3: Fetch + display threshold (sanity check)
echo ""
echo "==> Fetching Safe threshold..."
THRESHOLD=$(cast call "$SAFE" "getThreshold()(uint256)" --rpc-url "$RPC")
echo "Threshold: $THRESHOLD"
if [ "$THRESHOLD" != "1" ]; then
    echo "WARNING: Threshold is $THRESHOLD (not 1). This script only handles single-signer approval."
    echo "Additional approvals would be required. Exiting."
    exit 1
fi

# Step 4: Generate calldata for grantMintRole(address)
echo ""
echo "==> Generating grantMintRole calldata..."
CALLDATA=$(cast calldata "grantMintRole(address)" "$STABLECOIN_MANAGER")
echo "Calldata: $CALLDATA"

# Step 5: Compute Safe transaction hash
echo ""
echo "==> Computing Safe transaction hash..."
TX_HASH=$(cast call "$SAFE" \
    "getTransactionHash(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,uint256)(bytes32)" \
    "$TEL" 0 "$CALLDATA" 0 0 0 0 \
    "$ZERO_ADDR" "$ZERO_ADDR" "$NONCE" \
    --rpc-url "$RPC")
echo "Transaction hash: $TX_HASH"

# Step 6: approveHash via Trezor
echo ""
echo "==> Approving hash with Trezor (confirm on device)..."
cast send "$SAFE" "approveHash(bytes32)" "$TX_HASH" \
    --rpc-url "$RPC" --from "$FROM" --trezor

# Step 7: Verify approval
echo ""
echo "==> Verifying approval..."
APPROVED=$(cast call "$SAFE" "approvedHashes(address,bytes32)(uint256)" "$FROM" "$TX_HASH" --rpc-url "$RPC")
if [ "$APPROVED" != "1" ]; then
    echo "ERROR: Hash not approved. approvedHashes returned: $APPROVED"
    exit 1
fi
echo "Hash approved."

# Step 8 + 9: execTransaction via Trezor
echo ""
echo "==> Executing grantMintRole via Safe (confirm on device)..."
cast send "$SAFE" \
    "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)(bool)" \
    "$TEL" 0 "$CALLDATA" 0 0 0 0 \
    "$ZERO_ADDR" "$ZERO_ADDR" "$SIG" \
    --rpc-url "$RPC" --from "$FROM" --trezor

# Step 10: Verify mint role was granted
echo ""
echo "==> Verifying mint role..."
HAS_ROLE=$(cast call "$TEL" "hasMintRole(address)(bool)" "$STABLECOIN_MANAGER" --rpc-url "$RPC")
echo "hasMintRole($STABLECOIN_MANAGER): $HAS_ROLE"
if [ "$HAS_ROLE" = "true" ]; then
    echo "Mint role successfully granted!"
else
    echo "ERROR: Mint role was NOT granted. Check transaction logs."
    exit 1
fi
