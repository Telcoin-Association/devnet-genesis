# VB as run: verification row 11 (gateway restart, then validator restart) on validator 2

Unit VB, 2026-11-18, operator host xerxes. Raw outputs next to this file:
A-baseline.txt, B-gateway.txt, C-restart.txt (re-check, restart, polls), C-postcheck.txt, C-certs.txt,
D-closing.txt. State-changing commands run: exactly two, both on validator 2 (i=1), each once:
`sudo systemctl restart telcoin-gateway` (04:06:21Z) and `sudo systemctl restart telcoin` (04:09:15Z).

## A. Baseline (04:05:25Z to 04:06:01Z)

Per host: public head read just before, then `tn_nodeMode`, `net_peerCount`, `eth_blockNumber` on the host.

| UTC | i | host | public head | mode | peers | head |
|---|---|---|---|---|---|---|
| 04:05:28 | 0 | validator-1 | 21419 | CvvActive | 4 | 21419 |
| 04:05:31 | 1 | validator-2 | 21419 | CvvActive | 4 | 21421 |
| 04:05:35 | 2 | validator-3 | 21421 | CvvActive | 4 | 21431 |
| 04:05:40 | 3 | validator-4 | 21433 | CvvActive | 4 | 21446 |
| 04:05:45 | 4 | observer-5 | 21446 | Observer | 1 | 21453 |
| 04:05:49 | 5 | rpc-6 | 21453 | Observer | 5 | 21465 |

Public head 21465 (04:05:49) -> 21473 (04:05:59). Validator 2: telcoin ActiveEnterTimestamp 01:24:45Z,
telcoin-gateway 01:17:02Z, NRestarts 0 and 0; tables ip nat/filter, ip6 nat/filter, ip raw, inet tn_p2p_allow;
`nft list table inet tn_p2p_allow | md5sum` = 381d93a7eab2d25e53ac5ba0016efd53; allowlist `check` rc=0
(result=ok missing_total=0 mismatch_total=0); gateway /ready 200. Gate passed.

## B. Gateway restart (04:06:21Z)

`gcloud auth print-access-token` -> token-ok. One ssh: restart began 04:06:21.888, returned 04:06:22.481 rc=0,
then 25 polls of `http://127.0.0.1:8656/ready` one second apart:

```
04:06:22 000      (connection refused)
04:06:23 503 ... 04:06:27 503   (5 polls)
04:06:28 200 ... 04:06:46 200
```

Not 200 for about 6 s (1 refused + 5 x 503); 200 from 04:06:28, about 6.1 s after the restart returned.
Table expected 503 for about 11 s: it was shorter, and the first poll got a refused connection, not 503.
From xerxes at 04:06:48: `https://node2.devnet.telcoin.network/ready/any` -> 200
`{"ready":true,"submissions":true,"queries":true}`; `eth_chainId` through node2 -> 0x7e1d.
rpc-6, `demot` in the journal for the last 2 min: 0 (no example). telcoin on validator 2 still
ActiveEnterTimestamp 01:24:45Z, NRestarts 0: the node was not touched. Gateway now ActiveEnter 04:06:22Z.

## C. Validator restart (04:09:15Z)

Re-check at 04:09:00: validators 1, 3, 4 CvvActive; public head 21658 -> 21662 (8 s). Checkpoint written
"C STARTED 2026-11-18T04:09:13Z", then `onhost 1 'date; sudo systemctl restart telcoin; date'`:
04:09:15Z -> rc=0 -> 04:09:18Z.

Polls (15 s cadence; v2 = validator 2 is-active, mode, peers, head beside the public head read just before):

```
04:09:24 #0 v2 act=active mode=NA peers=NA head=NA pub=21663 lag=NA | v1=CvvActive v3=CvvActive v4=CvvActive
04:09:36 #1 v2 act=active mode=CvvActive peers=5 head=21672 pub=21671 lag=-1
04:09:50 #2 v2 act=active mode=CvvActive peers=4 head=21694 pub=21690 lag=-4
04:10:09 #3 v2 act=active mode=CvvActive peers=4 head=21718 pub=21718 lag=0 | v1=CvvActive v3=CvvActive v4=CvvActive
DONE: v2 CvvActive on 3 consecutive polls at 04:10:09
```

The brief's stop rule (three consecutive CvvActive) ended the polling at 04:10:09.

### The "record exactly" answers

- Unit active again: 04:09:18Z (systemd ActiveEnterTimestamp = ExecMainStartTimestamp = 04:09:18Z,
  NRestarts 0). The node log: the old process went NotReady at 04:09:17.0, the new one logged
  "telcoin-network 0.1.0 (5533ff73) starting" at 04:09:19.86, "starting node and launching first epoch"
  at 04:09:20.76, "creating committee from state" at 04:09:21.74.
- RPC answered: not at the 04:09:24 poll; answered at the 04:09:36 poll. So between about 04:09:24 and
  04:09:36 (21 s at most after the restart command).
- Changes of `tn_nodeMode`: no answer (RPC down) at 04:09:24 -> "CvvActive" at 04:09:36, then unchanged.
  It never showed CvvInactive or Observer. Log: "subscriber starting in mode node_mode=CvvActive" at
  04:09:22.84, certifier started at 04:09:22.84.
- Head behind: never measurably behind once RPC answered (+1 ahead of the public read just before it at
  04:09:36, +4 at 04:09:50, level at 04:10:09). The process was down about 2 to 5 s.
- CvvActive relative to the 04:24:45Z boundary: before it, at 04:09:36Z, about 21 s after the restart.
- Voting, not only the mode: since the restart, validator 2's own log committed certificates from all four
  origins at about the same rate (to 04:13:00, round 9584): 6JTxzzah 685, CgQ3xoAY 597, FjbqwQaB 708,
  GgVKMyi7 (validator 2 itself, per its certifier line) 657. It also re-proposed headers (round 8894, 9167),
  so it proposes.

