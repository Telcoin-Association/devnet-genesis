#!/usr/bin/env bash
set -euo pipefail

RECIPIENT=0x13842eee38eE22c68a0dae7ea05655DEF8d7f24B
AMOUNT=1000000000000000000000000000000
FROM=0xfeCeE4Ab07127fFf4EE4a3BA61dF5fD7B906F84C

# Pre-approved signature for the signer (r=address_padded | s=zero | v=0x01)
SIGS=0x000000000000000000000000fecee4ab07127fff4ee4a3ba61df5fd7b906f84c000000000000000000000000000000000000000000000000000000000000000001

# 1. Get the Safe transaction hash
echo "==> Getting transaction hash..."
HASH=$(make -s mint-hash RECIPIENT=$RECIPIENT AMOUNT=$AMOUNT)
echo "Hash: $HASH"

# 2. Approve the hash via Trezor (confirm on device)
echo "==> Signing hash with Trezor..."
make sign HASH=$HASH FROM=$FROM

# 3. Verify approval
echo "==> Checking approval..."
make check-approval FROM=$FROM HASH=$HASH

# 4. Execute the mint
echo "==> Submitting mint transaction..."
make mint-submit RECIPIENT=$RECIPIENT AMOUNT=$AMOUNT SIGS=$SIGS FROM=$FROM
