# Unit VC, verification row 12 (allowlist sync with the node down), validator 2 (i=1) — as run

Brief: tasks/l2/briefs/vc-sync-node-down.md. Raw outputs in this directory. All times UTC, 2026-11-18.

## Part A: baseline (05:01:51Z-05:02:07Z), read-only

Commands: helpers of the brief; per validator one IAP ssh running `tn_nodeMode`, `net_peerCount`,
`eth_blockNumber` against 127.0.0.1:8545; on validator 2 one more ssh for the unit files, timers,
`systemctl show telcoin`, the stateless md5, the element lines, the tool's `status` and `check`, and the
own-origin `certificate committed` lines from `/var/log/telcoin/telcoin.log` (needs sudo: the directory is
not readable by the login user). Raw: A-pubhead.txt, A-v1.txt, A-v2-rpc.txt, A-v3.txt, A-v4.txt, A-v2-host.txt.

| host | time | tn_nodeMode | net_peerCount | head | public head just before |
|---|---|---|---|---|---|
| validator 1 | 05:01:55 | CvvActive | 5 | 0x759a | 0x758b (05:01:51) / 0x759a (05:01:56) |
| validator 2 | 05:01:54 | CvvActive | 5 | 0x7597 | same |
| validator 3 | 05:01:54 | CvvActive | 5 | 0x7598 | same |
| validator 4 | 05:01:55 | CvvActive | 5 | 0x759a | same |

Public head: 0x758b (05:01:51) -> 0x759a (05:01:56) -> 0x759c (05:02:07): rising.

Validator 2 host:
- Units: `telcoin-p2p-allow-sync.service` static (the inferred name is confirmed), `telcoin-p2p-allow.service`
  enabled, `telcoin-p2p-allow-sync.timer` enabled. Timer: last 04:57:11, next 05:02:36 (about 5 min 25 s).
- `systemctl show telcoin`: ActiveEnterTimestamp=Wed 2026-11-18 04:09:18 UTC, NRestarts=0.
- Stateless md5 `52227139a722a7c8e9418f120967d095` (same as 04:15Z).
- Elements: `{ 34.7.93.35, 34.19.189.1, 34.20.254.166, 34.174.181.214, 35.236.51.63, 35.242.150.70 }` (6).
- `status` rc=0: `RESULT=unchanged LAST_RUN=1794977832 LAST_GOOD=1794977832 EPOCH=4 EPOCH_DURATION=3600
  STALE_SINCE= STALE_REASON= ALLOWED_V4=6 ALLOWED_V6=0 STATIC_V4=0 STATIC_V6=0 FLOOR=4 KEYS=5 DNS_SKIPPED=0
  UNPARSED=0 UNKNOWN_SLOTS=0 LOADED=true AGE_SECS=283 STALE=false` (+ packet counters), TOOL_VERSION=0.1.1.
- `check` rc=0: `result=ok missing_total=0 mismatch_total=0`.
- Last own-origin certificates committed (origin GgVKMyi79ZnXs7Bj2EoE4fSqDjRAyLpPXucwUQt1zXtZ): rounds 7411,
  7412 at 05:01:55.847Z, round 7413 at 05:01:56.417Z (age_ms 486-756).

## Part B: the sequence, run once (gate 05:09:06Z-05:09:15Z, sequence 05:09:16.7Z-05:10:20.0Z)

Gate (raw: B-gate.txt), all in the window: token-ok at 05:09:06Z; public head 0x7c91 (05:09:06Z) -> 0x7ca4
(05:09:15Z), rising; validators 1, 3, 4 (and 2) `CvvActive` at 05:09:09Z-05:09:11Z. Checkpoint written
"B STARTED 2026-11-18T05:09:15Z" before the launch.

Launch: one IAP ssh to validator 2 that (only if /tmp/l2-row12.log did not exist) decoded the script
(scratch copy: l2-row12.sh in the session scratchpad; the host copy is /tmp/l2-row12.sh) and ran
`sudo nohup setsid bash /tmp/l2-row12.sh </dev/null >/tmp/l2-row12.log 2>&1 &`; ssh rc=0 at 05:09:18Z.
Polled the host log until DONE; full copy: row12.log.

