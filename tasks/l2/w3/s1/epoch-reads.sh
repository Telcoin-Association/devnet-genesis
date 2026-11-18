#!/usr/bin/env bash
# Read-only: what each validator knows about node 5 right now (launch 2, runbook section 9).
# Usage (from the repo root): bash tasks/l2/w3/s1/epoch-reads.sh [label]
# Saves the four snapshots under tasks/l2/w3/s1/snaps/ and prints one block per validator:
# the snapshot's epoch, node 5's entry (slots, source, admitted) in the primary swarm, the
# allowlist check's exit code and whether node 5's address is in the nft set; then node 5's
# own mode, head and peer count. Changes nothing on any host.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." || exit 1
# shellcheck source=/dev/null
source ./devnet-lib.sh >/dev/null 2>&1
label="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"
out="tasks/l2/w3/s1/snaps"; mkdir -p "${out}"
NODE5_PEER="$(sed -n 's#.*network_address: /ip4/[0-9.]*/udp/49590/quic-v1/p2p/\(12D3[A-Za-z0-9]*\).*#\1#p' genesis/observers/node5.yaml | head -1)"
NODE5_IP="$(sed -n 's#.*network_address: /ip4/\([0-9.]*\)/udp/49590/.*#\1#p' genesis/observers/node5.yaml | head -1)"
body() { printf '{"jsonrpc":"2.0","id":1,"method":"%s","params":[]}' "$1"; }
echo "== $(date -u +%FT%TZ) label=${label} node5 peer=${NODE5_PEER} ip=${NODE5_IP}"
for i in 0 1 2 3; do
    inst="${INSTANCE_NAMES[$i]}"
    f="${out}/snap-${inst}-${label}.json"
    r="$(tn_iap_ssh "${inst}" "${ZONES[$i]}" "curl -s -m 10 -X POST -H 'Content-Type: application/json' --data '$(body tn_admissionSnapshot)' http://127.0.0.1:8545 > /tmp/l2-snap.json; echo SNAPRC=\$?; cat /tmp/l2-snap.json; echo; echo ---; sudo /usr/local/libexec/telcoin/tn-p2p-allow-sync check >/dev/null 2>&1; echo CHECKRC=\$?; echo NFTHITS=\$(sudo nft list table inet tn_p2p_allow 2>/dev/null | grep -c -F '${NODE5_IP}'); echo NFTELEMS=\$(sudo nft list table inet tn_p2p_allow 2>/dev/null | grep -o -E '([0-9]{1,3}\.){3}[0-9]{1,3}' | sort -u | tr '\n' ' ')" 2>/dev/null </dev/null)"
    printf '%s\n' "${r}" | sed -n '2p' > "${f}"
    printf '%s ' "${inst}"
    printf '%s\n' "${r}" | grep -E '^(CHECKRC|NFTHITS|NFTELEMS)=' | tr '\n' ' '
    echo
    python3 - "${f}" "${NODE5_PEER}" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))["result"]
except Exception as e:
    print("   snapshot unreadable:", e); sys.exit(0)
for sw in d["swarms"]:
    a = sw["admission"]
    hit = [e for e in sw["entries"] if sys.argv[2] in e.get("peer_id", "") or any("35.242.150.70" in m for m in e.get("multiaddrs", []))]
    desc = "; ".join("slots=%s source=%s admitted=%s ts=%s" % (",".join(e["slots"]), e["source"], e["admitted"], e.get("record_timestamp")) for e in hit) or "no entry"
    print("   %-9s epoch=%s effective=%s fallback=%s resolved=%s required=%s connected=%s entries=%d | node5: %s" % (
        sw["network"], a["epoch"], a["effective"], a["fallback"], a["resolved_current"], a["required_current"], a["connected_current"], len(sw["entries"]), desc))
PY
done
printf 'observer-5: '
tn_iap_ssh "${INSTANCE_NAMES[4]}" "${ZONES[4]}" "for m in tn_nodeMode eth_blockNumber net_peerCount; do curl -s -m 10 -X POST -H 'Content-Type: application/json' --data '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"'\$m'\",\"params\":[]}' http://127.0.0.1:8545 | sed 's/.*\"result\":\\(.*\\)}/\\1/'; echo -n ' '; done" 2>/dev/null </dev/null
echo
