## Problem

With commit decoupled from execution (F1), a validator reaches an epoch close with an execution backlog, and it cannot
enter the next epoch until it has executed every output up to the closing one: the next epoch's committee, epoch
timing, base fees and the epoch record are all read from the closing block's state. The next epoch's first certificate
needs 2f+1 = 7 of the 10 members inside it, so the boundary commit gap is the drain of the seventh-fastest member. Under
the bench-5 load that was 22.5 s and 10.9 s (idle: 1.2 s). With validator-05 down, the seven fast validators were
exactly the quorum: the margin was zero nodes. Both loaded epoch records formed at exactly 7 of 10, because the record
collector stops one second after quorum and the two slow executors (validator-01, validator-03) were still draining
12-28 s behind the seventh. They downloaded the certified record instead and never voted it. While they drained, their
closing epoch's task manager stopped tracking new tasks and logged about 1,460 `tn::tasks` errors (`… no available
capacity … can never be joined or aborted`). And validator-01 entered epoch 8 when the network was at round 39 of it:
one round more and the `epoch_behind` rule would have demoted it into a catch-up it cannot finish under load.

## Evidence (bench 5, run r20261107-1504, 2026-11-07, ten validators in ten regions, 10 × 600 senders, kill of validator-05 at 17:54:44Z)

- The two loaded closes (bench-5 report, findings 7 and 10; times UTC). Closing leader commit is the fleet's (commit
  drift ≤ 0.24 s); "7th in" is the seventh validator's `Starting epoch`.

  | close | closing leader committed | 7th in | first new-epoch commit | gap | validator-03 in | validator-01 in | record |
  |---|---|---|---|---|---|---|---|
  | epoch 7 (17:55:43) | `bench-validator-02:17:55:45.137Z` leader 1778 | validator-10 17:56:06.251 | 17:56:07.64 | 22.5 s | 17:56:23.187 (+16.9 s) | 17:56:33.613 (+27.4 s) | 7 of 10, missing 05/03/01 |
  | epoch 8 (18:15:43) | `bench-validator-02:18:15:47.753Z` leader 1098 | validator-04 18:15:57.161 | 18:15:58.64 | 10.9 s | 18:16:09.176 (+12.0 s) | 18:16:25.398 (+28.2 s) | 7 of 10, missing 05/03/01 |

  Every other close in the run (epochs 0-6 and 9, idle or light) took 1.2 s and had 10 signers. In the bench-5 KPIs the epoch-7 boundary
  is the run's longest gap between blocks carrying transactions (24 s; 14 s at epoch 8). Bench 4: 13 s at both loaded
  closes; bench 3: 12 and 26 s.
- The gap is the backlog times the output cost. Execution lag at 17:55:40 (Prometheus `consensus_exec_lag_rounds`, two
  rounds per output): 20-26 rounds on the healthy seven, 42 on validator-03, 54 on validator-01; at 18:15:40: 4-14, 24, 34.
  `bench-validator-02:17:55:45.146Z` detected the close with its engine on output 12102 and executed the closing output
  12113 at `bench-validator-02:17:56:05.176Z`: 11 outputs in 20.0 s (1.82 s each; engine task p50 1.66 s pre-kill,
  2.19 s post-kill in the stage analysis). validator-01 executed 12106-12113 at 1.2-2.7 s per output (`bench-validator-01:17:56:21.659Z` …
  `17:56:33.353Z`). Commit-to-entry predicted as backlog × cost: validator-01 27 × 1.8 ≈ 49 s (measured 48.5 s) at epoch 7,
  17 × 2.19 ≈ 37 s (37.6 s) at epoch 8.
- Detection itself lags on the slow nodes. `bench-validator-01:17:56:11.011Z epoch boundary detected epoch=7`, 25.9 s
  after the fleet committed the closing leader, because the subscriber hands an output to the epoch manager only after
  its execution wait (stage S7 in the bench-5 stage analysis: validator-01 p50 10.7 s, p95 32.6 s). Until then validator-01's epoch-7 primary kept
  proposing: `bench-validator-01:17:56:05.468Z` `fatal request for requested vote … round=1780 … Invalid epoch. Peer
  proposed epoch 7`, from peers already in epoch 8 (38 such lines, validator-01 only; node log census).
- The late members download the certified record before they can vote. `bench-validator-01:17:56:09.598Z retrieved cert
  for epoch 7 … from a peer`, 1.4 s before its own detection and 2 s after the record certified (17:56:07.54-08.86 on the
  seven). `bench-validator-03:17:56:08.027Z`, 7 s into its drain. Epoch 8: `bench-validator-03:18:15:59.306Z` (detection
  18:15:58.360), `bench-validator-01:18:16:03.437Z` (detection 18:16:14.416). Neither logged `publishing epoch record
  vote` for epochs 7 and 8; both voted at every other close (boundary analysis). validator-05 also downloaded both
  (`bench-validator-05:17:59:48.905Z`, `18:15:59.634Z`).
- The entry was one round short of an `epoch_behind` demotion. validator-01 started epoch 8 at 17:56:33.613. The fleet's
  newest header was round 39 (`bench-validator-02:17:56:33.145Z`; round 40 at 17:56:34.091, round 41 at 17:56:34.631).
  validator-01 committed leaders 2-38 at 17:56:34.144-.159 and skipped the empty output 12114 (leader 2) at
  `bench-validator-01:17:56:34.149Z`, which moved its executed epoch to 8 before any round-41 certificate could arrive.
  Margins at the other late entries: validator-03 at round 25 (epoch 8) and 15 (epoch 9), validator-01 at round 27
  (epoch 9). Epoch 8 ran 81 rounds in its first minute on validator-02 (0.74 s a round), so the 40-round rule is about
  30 s after the seventh member's entry.
- The task-tracker overflow is the closing epoch's, during the drain. `bench-validator-01` logged 950 `Failed to track
  spawned task` errors from 17:56:24.261 to 17:56:33.548 (about 100 a second), starting 13.3 s after its detection and
  ending 65 ms before `Starting epoch`. `bench-validator-03` logged 339 from 17:56:18.867 to 17:56:23.128 (detection
  17:56:00.849, entry 17:56:23.187). `bench-validator-05` logged 170 at 18:02:06-18:02:09, inside its own epoch-7 drain as an
  inactive follower (detected 18:01:49.106, `epoch boundary success` 18:02:09.162). There were none at the epoch-8 close,
  where the drains after detection were 10.6-11.0 s (validator-01/03) and 8.6 s (validator-05): the 1,000 slots fill after
  about 13-18 s. Task names (validator-01, 950): VoteRequest 239, process-report-batch 190, process-gossip 189,
  shed-sync-batches 142, ProcessGossip-tn-primary 99, next-batch 39, ProcessGossip-tn-consensus-output 32, sync-batches 14,
  ConsensusOutputReq 4, sync-epoch-pack 2 (validator-03, 339: VoteRequest 90, process-report-batch 86, process-gossip 85,
  ProcessGossip-tn-primary 43, next-batch 18, ProcessGossip-tn-consensus-output 14, ConsensusOutputReq 3). The vote
  requests are the new epoch's: between detection and entry validator-01 answered 537 `vote path timing … epoch=8
  outcome=rejected` (first `bench-validator-01:17:56:11.049Z`, round 9), every one in 0 ms. In the same window
  validator-01 and validator-03 denied 3,371 and 1,484 batch requests `AtCapacity` and logged 1,248 and 680 `failed to
  fetch batches` (node log census).
- No validator was demoted at either close (`epoch_behind` did not fire on a healthy node; bench-5 report, finding 1). The
  boundary risk the F1 design listed ("epoch close with a backlog → `epoch_behind` at a boundary"; see
  {{ISSUE:f1-commit-lag-demotion}}, "Not addressed here") was a one-round near miss, not a miss.

## Mechanism (067639def, `bench/main-fixes-2026-11`)

- **Why a node cannot enter the next epoch before executing the closing output.** The entry reads the committee,
  `EpochInfo` and the epoch-start timestamp (hence the next boundary) pinned to the canonical tip, which must be the
  closing block (`crates/node/src/manager/node/start_epoch.rs:191-205`), and the workers' base fees from that block
  (`run_epoch.rs:214`). The epoch record is built from committee reads at the same block and commits it as `final_state`
  (`close_epoch.rs:459-463`; `crates/types/src/primary/epoch.rs:22-39`). The closing block runs `concludeEpoch`, where
  mid-epoch governance (a burn shrinks the committee at once) takes effect, so none of these values can be taken from
  earlier state.
- **The sequence on one node** (`run_epoch.rs`): Bullshark commits the closing leader, fleet-synchronous. The subscriber
  waits for execution before it assembles the output (F1-1), so `wait_for_epoch_boundary` sees the closing output late on
  a slow executor (`:757`); until then its old-epoch primary keeps proposing. `close_epoch` notifies the consensus
  shutdown (`:811`) and waits for the closing output's execution (`:814`): the drain. Then `write_epoch_record` (`:512`),
  the state export, the exit grace and abort of the epoch's tasks (`:547-548`), `finish_epoch`, and the next `run_epoch`
  logs `Starting epoch`.
- **Why the gap is the seventh node's drain.** A certificate of the new epoch needs 2f+1 = 7 votes (n = 10, f = 3). With
  validator-05 dead (epoch 7) or catching up (epoch 8) and validator-01/03 draining, the new epoch could start only when
  the last of the seven fast members was in: 17:55:45.14 → 17:56:06.25 (21.1 s) plus about 1.4 s for its first two rounds
  = 22.5 s; 18:15:47.75 → 18:15:57.16 (9.4 s) + 1.5 s = 10.9 s. One more slow member among the seven would have made the
  gap that member's drain (validator-03's: about 38 s); four members out of the new epoch stops it until one of them
  enters.
- **Why the record has exactly 7 signers.** `super_quorum` = ⌊2n/3⌋ + 1 = 7 (`epoch.rs:109-111`). The collector shortens
  its wait to 1 s once it has quorum (`crates/node/src/manager/epoch_votes.rs:137`), aggregates and saves the
  certificate. A draining member learns of the newer epoch from gossip (`crates/consensus/primary/src/network/handler.rs:604`)
  and epoch-record sync downloads the record and its certificate from a peer (`crates/state-sync/src/epoch.rs:183-205`).
  When its drain ends, `write_epoch_record` finds the record stored and returns without building its own
  (`close_epoch.rs:416-421`), and the collector does not vote a certified record (`epoch_votes.rs:504`); late votes would
  be dropped anyway (`handler.rs:626` accepts votes only for an uncertified record). So the signers are the members whose
  closing output executed within about a second of the seventh vote; anyone later is missing by construction. Safety is
  unaffected (7 is a super-quorum). Side effect: a late member never compares its own closing block with the certified
  `final_state`. A divergence would surface only at its next vote's fork check.
- **The record is not on the entry path.** `bench-validator-02:17:56:05.187Z` published its vote and started epoch 8 at
  17:56:05.448, 2.2 s before its collector logged quorum (17:56:07.677). Entry waits for the local drain, not the
  certificate.
- **Why validator-01/03 were not demoted.** `behind_consensus` (`handler.rs:189`) has two epoch rules. The numbered one
  (`:248-250`, consensus-result gossip) cannot fire for a connected node: every gossiped result advances
  `last_consensus_number` (`:599`) before the next check. The certificate rule (`:251-256`) demotes when
  `exec_epoch + 1 == epoch` and the certificate's round exceeds `max(40, 6)`. Both terms are new-epoch rounds counted from
  that epoch's round 1, and `exec_epoch` is the epoch of the last executed output (`consensus_bus.rs:1448-1460`). A late
  member is safe if it executes its first new-epoch output before the network certifies round 41, about 30 s after the
  seventh member's entry. validator-01 was 27.4 s behind it. Anything that shortens the fleet's drain without shortening
  the slow members' widens their lag in new-epoch rounds.
- **The task-tracker errors.** `TaskSpawner::create_task` spawns the future and then `try_send`s its handle into the
  epoch `TaskManager`'s 1,000-slot channel, logging the error when the channel is full (`crates/types/src/task_manager.rs:183-203`,
  `:298`). Only `until_exit_internal` (`:461`) and `update_tasks` (`:437`) drain that channel. In `run_epoch` that is the
  `until_task_ends` arm of the boundary `select!` (`run_epoch.rs:536`). Once the boundary arm wins (`:481`), the close,
  record and export run with nothing draining. The closing epoch's network event loops and batch builder keep spawning:
  the primary loop is a task on the epoch spawner that ends only when the manager is dropped and does not watch the
  consensus shutdown (`crates/consensus/primary/src/network/mod.rs:2083`). The per-message tasks are VoteRequest
  (`:2162`), ProcessGossip (`:2273`), ConsensusOutputReq (`:2234`), sync-epoch-pack (`:2330`), the worker's
  process-report-batch, process-gossip, sync-batches and shed-sync-batches (`crates/consensus/worker/src/network/mod.rs:833`,
  `:874`, `:929`, `:607`) and the batch builder's next-batch (`crates/batch-builder/src/lib.rs:302`). Much of it is
  new-epoch traffic that the closing epoch can only refuse (the 537 rejected epoch-8 vote requests above). "Never
  joined or aborted" is wider than the error lines: `wait_for_exit`/`join_tasks_within` (`task_manager.rs:519`) and
  `abort_all_tasks` (`:428`) never read the channel either, so every task spawned during the close escapes the
  abort, the up to 1,000 queued ones as well as the untracked ones. Each still selects on the manager's local
  shutdown, which fires when the epoch manager is dropped
  (`task_manager.rs:143-147`) at `run_epoch`'s return. That is after `finish_epoch` has sealed the certificate pack and
  cleared the epoch tables (`close_epoch.rs:986-997`). The pack seal already tolerates a late holder
  (`run_epoch.rs:1232-1236`). Whether a late old-epoch handler can write a cleared table (`Votes`, `NodeBatchesCache`,
  `Payload`) in that window was not checked. None of the names seen is a critical task. A critical task spawned during a
  close would be untracked, and its failure would not end the epoch.

## Proposal

- **(A) Sign the record on the committed boundary output's consensus data, without local execution: reject.** The record
  attests execution: `final_state` is the closing block's hash and `next_committee` is read at that block, and sync
  anchors on the certificate as an execution checkpoint (`validate_downloaded_record`). A signer that has not executed
  echoes a hash it learned from peers. With four echoing signers, a 7-signer certificate has only three independent
  executors (≤ f). A consensus-only record (`final_consensus` alone) is a different, sync-visible record format, and it
  would not shorten the gap, because the certificate does not gate entry. One small, cherry-pickable part is worth
  keeping: when `write_epoch_record` short-circuits on a stored record in the live path, compare the record's
  `final_state` with `latest_execution_block_num_hash()` and halt on a mismatch, the same fail-stop the recovery path
  applies to a forked record.
- **(B) Bounded boundary grace (hold the new epoch's first rounds until N of the slow members are in): reject.** It
  turns the seventh member's drain into the slowest member's, 48.5 s instead of 22.5 s at epoch 7, for everyone, every loaded
  close. It buys signers and the demotion margin with user-visible stall.
- **(C) Make the drain shorter, by engine throughput: the root lever, and what the design named.** The gap is about
  1.4 s + max over the seven fastest of (outputs behind × engine cycle per output). Pipelined persist (F2; lever 2 in the bench-5 report, finding 5;
  cycle max(execute 479, persist 1,167) instead of 1,658 ms pre-kill, ≈ ×0.71 post-kill) scales every drain by about
  0.70. Epoch 7: seventh member 21.0 → ≈ 14.7 s, gap ≈ 16 s; validator-01's lag behind the seventh 27.4 → ≈ 19 s
  (≈ 26 rounds, margin ≈ 14). Epoch 8: gap ≈ 8 s. It does not reach the idle gap and does not raise the signer count,
  because the slow members trail the seventh by more than 1 s whatever the cycle. The slow members' extra 17-28 s is
  their deficit against the commit rate ({{ISSUE:execution-lag-feedback}}), which only a fix to that removes.
  **Warning:** an admission bound tied to the local backlog (lever 1 in the bench-5 report, finding 5) shrinks the fast members' backlog (the seventh
  member's drain → about 2 × 1.66 = 3.3 s) but not the slow members' deficit. validator-01 would then enter 34-45 s after
  the seventh, 46-61 new-epoch rounds, past the 40-round rule. Its `epoch_behind` demotion becomes certain at every loaded
  close, and a demoted slow executor does not catch up under load (validator-05 needed 23 min and the end of the load).
  Do not ship lever 1 without (C) for the slow members or a boundary guard.
- **(D) The task tracker: drain it during the close.** Name of the X: the per-message handler tasks of the closing
  epoch's primary and worker network loops (VoteRequest-<header>, ProcessGossip-<topic>-<relayer>,
  process-gossip-<relayer>, process-report-batch-<batch>, sync-batches and shed-sync-batches-<peer>,
  ConsensusOutputReq-<peer>, sync-epoch-pack-<peer>) and the batch builder's next-batch. Raising the limit does not fix
  it: validator-01 spawned about 1,950 tasks in its 22-s drain after detection, and a 48-s drain needs about 4,000.
  Stopping those loops at the consensus shutdown would stop this node serving epoch records and consensus outputs to
  catching-up peers while it drains. Fix: a `TaskManager` method that tracks new handles and reaps finished ones while a
  given future runs (the `new_task_rx` and `tasks.next()` arms of `until_exit_internal` without its exit conditions,
  because consensus tasks end normally at the close). The boundary arm then awaits the close, record and export through
  it, and `update_tasks()` runs once more before `wait_for_exit`/`abort_all_tasks` so that every task is aborted.
  Two files (`crates/types/src/task_manager.rs`, `crates/node/src/manager/node/run_epoch.rs`), nothing
  consensus-observable, cherry-pickable.
- **(E) Observability, so the margin is visible before it reaches zero.** Per node and per close, at info on
  `epoch-manager` and as gauges: `tn_node_epoch_close_backlog_outputs` (closing number minus last executed number at
  detection), `tn_node_epoch_close_detect_lag_seconds` (closing output's `committed_at` to detection),
  `tn_node_epoch_close_drain_seconds` (detection to closing output executed), and `tn_node_epoch_entry_lag_seconds`
  (`committed_at` to `Starting epoch`). Also `tn_primary_epoch_entry_rounds_behind`: the highest new-epoch round seen at
  entry against the 40-round rule, which was 39 vs 40 at validator-01's epoch-8 entry. On the record side,
  `tn_node_epoch_record_vote_skipped_total{reason="certified_before_close"}` plus the seconds by which the member missed
  the quorum. `tn_node_epoch_record_signers` already exists: its distance to `super_quorum` is the record margin (0 at
  both loaded closes). Cherry-pickable, nothing consensus-observable.
- **(F) Drain before the boundary (new here).** The batch builders stop sealing T seconds before the epoch
  boundary, so the last outputs are empty, consensus keeps committing, and every engine drains while the epoch is still
  live. All members then reach the close caught up: entry and the record in about 1 s, no tracker overflow, no
  demotion margin to spend. It is the only option that meets the idle-gap and ≥ 9-signer fields. Costs: T must cover the
  slowest member that matters (about 20-50 s here). Transactions submitted in the window wait up to T even at light load
  unless T adapts. It changes block contents, as policy rather than validity, and it works only if the whole fleet
  applies it. Bench 7 candidate, sized from (E)'s bench-6 data.

**Recommendation for bench 6: (C), carried by the pipelined persist already in the bench-6 plan, measured at the
boundary with (E), with (D) riding along.** (D), (E) and the `final_state` check from (A) are cherry-pickable on their
own and touch nothing consensus-observable. (C) is owned by the F2 work; this issue adds the boundary fields and the
lever-1 warning to it. Drop (A) and (B). Keep (F) for bench 7.

## Test plan

- (D) `task_manager.rs` inline tests: `tracks_tasks_spawned_while_a_close_runs`: spawn 1,500 tasks from a `TaskSpawner`
  while the tracking wrapper awaits a pending future; expect no `try_send` failure and, after the future resolves,
  `abort_all_tasks` cancels all 1,500. `reaps_finished_tasks_while_tracking`: 10,000 short tasks leave the tracked set
  bounded.
- (D) `run_epoch.rs`: the boundary arm keeps the epoch tracker draining while `close_epoch` waits on a test engine
  held back for 30 s and the primary network spawns per-message tasks; no `tn::tasks` error is logged
  (`tracing::subscriber::with_default` capture).
- (A, the check) `close_epoch.rs`: a stored record whose `final_state` matches the executed closing block passes; a
  mismatched one returns the fork error and does not publish to `epoch_record_watch`.
- (E) DebuggingRecorder test for each gauge on a closing output with a backlog of 3 and a detection lag of 2 s.
- e2e `test_loaded_close_with_a_slow_member`: four validators, one with the test-only execution delay used by
  `test_slow_execution_stays_active`, `gc_depth` 25 (window 15). Load across a close; assert the slow member enters the
  next epoch active, `tn_primary_epoch_entry_rounds_behind` is reported, and there are no `tn::tasks` errors.

## The bench-6 field that proves it

- (D): `Failed to track spawned task` = 0 on every node at every close, including the slowest executor's loaded close and
  a restarted member's catch-up close.
- (E): every loaded close has, per node, backlog outputs, detect lag, drain, entry lag and entry rounds-behind, and
  `epoch_record_vote_skipped_total` explains every missing signer.
- (C): at each loaded close, gap ≈ 1.4 s + the seventh-fastest member's backlog × cycle, and ≤ 0.72 × the bench-5 value at a
  matched backlog (bench 5: 22.5 s at 10-13 outputs, 10.9 s at 2-7). Every late member enters less than 30 s after the
  seventh (entry rounds-behind ≤ 30, a margin of at least 10 rounds), and no `reason="epoch_behind"` transition on a
  healthy validator.
- Stretch, not expected from (C) alone (needs the lag-spread fix or (F)): epoch records with ≥ 9 of 10 signers at loaded
  closes (10 of 10 without a chaos member) and a boundary commit gap ≤ the idle 1.2 s.
- Watch: if lever 1 (the in-flight bound) ships, the slow members' entry rounds-behind against 40, and `epoch_behind` at the first loaded
  close.

## Related

- {{ISSUE:f1-commit-lag-demotion}}, "Not addressed here": predicted the boundary drain and the
  `epoch_behind` risk. Bench 5 measured the drain and found the risk one round from firing.
- {{ISSUE:execution-lag-feedback}}: why validator-01/03 are the slow members and why their backlog
  survives into the next epoch (they enter 27 s late with the fleet's first outputs already committed).
- Levers 1 and 2 in the bench-5 report, finding 5 (https://benchmark.telcoin.network/runs/r20261107-1504/report.html), the F2
  pipelined persist ({{ISSUE:f2-execution-ceiling}}), and {{ISSUE:f3-rejoin-loop}} (what a demoted slow executor faces
  under load).
- Bench-4 watch items (https://benchmark.telcoin.network/runs/r20261105-0803/report.html): the 13-s loaded boundary gap (F7) and the records at exactly 7 (F6). The collector's
  `signers=1 timeouts=25` failure did not recur, so its retry path was not exercised.