Transitions (from row12.log):
- 05:09:16.729Z step 1: md5 `52227139a722a7c8e9418f120967d095`, elements the six of part A.
- 05:09:16.741Z step 2: `systemctl stop telcoin`, rc 0; returned 05:09:19.408Z, `is-active=inactive` (stop took 2.7 s).
- 05:09:19.418Z step 3: `systemctl start telcoin-p2p-allow-sync.service` rc 0, finished 05:09:19.80Z.
  `systemctl show`: `Result=success`, `ExecMainStatus=3`, `ActiveState=inactive`.
  Tool journal: `result=stale reason=rpc-unreachable epoch=4 v4=6 v6=0 static=0 floor=4 keys=5 dns_skipped=0 unparsed=0`
  then `stale reason=rpc-unreachable action=kept`.
  `status` rc 0: `RESULT=stale LAST_RUN=1794978559 LAST_GOOD=1794978502 STALE_SINCE=1794978559
  STALE_REASON=rpc-unreachable ALLOWED_V4=6 KEYS=5 FLOOR=4 LOADED=true AGE_SECS=57 STALE=false`.
  `check` rc 3: `result=stale missing_total=0 mismatch_total=0` / `stale reason=rpc-unreachable`.
- 05:09:19.872Z step 4: md5 `52227139a722a7c8e9418f120967d095`, same six elements: set unchanged.
- 05:09:19.894Z step 5: sleep 60 (stopped since 05:09:19Z); 05:10:19.900Z `systemctl start telcoin` rc 0.
- 05:10:20.021Z step 6: `is-active=active`; 05:10:20.031Z DONE.
Node down 63.2 s from the stop command (60.5 s from the stop's return) to the start.

Row 12 verdict (sync part): PASS. The result is stale (`RESULT=stale`, `STALE_REASON=rpc-unreachable`, check
exits 3 with `result=stale`), the tool says `action=kept`, and the stateless md5 and the elements are the same
before and after.

## Part C: validator 2 coming back (05:10:45Z-05:11:05Z, stopped early: voting proven)

Command: a local loop (scratch copy c-loop.sh in the session scratchpad), each poll = public head, then one
IAP ssh to validator 2 that prints `systemctl is-active telcoin`, `tn_nodeMode`, `net_peerCount`,
`eth_blockNumber` from 127.0.0.1:8545 and, from `/var/log/telcoin/telcoin.log` since 05:10:19Z, the count of
`certificate committed` lines with origin GgVKMyi7..., and of those whose `created_at_ms` is after the start;
every third poll validators 1, 3, 4 `tn_nodeMode`. Exit rule: own certificates created after the start, counted
in two polls, rising. Raw: c-loop.txt.

| poll | time | is-active | tn_nodeMode | peers | v2 head | public head (read just before) | own certs created after start |
|---|---|---|---|---|---|---|---|
| 1 | 05:10:45Z | active | CvvActive | 5 | 0x7d57 | 0x7d54 (v2 3 ahead) | 48, first committed `ts=2026-11-18T05:10:29.425332066Z` |
| - | 05:10:57Z | validators 1, 3, 4: CvvActive, CvvActive, CvvActive | | | | | |
| 2 | 05:11:04Z | active | CvvActive | 5 | 0x7da7 | 0x7d93 (v2 20 ahead) | 103 |

- Unit active: 05:10:20.021Z (row12.log step 6).
- RPC answering: by 05:10:45Z at the latest (first poll; not resolved finer).
- tn_nodeMode: CvvActive at 05:10:45Z and 05:11:04Z; no other value seen.
- Head: already level at the first poll, 26 s after the start (ahead of the public head read a few seconds
  before it, which is the read-order effect the brief describes).
- First own certificate created after the start and committed: 05:10:29.425Z, 9.5 s after
  `systemctl start telcoin` (05:10:19.900Z). Count rising 48 -> 103 between 05:10:45Z and 05:11:04Z.
- Cost of the one-minute stop: about 73 s without its own certificates being committed (last before the stop
  not read precisely; stop at 05:09:16.7Z, first after start 05:10:29.4Z), i.e. the stop itself plus about
  9.5 s; not "the rest of the epoch".

### Part C, the read 6 minutes after the start (05:16:30Z; raw C-6min.txt)

- `systemctl show telcoin`: ActiveState=active, ActiveEnterTimestamp=05:10:20, NRestarts=0.
- Sync timer ran at 05:14:31Z (next 05:19:49Z); journal: `result=unchanged reason= epoch=4 v4=6 v6=0 static=0
  floor=4 keys=5 dns_skipped=0 unparsed=0`.
- `status` rc 0: `RESULT=unchanged LAST_RUN=1794978872 LAST_GOOD=1794978872 STALE_SINCE= STALE_REASON= ... STALE=false
  AGE_SECS=118`. `check` rc 0: `result=ok missing_total=0 mismatch_total=0`. Fresh again: yes.
- Stateless md5 `52227139a722a7c8e9418f120967d095`, same six elements.
- Validator 2 log since the start (mode lines, tail 15, all there were):
  - 05:10:21.299Z `telcoin-network 0.1.0 (5533ff73...) starting`
  - 05:10:23.749Z `subscriber starting in mode node_mode=CvvActive`
  - 05:10:24.039Z `subscriber starting in mode node_mode=CvvInactive`
  - 05:10:24.126Z `batch builder not started: node is in committee but not an active CVV; accepted transactions stay
    pooled until a later epoch entry starts a builder: rejoin as CvvActive, or the next epoch as a non-member that forwards`
  - 05:10:24.326Z `bulk catching up current epoch via partial pack stream (staging) epoch=4 number=22485 our_latest=22431`
  - 05:10:24.431Z WARN `demoting unreachable validator RPC endpoints from forward admission demoted=1 cooldown_secs=30`
    (forward admission, not a mode demotion)
  - 05:10:26.768Z `catching up consensus blocks last_consensus_height=22431 max_consensus_height=22486 catchup_distance=55`
  - 05:10:28.334Z `subscriber starting in mode node_mode=CvvActive`
  So: CvvInactive for about 4.3 s (05:10:24.04Z-05:10:28.33Z) while it caught up 55 consensus blocks, CvvActive
  again at 05:10:28.3Z, first own certificate committed 05:10:29.4Z.
- Public head between 05:11:52Z and 05:16:24Z (wait-pubhead.txt): 0x7e23 -> 0x816b, rising at every read.

## Part D: closing read after the epoch boundary (05:25:52Z-05:26:22Z; raw D-nodes.txt, D-v2.txt, D-committee-status.txt)

| i | host | time | tn_nodeMode | peers | head |
|---|---|---|---|---|---|
| 0 | validator-1 | 05:25:54Z | CvvActive | 5 | 0x8c54 |
| 1 | validator-2 | 05:25:53Z | Observer | 5 | 0x8c50 |
| 2 | validator-3 | 05:25:54Z | CvvActive | 5 | 0x8c54 |
| 3 | validator-4 | 05:25:56Z | CvvActive | 5 | 0x8c57 |
| 4 | observer-5 | 05:25:56Z | CvvActive | 5 | 0x8c57 |
| 5 | rpc-6 | 05:25:54Z | Observer | 5 | 0x8c54 |

Public head: 0x8c3d (05:25:52Z), 0x8c57 (05:25:56Z), 0x8c57 (05:26:06Z, a 10 s pause), then see the two reads
appended at the end of D-nodes.txt (taken at the close). Across the boundary (wait-pubhead.txt) the head rose at
every 10 s read: 0x86df (05:24:20Z) -> 0x889e (05:24:50Z) -> 0x8c3d (05:25:51Z).

Validator 2 outside the committee: `tn_nodeMode` = `Observer` (as read). Log: 05:24:52.083Z `Epoch Task Manager:
batch builder was cancelled`; 05:24:52.279Z `subscriber starting in mode node_mode=Observer`; 05:24:52.337Z new
epoch tasks with `forward-txns`. Unit active. Its builder after the rejoin in epoch 4: 05:10:28.335Z `EPOCH TASKS`
with `batch builder (critical)` (started again when it returned to CvvActive).

`./devnet-p2p-committee.sh --status` (05:26:1xZ), rc 1:
- validator-1: on, mode CvvActive, check ok, 6 IPv4 / 5 keys / floor 4, epoch 5.
- validator-2: on, mode Observer, check ok, 6 IPv4, epoch 5.
- validator-3: on, mode CvvActive, check ok, epoch 5.
- validator-4: on, mode CvvActive, `check: result=behind missing_total=0 mismatch_total=0 (exit 3)`, set still
  tagged epoch 4 -> the script prints `validator-4-devnet should be on but check is not ok` and exits 1. Same
  six sources, no missing or mismatched entry: its sync timer had not run since the 05:24:45Z boundary.

## Verdict, row 12

- Result stale with the node down: YES (`result=stale reason=rpc-unreachable`, `stale reason=rpc-unreachable
  action=kept`, `RESULT=stale`, `STALE_REASON=rpc-unreachable`, `check` exit 3).
- Set unchanged: YES (stateless md5 `52227139a722a7c8e9418f120967d095` and the six elements before, after, and
  6 minutes later).
- Node back: YES (active 05:10:20.0Z, CvvActive 05:10:28.3Z after 4.3 s CvvInactive catching up 55 consensus
  blocks, first own certificate committed 05:10:29.4Z; sync fresh again at the 05:14:31Z timer run).
- PASS. Cost of the one-minute stop: the stop itself plus about 9.5 s (about 73 s without own certificates),
  not the rest of the epoch. Chain never at risk: validators 1, 3, 4 CvvActive at every read, head rising.

## Deviations

- Launch line: added `setsid`, `</dev/null` and a guard (run only if /tmp/l2-row12.log does not exist) to the
  brief's `sudo nohup bash /tmp/l2-row12.sh > /tmp/l2-row12.log 2>&1 &`; wrapped step 3's reads in `timeout` so
  a hung read could not delay the start. The 60 s were counted from the stop's return (node stopped 60.5 s;
  63.2 s from the stop command).
