#!/bin/bash
# Grow boot partition + ext4 fs after the cloud disk was resized. GROW ONLY (no
# container restart) — for the running nodes (val-1, observer-5).
# Run as root: gcloud compute ssh ... --command='sudo bash -s' < tasks/resize-disk.sh
set -e
export DEBIAN_FRONTEND=noninteractive
echo "--- before ---"; df -h / | tail -1
# Free a little scratch if nearly full (truncate telcoin json-log; safe while running).
LOG=$(docker inspect -f '{{.LogPath}}' telcoin 2>/dev/null || true)
AVAIL_KB=$(df --output=avail / | tail -1 | tr -d ' ')
if [ -n "$LOG" ] && [ -f "$LOG" ] && [ "${AVAIL_KB:-0}" -lt 524288 ]; then
  echo "freeing scratch: truncate $LOG ($(du -h "$LOG" 2>/dev/null | cut -f1))"; truncate -s 0 "$LOG"
fi
command -v growpart >/dev/null 2>&1 || { echo "installing growpart..."; apt-get install -y cloud-guest-utils gdisk; }
ROOT_SRC=$(findmnt -no SOURCE /)
DISK_DEV=$(lsblk -no PKNAME "$ROOT_SRC")
PART_NUM=$(printf '%s' "$ROOT_SRC" | grep -o '[0-9]*$')
echo "--- growpart /dev/$DISK_DEV $PART_NUM ---"
growpart "/dev/$DISK_DEV" "$PART_NUM" || echo "growpart rc=$? (nochange?)"
echo "--- resize2fs $ROOT_SRC ---"
resize2fs "$ROOT_SRC"
echo "--- after ---"; df -h /
