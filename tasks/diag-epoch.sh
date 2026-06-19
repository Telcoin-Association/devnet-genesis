#!/bin/bash
echo "host=$(hostname)"
h=$(curl -s --max-time 6 -X POST -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' http://localhost:8545 | grep -o '0x[0-9a-fA-F]*')
echo "evm_block=$((${h:-0x0}))"
echo "--- last 30 epoch/exec/error log lines ---"
sudo docker logs telcoin --tail 250 2>&1 \
  | grep -iE 'epoch|exec|incentive|conclude|system.?call|close|catch|sync|retriev|consensus_output|canonical|reorg|panic|fatal|stall' \
  | tail -30
