#!/usr/bin/env bash
# D4: wait on a detached driver by its pid file (kill -0), at most <max_secs>; then print rc and log tail.
# usage: waitrc.sh <name> <max_secs> [tail_lines]
set -u
D=/home/drtnarg/coding/telcoin/devnet-genesis/tasks/l2/w3/d4
n=$1; max=$2; tl=${3:-25}
pid=$(cat "$D/$n.pid"); t0=$(date +%s)
while [ ! -s "$D/$n.rc" ] && kill -0 "$pid" 2>/dev/null; do
  if (( $(date +%s) - t0 >= max )); then
    echo "STILL RUNNING pid=$pid after ${max}s at $(date -u +%H:%M:%SZ); log tail:"
    tail -n "$tl" "$D/$n.log" | grep -v -i -E 'numpy|increase the performance|pip3 install|^$'
    exit 9
  fi
  sleep 5
done
echo "EXITED pid=$pid at $(date -u +%H:%M:%SZ) rc=$(cat "$D/$n.rc" 2>/dev/null || echo MISSING)"
echo "--- log tail (numpy noise filtered):"
tail -n "$tl" "$D/$n.log" | grep -v -i -E 'numpy|increase the performance|pip3 install|^$'