### Post-check (04:11:15Z, about 2 min after the restart)

- `sudo nft list tables`: same six tables, `inet tn_p2p_allow` still loaded.
- md5 of `nft list table inet tn_p2p_allow`: fcb98ca05679e4871b7480bab4119f3a, not A's 381d93a7.... Not a
  change of rules: two reads 3 s apart at 04:11:49 also differed (fb6dc4ff vs 8dac60b6), because the table
  holds live counters (the status script shows packet counts). The stateless md5
  (`nft -s list table ...`) was 52227139a722 at 04:11:49 (37 lines); A has no stateless baseline.
- Allowlist `check` rc=0 (result=ok missing_total=0 mismatch_total=0); `telcoin-p2p-allow-sync.timer`
  active; gateway /ready 200.
- Log lines matching CvvInactive|CvvActive|too new|catching up|epoch boundary|node mode|rejoin since the
  restart: only one, "subscriber starting in mode node_mode=CvvActive" (04:09:22.84).
- Warnings since the restart: 12 (no errors). 4 x "received inbound stream from unknown peer"
  (PeerId 12D3KooWGHfeJyynQfkiYyw1mbFjUQAjfoexa6C3Rju6KedffxSE), 1 "failed to dial 24JYGVN999i3..."
  (epoch-manager), 1 "queue dropped messages while no consumer was subscribed" (primary_network_events,
  dropped=65), 2 header re-proposals, 1 suppressed-diagnostics notice. Not investigated.

### Public side during the restart

- rpc-6 set-asides (`demot`) since 04:05: journal 0, /var/log/telcoin/telcoin.log 0, syslog 1 (a kernel
  "Demotion targets for Node 0" line from 2026-11-17T23:35, unrelated). So 0 found.
- Public head kept rising: 21658 (04:09:05) -> 21662 (04:09:13) -> 21663 (04:09:24) -> 21671 (04:09:36)
  -> 21690 (04:09:50) -> 21718 (04:10:09) -> 21785 (04:11:55). Slowest stretch 1 block in 11 s
  (04:09:13 to 04:09:24, during the restart). No 60 s stop. Validators 1, 3, 4 CvvActive at every read.

## D. Closing read (04:11:55Z to 04:12:25Z)

| UTC | i | host | public head | unit | mode | peers | head |
|---|---|---|---|---|---|---|---|
| 04:11:55 | 0 | validator-1 | 21785 | active | CvvActive | 4 | 21785 |
| 04:11:58 | 1 | validator-2 | 21785 | active | CvvActive | 4 | 21785 |
| 04:12:00 | 2 | validator-3 | 21786 | active | CvvActive | 4 | 21792 |
| 04:12:03 | 3 | validator-4 | 21793 | active | CvvActive | 4 | 21802 |
| 04:12:08 | 4 | observer-5 | 21802 | active | Observer | 1 | 21805 |
| 04:12:13 | 5 | rpc-6 | 21806 | active | Observer | 5 | 21813 |

Public head 21813 (04:12:15) -> 21832 (04:12:25). `./devnet-p2p-committee.sh --status` rc=0: all four
validators P2P_COMMITTEE=on, unit active, CvvActive, check ok, table holds 6 IPv4 / 0 IPv6 sources (5 keys,
4 floor), epoch 3. Drops from unlisted sources: v1 3898, v2 2988, v3 2961, v4 2914.

## Deviations from row 11's expectation

- Gateway /ready: not 200 for about 6 s, not about 11 s, and the first second was a refused connection
  (000), not 503.
- Validator: as expected (back to CvvActive, table still loaded). It came back much faster than the brief
  allowed for: CvvActive about 21 s after the restart, head level at once.
- The md5 comparison in the brief cannot detect a change: the full listing changes every few seconds
  because of counters.

## Frictions for a mainnet operator (restart behind a gateway and a committee allowlist)

1. Zero quorum margin: with four seats, one restart leaves exactly quorum. Nothing in the tooling checks
   the other three before the restart; the operator has to (this unit did it by hand).
2. `tn_nodeMode` reads "CvvActive" about 3 s after start, from on-chain committee state, before the node
   has done anything. Proof of voting is its own certificates being committed (here, origin GgVKMyi7, 657
   since the restart), which needs a log grep and knowing the node's own key prefix.
3. Comparing the allowlist table by md5 needs `nft -s` (stateless); the plain listing has counters.
4. A load balancer polling the gateway sees a refused connection for about 1 s before the 503s.
5. `tn-p2p-allow-sync` is in /usr/local/libexec/telcoin, not on sudo's PATH.
6. `devnet-p2p-committee.sh --status`, though read-only on hosts, creates a log directory on xerxes
   (logs/20261117_221225-p2p-committee), stamped in xerxes local time, not UTC.
7. Where rpc-6 logs a set-aside is not known to this unit: no `demot` line anywhere, so "0" may mean
   "not logged here" as well as "none".

## Not checked

- The 04:24:45Z epoch boundary after the restart (polling stopped at 04:10:09 under the three-consecutive
  rule; D was read at 04:12).
- Whether rpc-6 sent any request to node2's gateway during its 6 s outage; where set-asides are logged.
- node2's public endpoint during the gateway's non-200 window (read only after it).
- The allowlist table's rules against A's (no stateless baseline from A); `check` rc=0 and the status
  counts are the evidence it is unchanged.
- The unknown peer 12D3KooWGHfe... and the "failed to dial 24JYGVN..." warning on validator 2.
- observer-5's peer count of 1; gateway-4 (i=6), not read.
