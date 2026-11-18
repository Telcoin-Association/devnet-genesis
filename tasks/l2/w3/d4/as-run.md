# D4 as-run: step 20, committee P2P allowlist (devnet launch 2, 2026-11-18 UTC)

Result: all four parts passed. No stop condition fired. No kill switch was run.
End state: allowlist ON on validator-1..4 and observer-5. rpc-6 was not touched (the driver refuses an `rpc` target
without `--allow-rpc`). gateway-4 has no node.

Address map (gcloud, 02:27Z; no VM has an external IPv6):
| external IPv4 | host |
|---|---|
| 35.236.51.63 | validator-1-devnet (10.168.0.21) |
| 34.174.181.214 | validator-2-devnet (10.206.0.3) |
| 34.19.189.1 | validator-3-devnet (10.162.0.49) |
| 34.7.93.35 | validator-4-devnet (10.164.0.11) |
| 35.242.150.70 | observer-5-devnet (10.154.0.15) |
| 34.20.254.166 | rpc-6-devnet (10.168.0.27) |

All times UTC. Raw files are in this directory (`*.log`, `*.txt`, `raw/`). Helper scripts (read-only):
`probe.sh` (mode/peers/head/consensus header/NRestarts per host, plus the public head), `s8reads.sh`, `waitrc.sh`.

## A. Baseline (read-only), 02:26:59Z-02:27:41Z

- `gcloud auth print-access-token` -> token-ok.
- Public head 2483 (02:27:00Z), then 2500 (02:27:10Z): rising.
- `./devnet-p2p-committee.sh --status` 02:27:10Z-02:27:32Z, **rc=0** (`A-status.log`). First time this output was seen
  with everything off. Per validator:
  ```
  >>> validator-1-devnet (us-west2-a, validator): status
      state: P2P_COMMITTEE=off unit=active mode=CvvActive head=2511
      check: no result line (exit 1)
      ->  P2P committee allowlist: off (sudo bash /opt/telcoin-node-scripts/firewall-setup.sh --p2p-committee on turns it on)
  P2P_COMMITTEE_STATUS validator-1-devnet state=off check=n/a accept=? drop=?
  ```
  validator-2/3/4 the same (heads 2513, 2517, 2517).
- Fleet 02:27:34Z (`A-fleet.txt`): validator-1..4 `CvvActive` peers 4; observer-5 `Observer` peers 1; rpc-6 `Observer`
  peers 5; all heads 2518; consensus headers 6258-6260; NRestarts 0 on all six.

## B. Canary, validator-1

- 02:27:54Z token-ok, launched `./devnet-p2p-committee.sh --yes node1` (`b-node1.log`). **rc=0**, done by 02:28:49Z
  (about 55 s). Driver log dir `logs/20261117_202754-p2p-committee` (local-time stamp, see frictions).
- Key lines:
  ```
  committee whole (0s): node1=CvvActive@2531 node2=CvvActive@2531 node3=CvvActive@2531 node4=CvvActive@2532
  before: unit=active ufw=active nft=yes P2P_COMMITTEE=off mode=CvvActive head=2542
  snapshot authoritative (0s): epoch=2 effective=Closed fallback=null
    |   ->  Installed tn-p2p-allow-sync v0.1.1 as /usr/local/libexec/telcoin/tn-p2p-allow-sync.
    |   [OK]  P2P committee mode is on: only the sources the allowlist lists reach UDP 49590 and 49594 (epoch 2: 5 IPv4 and 0 IPv6 sources (4 keys, 4 floor, 0 static)).
  on: rc 0
  check: result=ok missing_total=0 mismatch_total=0 (exit 0)
  … 0s/60s: heads 2598..2615 differ by more than 5 baseline head=2615 (highest after the change); validator-1-devnet must pass it
  committee whole (12s): node1=CvvActive@2682 node2=CvvActive@2685 node3=CvvActive@2685 node4=CvvActive@2687 (head 2682 > baseline 2615)
  P2P_COMMITTEE validator-1-devnet on epoch=2 v4=5 v6=0 keys=4 check=ok mode=CvvActive head=2682
  ```
