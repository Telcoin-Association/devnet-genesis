# Brief: unit VB, verification row 11 (restart a gateway, then a validator) on validator 2

Live GCP devnet (project tn-devnet), operator host xerxes, working directory
/home/drtnarg/coding/telcoin/devnet-genesis. The chain is live: committee of epoch 3 and 4 = validators 1-4;
node 5 is Active, not yet seated (its first seat is epoch 5, from 05:24:45Z, in place of validator 2). Epochs
are 3600 s; the next boundary is 04:24:45Z. The committee P2P allowlist is ON on validators 1-4 and node 5.

With four committee members, quorum is three. Your test takes ONE member (validator 2, index i=1,
`validator-2-devnet`) out for a short time. A second member out at the same time stalls the chain. So:
you touch validator 2 only, you first prove the other three are healthy, and you stop at the first doubt.

## On start
Read your checkpoint tasks/ckpt-l2-VB.md if it exists and continue from the first unfinished part. If it says
a restart was STARTED, do NOT restart again: go straight to observing. Otherwise create it (`status:` header)
and rewrite it after EACH part.

## What you may read
- tasks/runbook-l2-2026-11-17.md lines 14-51 (helpers and fleet index) and, in the section 10 table, row 11.
- Your own outputs under tasks/l2/w3/vb/.
Nothing else. Hand back rather than explore.

## Hard rules
- The ONLY state-changing commands, each at most once, both on validator 2 (i=1):
  `sudo systemctl restart telcoin-gateway` and `sudo systemctl restart telcoin`.
  No other systemctl action on any host, no ufw/nft/firewall-setup changes, no `./devnet-*.sh` except
  `./devnet-p2p-committee.sh --status` (read-only), no edits, no git add/commit/push, no gh.
- If validator 2 does not come back the way the table expects, do NOT restart it again and do not "fix"
  anything: record what you see (unit state, last 40 log lines, mode, head) and keep observing to the end of
  your window, then hand back.
- If, at ANY read, one of validators 1, 3, 4 is not "CvvActive" or the public head stops rising for 60 s:
  write it in the checkpoint at once, do nothing to any host, and hand back immediately with "CHAIN AT RISK"
  as the first words. (The owner decides; a restart by you could make it worse.)
- `gcloud auth print-access-token >/dev/null && echo token-ok` before part B; if it fails, hand back "credentials".
- Do not start part C (the validator restart) after 04:14:00Z: the node must be back up and catching up well
  before the 04:24:45Z boundary. If you are late, skip part C and say so.
- Secrets never on argv, env or logs. Budget: at most 40 tool calls, about 120 printed lines per call; save raw
  outputs under tasks/l2/w3/vb/. A single shell call may run a polling loop of up to 9 minutes (set the tool's
  timeout to 600000 ms) and should print one compact line per poll. IAP prints a NumPy warning on stderr:
  add `2>/dev/null` to reads.

