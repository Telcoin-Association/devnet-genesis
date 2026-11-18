#!/usr/bin/env bash
# D4 read-only probe. usage: probe.sh <label> <rounds> <gap_secs> <idx...>
# Per round: public head, then per host (parallel, over IAP) tn_nodeMode, net_peerCount,
# eth_blockNumber, tn_latestConsensusHeader.number, NRestarts of the telcoin unit.
# Raw answers in raw/<label>-r<n>-i<i>.txt; one summary line per host on stdout and in <label>.txt.
set -u
cd /home/drtnarg/coding/telcoin/devnet-genesis || exit 2
source ./devnet-lib.sh >/dev/null 2>&1
D=tasks/l2/w3/d4; RPC=https://rpc.devnet.telcoin.network
mkdir -p "$D/raw"
rpcj() { printf '{"jsonrpc":"2.0","id":1,"method":"%s","params":%s}' "$1" "${2:-[]}"; }
onhost() { local i="$1"; shift; tn_iap_ssh "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "$*"; }
pubcall() { curl -s -m 10 -X POST -H 'Content-Type: application/json' --data "$(rpcj "$2" "${3:-[]}")" "$1"; }
h2d() { local x="$1"; if [[ "$x" =~ ^0x[0-9a-fA-F]+$ ]]; then echo $((16#${x#0x})); else echo "$x"; fi; }
field() { awk -v h="== $2" '$0==h{getline; print; exit}' "$1"; }
label=$1; rounds=$2; gap=$3; shift 3
remote=""
for m in tn_nodeMode net_peerCount eth_blockNumber tn_latestConsensusHeader; do
  remote+="echo '== $m'; curl -s -m 10 -X POST -H 'Content-Type: application/json' --data '$(rpcj "$m")' http://127.0.0.1:8545; echo; "
done
remote+="echo '== NRestarts'; systemctl show -p NRestarts --value telcoin"
for ((r = 1; r <= rounds; r++)); do
  ts=$(date -u +%H:%M:%SZ)
  pub=$(pubcall "$RPC" eth_blockNumber | jq -r '.result // "?"' 2>/dev/null)
  for i in "$@"; do
    ( onhost "$i" "$remote" >"$D/raw/$label-r$r-i$i.txt" 2>/dev/null ) &
  done
  wait
  te=$(date -u +%H:%M:%SZ)
  echo "-- $label round $r $ts..$te public_head=$(h2d "$pub")" | tee -a "$D/$label.txt"
  for i in "$@"; do
    f="$D/raw/$label-r$r-i$i.txt"
    mode=$(field "$f" tn_nodeMode | jq -r '.result // .error.message // "?"' 2>/dev/null)
    peers=$(field "$f" net_peerCount | jq -r '.result // .error.message // "?"' 2>/dev/null)
    head=$(field "$f" eth_blockNumber | jq -r '.result // .error.message // "?"' 2>/dev/null)
    ch=$(field "$f" tn_latestConsensusHeader | jq -r '.result.number // .error.message // "?"' 2>/dev/null)
    nr=$(field "$f" NRestarts)
    printf '%s i%d %-20s mode=%-10s peers=%s head=%s chdr=%s nrestarts=%s\n' "$ts" "$i" "${INSTANCE_NAMES[$i]}" \
      "${mode:-NOANSWER}" "$(h2d "${peers:-?}")" "$(h2d "${head:-?}")" "${ch:-?}" "${nr:-?}" | tee -a "$D/$label.txt"
  done
  if ((r < rounds)); then sleep "$gap"; fi
done
