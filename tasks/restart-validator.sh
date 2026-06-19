#!/bin/bash
# On-VM: restart the crashed telcoin container in place and verify it stays up.
# Safe after a disk-full crash with the VM still running: same image + same baked
# config (internal IP unchanged since no reboot). Existing container already has
# bounded LogConfig, so a plain start preserves it.
echo "--- df / (post-resize) ---"; df -h / | tail -1
echo "--- starting telcoin ---"; sudo docker start telcoin
for _ in $(seq 1 20); do
  [ "$(sudo docker inspect -f '{{.State.Running}}' telcoin 2>/dev/null)" = "true" ] && break
  sleep 1
done
echo "telcoin Running=$(sudo docker inspect -f '{{.State.Running}}' telcoin 2>/dev/null) Status=$(sudo docker inspect -f '{{.State.Status}}' telcoin 2>/dev/null) Exit=$(sudo docker inspect -f '{{.State.ExitCode}}' telcoin 2>/dev/null)"
echo "--- last 8 log lines ---"; sudo docker logs telcoin --tail 8 2>&1 | tail -8
echo "--- rpc block (after 4s) ---"; sleep 4
curl -s --max-time 6 -X POST -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' http://localhost:8545 \
  && echo "" || echo "(rpc not ready yet)"
