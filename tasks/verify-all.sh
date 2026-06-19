#!/bin/bash
# Read-only verification: disk, container health, bounded logging, block progress.
echo "df:        $(df -h / | tail -1 | awk '{print $2" total, "$3" used, "$5}')"
echo "telcoin:   $(sudo docker inspect -f '{{.State.Status}} (exit {{.State.ExitCode}}, since {{.State.StartedAt}})' telcoin 2>/dev/null)"
echo "alloy:     $(sudo docker inspect -f '{{.State.Status}}' alloy 2>/dev/null)"
echo "LogConfig: $(sudo docker inspect -f '{{json .HostConfig.LogConfig}}' telcoin 2>/dev/null)"
rpc() { curl -s --max-time 6 -X POST -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' http://localhost:8545 \
  | grep -o '0x[0-9a-fA-F]*'; }
b1="$(rpc)"; b1="${b1:-0x0}"; sleep 8; b2="$(rpc)"; b2="${b2:-0x0}"
echo "block:     $b1 -> $b2  (dec $((b1)) -> $((b2)))  [pre-halt was 265]"