- Part C ended at the second poll (05:11:05Z) because voting was proven; the 20 s / 45 s schedule did not run
  further. Part D ran at 05:25:50Z, not 05:26Z.
- Left on validator 2: /tmp/l2-row12.sh and /tmp/l2-row12.log (not removed: no other host change allowed).

## Frictions an operator on mainnet would meet

- `status` prints `RESULT=stale` and `STALE=false` together (STALE looks age-based: AGE_SECS=57 since the last
  good run). A monitor keyed on `STALE=` misses a failed sync; use `check` (exit 3) or `RESULT=`.
- The sync unit ends `Result=success` with `ExecMainStatus=3`: exit 3 counts as success to systemd, so failed-unit
  alerts never see a stale sync. And `status` exits 0 when stale; only `check` exits non-zero.
- `devnet-p2p-committee.sh --status` exits 1 for a minute or more after every epoch boundary (`check=behind` until
  each host's ~5.5 min sync timer runs), although nothing is missing or mismatched.
- The node log /var/log/telcoin/telcoin.log is not readable without sudo; RPC `tn_nodeMode` said CvvActive at
  05:10:23.7Z, 0.3 s before the node dropped to CvvInactive to catch up: the RPC mode is not proof of voting.
- Runbook row 12 as written (validator-3, `sudo tn-p2p-allow-sync`, `nft list table` with counters) would not work
  as-is: the tool is not on sudo's PATH and the counters change the md5.

## Not checked

- When RPC first answered (only bounded: by 05:10:45Z; the log has the subscriber in mode at 05:10:23.7Z).
- The time of validator 2's last own certificate before the stop (cost counted from the stop command).
- Whether validator 2 actually produced batches between 05:10:28Z and 05:24:45Z (only the builder task start).
- The other validators' logs during the 63 s (round timeouts, missed votes).
- Validator 4's allowlist after its next sync run (left `check=behind`, epoch 4).
