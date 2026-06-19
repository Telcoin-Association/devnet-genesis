#!/bin/bash
# Read-only health diagnosis: telcoin container state, crash reason, block height.
echo "--- telcoin container state (incl. stopped) ---"
sudo docker ps -a --filter name=telcoin --format '{{.Names}} | status={{.Status}}'
echo "--- telcoin inspect ---"
sudo docker inspect -f 'status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} finished={{.State.FinishedAt}}' telcoin 2>/dev/null || echo "(no telcoin container object)"
echo "--- telcoin last 12 log lines (crash reason?) ---"
sudo docker logs telcoin --tail 12 2>&1 | tail -12
echo "--- eth_blockNumber (local rpc) ---"
curl -s --max-time 6 -X POST -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' http://localhost:8545 \
  && echo "" || echo "(rpc unreachable -> telcoin not serving)"