## Helpers (paste at the top of each shell call)
```
cd /home/drtnarg/coding/telcoin/devnet-genesis && source ./devnet-lib.sh >/dev/null 2>&1; S=/opt/telcoin-node-scripts; RPC=https://rpc.devnet.telcoin.network
rpcj() { printf '{"jsonrpc":"2.0","id":1,"method":"%s","params":%s}' "$1" "${2:-[]}"; }
onhost() { local i="$1"; shift; tn_iap_ssh "${INSTANCE_NAMES[$i]}" "${ZONES[$i]}" "$*"; }
nodecall() { onhost "$1" "curl -s -m 10 -X POST -H 'Content-Type: application/json' --data '$(rpcj "$2" "${3:-[]}")' http://127.0.0.1:8545"; }
pubcall() { curl -s -m 10 -X POST -H 'Content-Type: application/json' --data "$(rpcj "$2" "${3:-[]}")" "$1"; }
```
Known: `tn-p2p-allow-sync` is at `/usr/local/libexec/telcoin/tn-p2p-allow-sync` (not on sudo's PATH). Heads
read one host after another differ by the blocks made in between (2 to 18 a second): compare a host with the
public head read just before it, never two sequential reads as if simultaneous. The gateway's readiness is
`curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8656/ready` on the host; its metrics are on
127.0.0.1:9655; the node's log is /var/log/telcoin/telcoin.log (needs sudo).

## Parts
A. Baseline (read-only). `tn_nodeMode`, `net_peerCount`, `eth_blockNumber` on i=0..5; public head twice 10 s
   apart; on validator 2: `systemctl show telcoin telcoin-gateway -p ActiveEnterTimestamp -p NRestarts`,
   `sudo nft list tables`, `sudo nft list table inet tn_p2p_allow | md5sum`, the allowlist `check` with its
   rc, gateway `/ready` code. All four validators must be "CvvActive" and the head rising, or you stop here.

B. Gateway restart on validator 2. In ONE ssh command: `sudo systemctl restart telcoin-gateway`, then 25 polls
   one second apart of the gateway's `/ready` code with a timestamp. Record how long it answered other than
   200 (expected 503 for about 11 s, then 200). Then from xerxes: `https://node2.devnet.telcoin.network/ready/any`
   and one `eth_chainId` through `https://node2.devnet.telcoin.network`. Then on rpc-6 (i=5): the log lines of
   the last 2 minutes that match `demot` (the forwarder sets a gateway aside for 30 s after a failure): count
   and one example. The node (telcoin) on validator 2 must show the same ActiveEnterTimestamp as in A.

C. Validator restart on validator 2 (not after 04:14:00Z). Re-check first: validators 1, 3, 4 "CvvActive",
   head rising. Write "C STARTED <UTC>" in the checkpoint. Then `onhost 1 'date -u +%FT%TZ; sudo systemctl
   restart telcoin; date -u +%FT%TZ'`. Then observe, one compact line per poll (UTC time; validator 2's
   `systemctl is-active telcoin`, `tn_nodeMode`, `net_peerCount`, its head beside the public head read just
   before; validators 1, 3, 4 `tn_nodeMode` every third poll): every 15 s for the first 3 minutes, then every
   45 s until 04:32:00Z or until validator 2 has reported "CvvActive" on three consecutive polls, whichever is
   first. Record exactly: when the unit was active again, when RPC answered, each change of `tn_nodeMode` with
   its time, how far its head was behind and when it was level, and whether it became "CvvActive" before the
   04:24:45Z boundary, at it, or not by 04:32Z.
   After it is up (once, about 2 minutes after the restart): `sudo nft list tables` (table `inet tn_p2p_allow`
   still loaded), its md5 against A's, the allowlist `check` rc, `systemctl is-active telcoin-p2p-allow-sync.timer`,
   gateway `/ready`, and from validator 2's log since the restart: the lines that say why it is or is not
   voting (grep -i -E 'CvvInactive|CvvActive|too new|catching up|epoch boundary|node mode|rejoin' | tail -15).
   Also the public side during the restart: how many 30 s set-asides rpc-6 logged (`demot`), and whether the
   public head kept rising throughout (it must).

D. Closing read: `tn_nodeMode`, `net_peerCount` on i=0..5, public head twice, `./devnet-p2p-committee.sh --status`.

## Record
tasks/l2/w3/vb/as-run.md: per part the commands, UTC times, the poll lines that show each transition, the
answers to C's "record exactly" list, deviations from the table's expectation, frictions an operator on
mainnet would meet when restarting a validator behind a gateway and a committee allowlist. Mark what you did
not check.

## Hand back
A summary, not file dumps: status (done / stopped at <part> and why / CHAIN AT RISK), the timeline of the
validator restart in six to ten lines, the gateway restart's numbers, the state all six hosts were left in,
frictions, not checked, absolute file paths.