- Section 8 reads on validator-1, 02:28:55Z-02:29:14Z (`B-v1-reads.txt`, `B-v1-allowsync.txt`,
  `B-v1-fwstatus-stdout.txt`, `B-v1-fwstatus-stderr.txt`):
  - `sudo tn-p2p-allow-sync status` and `sudo tn-p2p-allow-sync check` as written: **rc=1, `sudo: tn-p2p-allow-sync:
    command not found`**. The tool is at `/usr/local/libexec/telcoin/tn-p2p-allow-sync` (not on sudo's PATH). With the
    full path: `status` rc=0 (`RESULT=unchanged EPOCH=2 EPOCH_DURATION=3600 ALLOWED_V4=5 ALLOWED_V6=0 STATIC_V4=0
    FLOOR=4 KEYS=4 LOADED=true STALE=false AGE_SECS=57`, counters accept 10179 / drop 60); `check` rc=0
    `result=ok missing_total=0 mismatch_total=0`.
  - `firewall-setup.sh --p2p-committee status`: everything on **stdout**, rc=0; **stderr empty**. Stdout:
    ```
    [OK]  Running as root
    [OK]  P2P committee allowlist: on; table inet tn_p2p_allow holds 5 IPv4 and 0 IPv6 sources (4 keys, 4 floor), epoch 2
    ->  Last sync: unchanged; last good one 44s ago
    ->  P2P committee allowlist counters: 8193 packets accepted from listed sources, 60 dropped from others
    [OK]  P2P committee allowlist sync: telcoin-p2p-allow-sync.timer enabled and active
    ```
  - `nft list table inet tn_p2p_allow`: set `allow_v4` = 34.7.93.35 (validator-4), 34.19.189.1 (validator-3),
    34.20.254.166 (rpc-6), 34.174.181.214 (validator-2), 35.236.51.63 (validator-1). **validator-1's own address is
    listed; node 5's (35.242.150.70) is not.** `allow_v6`, `static_v4`, `static_v6` empty. Chain `input` priority -20,
    policy accept; UDP 49590/49594 accepted from the sets, else counted and dropped.
  - Timer: `NEXT Wed 2026-11-18 02:33:24 UTC (4min 24s), LAST 02:28:19 UTC`, enabled + active. It did fire: at
    02:35Z validator-1's LAST was 02:33:52Z.
- Health of validator-1 (`B-health.txt`):
  | read | mode | peers | head | cons. header | rpc-6 peers | obs-5 peers |
  |---|---|---|---|---|---|---|
  | 02:29:17Z | CvvActive | 4 | 2720 | 6428 | 5 | 2 |
  | 02:30:07Z | CvvActive | 4 | 2932 | 6511 | 5 | 2 |
  | 02:30:56Z | CvvActive | 4 | 3132 | 6593 | 5 | 2 |
  PASS. rpc-6 kept 5 peers and the same head as validator-1 (2720/2932/3132); which peers rpc-6 holds was not listed.

## C. Validators 2-4: `./devnet-deploy.sh --yes --only 20`

- 02:31:16Z token-ok, launched (`c-only20.log`). **rc=0**. The deploy printed first:
  `log: /home/drtnarg/coding/telcoin/devnet-genesis/logs/20261118_023116-deploy/deploy.log`; then
  `## step 20 done (190 s)`; driver log dir `logs/20261117_203116-p2p-committee`.
- `P2P_COMMITTEE` lines, verbatim:
  ```
  P2P_COMMITTEE validator-1-devnet on epoch=2 v4=5 v6=0 keys=4 check=ok mode=CvvActive head=3432
  P2P_COMMITTEE validator-2-devnet on epoch=2 v4=5 v6=0 keys=4 check=ok mode=CvvActive head=3604
  P2P_COMMITTEE validator-3-devnet on epoch=2 v4=5 v6=0 keys=4 check=ok mode=CvvActive head=3778
  P2P_COMMITTEE validator-4-devnet on epoch=2 v4=5 v6=0 keys=4 check=ok mode=CvvActive head=4088
  ```
  validator-1: `already-on: .node-meta has P2P_COMMITTEE=on; 'on' resyncs it (no snapshot wait; steps 3-5 still run)`,
  `P2P committee mode is on already; syncing it.` Each of 2/3/4: `snapshot authoritative (0s): epoch=2
  effective=Closed fallback=null`, `on: rc 0`, `check: result=ok …`, committee whole after 12 s / 30 s / 13 s
  (validator-1's resync: 25 s).
- `./devnet-p2p-committee.sh --status` 02:34:46Z, **rc=0** (`C-status.log`):
  ```
  P2P_COMMITTEE_STATUS validator-1-devnet state=on check=ok accept=72920 drop=420
  P2P_COMMITTEE_STATUS validator-2-devnet state=on check=ok accept=28603 drop=132
  P2P_COMMITTEE_STATUS validator-3-devnet state=on check=ok accept=24981 drop=100
  P2P_COMMITTEE_STATUS validator-4-devnet state=on check=ok accept=15168 drop=74
  ```
- Per validator 02:35:11Z (`C-v1..4-check.txt`): bare `sudo tn-p2p-allow-sync check` = command not found on all four;
  full path `check` rc=0 `result=ok missing_total=0 mismatch_total=0` on all four; nft `allow_v4` 5 elements on each,
  the same five (validator-1..4 + rpc-6). Timers next 02:39:08Z / 02:37:33Z / 02:38:05Z / 02:39:12Z.
- Public head 4551 (02:35:19Z) -> 4732 (02:35:29Z).
- Fleet (`C-fleet.txt`):
  | host | 02:35:29Z mode / peers / head | 02:36:35Z mode / peers / head |
  |---|---|---|
  | validator-1 | CvvActive / 4 / 4780 | CvvActive / 4 / 5241 |
  | validator-2 | CvvActive / 4 / 4770 | CvvActive / 4 / 5241 |
  | validator-3 | CvvActive / 4 / 4787 | CvvActive / 4 / 5241 |
  | validator-4 | CvvActive / 4 / 4809 | CvvActive / 4 / 5241 |
  | observer-5 | Observer / 3 / 4634 | Observer / 1 / 5240 |
  | rpc-6 | Observer / 5 / 4788 | Observer / 5 / 5241 |
  NRestarts 0 on all six. PASS.

## D. Node 5 (observer, before staking): `./devnet-p2p-committee.sh --yes node5`

- 02:37:01Z token-ok, launched (`d-node5.log`). Outcome: **rc=0 with mode=Observer** (02:38:47Z, about 106 s). Driver log
  dir `logs/20261117_203701-p2p-committee`. Last lines:
  ```
  before: unit=active ufw=active nft=yes P2P_COMMITTEE=off mode=Observer head=5249
  snapshot authoritative (0s): epoch=2 effective=Closed fallback=null
    |   [OK]  P2P committee mode is on: only the sources the allowlist lists reach UDP 49590 and 49594 (epoch 2: 5 IPv4 and 0 IPv6 sources (5 keys, 4 floor, 0 static)).
  on: rc 0
  check: result=ok missing_total=0 mismatch_total=0 (exit 0)
  [OK]  P2P committee allowlist: on; table inet tn_p2p_allow holds 5 IPv4 and 0 IPv6 sources (5 keys, 4 floor), epoch 2
  ->  P2P committee allowlist counters: 211 packets accepted from listed sources, 0 dropped from others
  … 0s/60s: heads 5288..5423 differ by more than 5 baseline head=5423 (highest after the change); observer-5-devnet must pass it
  … 13s/60s: heads 5438..5454 differ by more than 5
  … 26s/60s: heads 5443..5495 differ by more than 5
  … 38s/60s: heads 5443..5617 differ by more than 5
  … 51s/60s: heads 5443..5638 differ by more than 5
  committee whole (63s): node1=CvvActive@5665 node2=CvvActive@5665 node3=CvvActive@5666 node4=CvvActive@5667 node5=Observer@5667 (head 5667 > baseline 5423)
  P2P_COMMITTEE observer-5-devnet on epoch=2 v4=5 v6=0 keys=5 check=ok mode=Observer head=5667
  ```
  The host stuck at 5443 for about 25 s was node 5 (`node5=Observer@5443` in the driver's log dir). It passed in the
  round that started at 51 s and ended at 63 s.
- Node 5 reads 02:39:00Z (`D-n5-reads.txt`, `D-n5-fwstatus-stdout.txt`): full-path `status` rc=0 (`RESULT=unchanged
  EPOCH=2 ALLOWED_V4=5 ALLOWED_V6=0 FLOOR=4 KEYS=5 STALE=false COUNTER_DROP_PACKETS=0`); `check` rc=0
  `result=ok missing_total=0 mismatch_total=0`; set `allow_v4` = the same five: validator-1..4 + rpc-6 (node 5's own
  address is not in its own set). Timer next 02:42:33Z. fw status stdout: on, 5 IPv4 (5 keys, 4 floor), last sync
  unchanged 109 s ago, 2618 accepted / 0 dropped, timer enabled and active, rc=0.
- Node 5 health (`D-health.txt`, `D-health2.txt`):
  | read | node 5 peers | node 5 head | validator-1 head | node 5 / v1 cons. header |
  |---|---|---|---|---|
  | 02:39:14Z | 2 | 5682 | 5812 (130 ahead) | 7431 / 7429 |
  | 02:40:21Z | 1 | 5899 | 5899 | 7541 / 7540 |
  | 02:40:42Z | 4 | 6020 | 6020 | 7572 / 7572 |
  | 02:41:17Z | 1 | 6021 | 6053 (32 ahead) | 7626 / 7633 |
  | 02:41:54Z | 4 | 6192 | 6195 | 7699 / 7697 |
  Peers stayed >= 1 and node 5's head kept rising, so the D stop condition did not fire and the kill switch was not
  run. Deviation: the "within 5 blocks" expectation failed on 2 of 5 single reads (130 and 32 behind), each level again
  on the next read. The same burst lag was there before node 5's allowlist went on (C, 02:35:29Z: 146 behind with the
  allowlist off on node 5), so it is node 5's execution catch-up pattern, not the allowlist (not proven).
  At 02:41:54Z all four validators CvvActive peers 4, heads 6194-6197; rpc-6 peers 5; NRestarts 0 everywhere.

## Deviations from the runbook's / brief's expectations

1. `sudo tn-p2p-allow-sync status|check` (runbook section 8 and the brief) does not run: `command not found` on every
   host. Use `sudo /usr/local/libexec/telcoin/tn-p2p-allow-sync …` (the driver does).
2. The set holds 5 addresses with `keys=4` on the validators: rpc-6's address is in it though it is not one of the 4
   keys. On node 5 `keys=5` (same 5 addresses). Where the 5th source comes from is not shown by `status`.
3. Node 5's head was more than 5 blocks behind validator-1 on 2 of 5 reads (see D).
4. Node 5's `net_peerCount` went from 1 (baseline, allowlist off everywhere) to 1-4 after the validators' allowlists
   went on, although no validator lists node 5's address. Not explained; not investigated (no `net_peers` read).

## Frictions (what an operator on mainnet would trip over)

1. Wrong command in the runbook: bare `tn-p2p-allow-sync` is not on sudo's PATH (see deviation 1).
2. `--status` with the allowlist off prints `check: no result line (exit 1)` on every host while the run exits 0. It
   reads like a failure; `check: n/a (off)` would match the summary line's `check=n/a`.
3. Mixed time zones in log names: the p2p-committee driver stamps its log dir in xerxes' local time (CST,
   `logs/20261117_202754-p2p-committee` for 02:27:54Z, a different date), the deploy stamps UTC
   (`logs/20261118_023116-deploy`). The runbook works in UTC; correlating needs a mental conversion.
4. The settle loop's progress lines (`heads 5443..5638 differ by more than 5`) do not name the lagging host. In D it
   was node 5 (the target), visible only by grepping the driver's log dir.
5. The node 5 settle passed at 63 s against a 60 s budget; with node 5's burst lag (25 s stuck) a slightly worse burst
   fails the host on timing alone (driver rc=1 and a kill switch for a healthy node). Consider a longer
   `P2P_COMMITTEE_SETTLE_SECS` for observers.
6. `./devnet-deploy.sh --only 20` ends with `All 20 steps done; nothing left to resume.` Only step 20 ran; on mainnet
   that line could be taken as a statement about the whole deploy.
7. Detaching: `setsid bash -c '…' &` from an agent shell (job control on) forks, so `$!` is a parent that exits at once
   and a `kill -0` waiter reports the driver finished with no rc file. The runbook's `( … ) & echo $!` form works.
   Waiters should wait on "rc file present OR pid dead", not `kill -0` alone (`waitrc.sh` does now).
8. gcloud IAP noise on every ssh (NumPy warning plus the `increasing_the_tcp_upload_bandwidth` link) on stderr.
9. The block rate swings a lot under txgen (1.7 blocks/s at 02:27Z, 18 blocks/s at 02:35Z, between about 1 and 6 blocks/s
   at 02:40-02:42Z). The driver's "heads within 5" rule produced several "differ by more than 5" rounds in every run; it passed
   each time, but on a faster chain 5 blocks is a tight window for reads taken over IAP one after the other.
10. Drop counters on the validators (420/132/100/74 packets at 02:34:46Z) show unlisted sources being dropped; `status`
    does not say from where (node 5's dials? internet noise?). Node 5's own drop counter was 0.

## Not checked

- The kill switch (`--off`) was not exercised; no stop condition fired.
- Which peers rpc-6, validator-1 and node 5 actually hold (no `net_peers` / admin peer listing). "rpc-6 still a peer of
  validator-1" is inferred from peer counts (v1 4, rpc-6 5, unchanged) and equal heads.
- Why node 5's peer count rose to 2-4 (deviation 4).
- The allowlist across an epoch change (epoch 2, 3600 s epochs): the resync at the next epoch was not watched.
- The source addresses behind the drop counters.
- IPv6 paths (no VM has an external IPv6; `allow_v6` empty everywhere).
- Runbook section 8 beyond line 633 (outside my reading scope); the section 8 reads followed the brief.
- What happens to the validators' sets when node 5 stakes (S1 territory).
