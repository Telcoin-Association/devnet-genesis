#!/bin/bash
echo "host=$(hostname) — restarting telcoin (was stuck at epoch 233)"
sudo docker restart telcoin >/dev/null 2>&1 && echo "restart issued"
echo "waiting 60s for epoch catchup..."
sleep 60
h=$(curl -s --max-time 6 -X POST -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' http://localhost:8545 | grep -o '0x[0-9a-fA-F]*')
echo "evm_block=$((${h:-0x0}))  (healthy nodes at 266)"
echo "--- epoch / catchup signals (last 35s) ---"
sudo docker logs telcoin --since 35s 2>&1 \
  | grep -iE 'epoch=[0-9]|InvalidEpoch|ours: [0-9]|retrieve|caught up|catchup|certificate committed|quorum reached' | tail -12
