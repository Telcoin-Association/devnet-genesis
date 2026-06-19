#!/bin/bash
h=$(curl -s --max-time 6 -X POST -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' http://localhost:8545 \
  | grep -o '0x[0-9a-fA-F]*'); h="${h:-0x0}"
echo "block=$((h)) ($h)  peers=$(sudo docker logs telcoin --since 30s 2>&1 | grep -oE 'connected_count=[0-9]+' | tail -1)"
echo "--- recent consensus/epoch log lines (last 90s) ---"
sudo docker logs telcoin --since 90s 2>&1 \
  | grep -iE 'quorum|certificate committed|got new consensus|re-proposing|network error|could not get the epoch|DialFailure|panic|error' \
  | tail -12
