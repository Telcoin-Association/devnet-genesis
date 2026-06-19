#!/bin/bash
# Full recovery for a crashed (disk-full) validator: free scratch -> grow part+fs
# -> restart telcoin -> verify it stays up. Run as root:
#   gcloud compute ssh ... --command='sudo bash -s' < tasks/recover-down-node.sh
set -e
export DEBIAN_FRONTEND=noninteractive
echo "=== [$(hostname)] df before ==="; df -h / | tail -1
LOG=$(docker inspect -f '{{.LogPath}}' telcoin 2>/dev/null || true)
AVAIL_KB=$(df --output=avail / | tail -1 | tr -d ' ')
if [ -n "$LOG" ] && [ -f "$LOG" ] && [ "${AVAIL_KB:-0}" -lt 524288 ]; then
  echo "freeing scratch: truncate $LOG ($(du -h "$LOG" 2>/dev/null | cut -f1))"; truncate -s 0 "$LOG"
fi
command -v growpart >/dev/null 2>&1 || { echo "installing growpart..."; apt-get install -y cloud-guest-utils gdisk; }
ROOT_SRC=$(findmnt -no SOURCE /)
DISK_DEV=$(lsblk -no PKNAME "$ROOT_SRC")
PART_NUM=$(printf '%s' "$ROOT_SRC" | grep -o '[0-9]*$')
echo "=== growpart /dev/$DISK_DEV $PART_NUM ==="; growpart "/dev/$DISK_DEV" "$PART_NUM" || echo "growpart rc=$? (nochange?)"
echo "=== resize2fs $ROOT_SRC ==="; resize2fs "$ROOT_SRC"
echo "=== df after ==="; df -h / | tail -1
echo "=== starting telcoin ==="; docker start telcoin
for _ in $(seq 1 20); do [ "$(docker inspect -f '{{.State.Running}}' telcoin 2>/dev/null)" = "true" ] && break; sleep 1; done
echo "telcoin Running=$(docker inspect -f '{{.State.Running}}' telcoin 2>/dev/null) Status=$(docker inspect -f '{{.State.Status}}' telcoin 2>/dev/null) Exit=$(docker inspect -f '{{.State.ExitCode}}' telcoin 2>/dev/null)"
echo "=== last 8 log lines ==="; docker logs telcoin --tail 8 2>&1 | tail -8
sleep 5; echo "=== rpc block ==="
curl -s --max-time 6 -X POST -H 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' http://localhost:8545 && echo "" || echo "(rpc not ready yet)"
