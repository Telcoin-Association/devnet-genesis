#!/usr/bin/env bash
# D4 read-only: the four reads of runbook section 8 on one host.
# usage: s8reads.sh <label> <idx>
# Writes <label>-reads.txt (allow-sync status+check with rc, nft table, timer),
# <label>-fwstatus-stdout.txt and <label>-fwstatus-stderr.txt (firewall-setup.sh status, the two streams apart).
set -u
cd /home/drtnarg/coding/telcoin/devnet-genesis || exit 2
source ./devnet-lib.sh >/dev/null 2>&1
D=tasks/l2/w3/d4; S=/opt/telcoin-node-scripts
onhost() { local i="$1"; shift; tn_iap_ssh "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "$*"; }
label=$1; i=$2
echo "== $label on ${INSTANCE_NAMES[$i]} at $(date -u +%H:%M:%SZ)"
r="echo '== tn-p2p-allow-sync status'; sudo tn-p2p-allow-sync status; echo rc=\$?;"
r+=" echo '== tn-p2p-allow-sync check'; sudo tn-p2p-allow-sync check; echo rc=\$?;"
r+=" echo '== nft list table inet tn_p2p_allow'; sudo nft list table inet tn_p2p_allow; echo rc=\$?;"
r+=" echo '== timer'; systemctl list-timers --all --no-pager telcoin-p2p-allow-sync.timer; echo rc=\$?;"
r+=" echo '== timer unit state'; systemctl is-enabled telcoin-p2p-allow-sync.timer; systemctl is-active telcoin-p2p-allow-sync.timer"
onhost "$i" "$r" >"$D/$label-reads.txt" 2>"$D/$label-reads.ssh-stderr.txt"
onhost "$i" "sudo bash $S/firewall-setup.sh --p2p-committee status </dev/null 2>/dev/null; echo rc=\$?" \
  >"$D/$label-fwstatus-stdout.txt" 2>/dev/null
onhost "$i" "sudo bash $S/firewall-setup.sh --p2p-committee status </dev/null 2>&1 >/dev/null; echo rc=\$?" \
  >"$D/$label-fwstatus-stderr.txt" 2>/dev/null
echo "done at $(date -u +%H:%M:%SZ)"
