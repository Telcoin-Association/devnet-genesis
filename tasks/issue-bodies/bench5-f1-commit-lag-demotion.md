## Problem

For every committed sub-DAG the consensus task waits until local execution reaches the leader's `latest_execution_block`
before it sends the sub-DAG to the subscriber and publishes `committed_round`. A validator whose execution runs a few per
cent slower than the quorum's therefore lets its committed round fall behind the certificate frontier at the rate of its
execution deficit, and `behind_consensus` demotes it once the gap passes the 40-round activity window, while it is still
proposing at the frontier. In bench 4 this took two healthy validators (slower MDBX fsync, no fault) out of a ten-member
committee for 24 and 31 minutes under load and left the committee at exactly quorum for the planned kill.

## Evidence (bench 4, run r20261105-0803, 2026-11-05, ten validators in ten regions, closed-loop load)

- `bench-validator-08:2026-11-05T09:20:07.534Z` `we are behind, go to catchup mode! epoch=3 exec_epoch=3 number=None
  exec_number=4423 exec_round=352 processed_consensus_round=352 committed_round=362 round=403 effective_exec_round=362
  gc_window=40 reason=outside_gc_window`.
- `bench-validator-07:2026-11-05T09:27:01.433Z` the same line with `exec_round=756 committed_round=760 round=801
  effective_exec_round=760`. In both, one gossiped certificate arrived 41 rounds above the node's own committed round
  (362 + 40 < 403, 760 + 40 < 801). Every epoch record in the run has ten members: this is not committee rotation.
- Both still proposed at the frontier: validator-08's last own certificate before the drop is round 403 at
  `bench-validator-08:09:20:07.487Z`, validator-07's is round 800 at `bench-validator-07:09:27:00.875Z`.
- The delay sits at the wait. `subdag committed` (logged inside Bullshark) to `received committed subdag from consensus`
  (the subscriber, after a send into a 10,000-slot channel) took 2.2-4.2 s on average and 7-13.5 s at most per minute on
  these two nodes from 09:16, and 0 on validators 01 and 05. Batch download after pickup took under 10 ms.
- Commit drift behind the earliest node: validator-07 about 2 s a minute from 09:11 (30.4 s at 09:26), validator-08
  about 6 s a minute from the epoch-2 close at 09:14:49 (31.6 s at 09:19). About 30 s is 37-40 rounds at the loaded
  1.2-1.3 rounds a second. Validator-04 drifted to 8.4 s by 09:32 and stayed; the other seven stayed at 0.2 s or less.
- The deficit is persistence, not execution: MDBX sync p50 0.556 s (08) and 0.383 s (07) against 0.338-0.364 s on the
  others; persist 87 and 68 µs/tx against 55-61; execute 157 and 167 µs/tx against 161-166; engine queue wait p50 8.8 and
  9.2 s against 4.7-7.1 s. Every engine was saturated, so no node had spare rate to catch up.
- Effect on users and the committee: generators 08 and 07 received `-32603 validator is inactive` from 09:20:06 and
  09:27:02 to the end of the load, about 31 and 24 minutes. Voting members went 10 → 9 → 8, then 7 at the 09:33:50 kill,
  so every certificate needed all seven votes: `bench-validator-01:09:33:50.237Z` committed leader round 1,144 and
  `bench-validator-01:09:34:07.399Z` the next, 1,146, a 17.2-s pause (block 24,434 to 24,435, the longest gap of the run).
  The mean round went 806 → 1,047 → 1,185 → 1,458 ms with each lost voter. Chain throughput did not fall, because
  execution sets it.
- Both nodes had already stopped voting about five minutes before they were demoted (their Ok vote responses fell to 0 at
  09:15 and 09:18; their wait is the voter's own execution wait). The demotion removed two proposers and two RPC endpoints,
  not two votes.

## Mechanism (origin/main 4bf4604d2)

- `crates/consensus/primary/src/consensus/state.rs`: `new_certificate` (`:573`) runs Bullshark (`:594`), which advances the
  in-memory commit state; then for each committed sub-DAG the task waits on `wait_for_execution(leader.latest_execution_block())`
  (`:611-612`; a failure goes inactive and shuts the epoch down, `:613-624`), and only then sends it to `sequence`
  (`:646-650`) and, after the whole batch, publishes `committed_round` (`:666-670`). While it waits it reads no further
  certificate.
- `crates/consensus/primary/src/network/handler.rs` `behind_consensus` (`:162`): `effective = max(exec_round,
  processed_consensus_round, committed_round)` (`:198`), window `gc_activity_window(50)` = 40 (`:211`,
  `crates/types/src/primary/mod.rs:72`), demotion when `epoch == exec_epoch && effective + 40 < round` (`:215`). It runs for
  every gossiped certificate with that certificate's round (`:327`) and for consensus results (`:483`). Because of the wait,
  all three terms of `effective` follow the node's execution.
- The wait is also the only throttle between Bullshark and the engine (engine queue 8, `crates/engine/src/lib.rs:55`; then
  `to_engine` 64 and `consensus_output` 100), and the quorum sets the pace: a voter answers only after its own execution
  reaches the header's execution block (`handler.rs:913`). A node a few per cent slower than the quorum falls behind for as
  long as the load lasts.
- What the wait protects: a fork canary (the leader's execution block must be one this node executed:
  `crates/consensus/primary/src/consensus_bus.rs:1166-1197`, the same check every vote makes at `handler.rs:913`), the
  back-pressure above, and the rule that the consensus pack only receives outputs that passed the check. It does not
  protect epoch close (`crates/node/src/manager/node/run_epoch.rs:804` waits on the boundary output's own execution),
  restart replay (the pack may already lead execution: `crates/state-sync/src/lib.rs:195-245`, replayed and awaited at
  `run_epoch.rs:237-258`) or the commit-accounting check (in memory, `state.rs:666-683`).

## Proposal

1. Commit without waiting (`state.rs:607-624`). Delete the wait and the bogus-sub-DAG branch. Before each
   `sequence().send`, apply a run-ahead gate: hold while `leader_round > exec_round + MAX_COMMIT_RUN_AHEAD_ROUNDS`, with
   `exec_round = max(bus.last_consensus_round(), exec_floor)` and `exec_floor` the pack's committed round read at spawn.
   `last_consensus_round` is the leader round of the last output the engine processed, empty outputs included. The floor
   matters after a promotion from catch-up, where the pack written by state sync can lead execution and there is no replay;
   Initial and NewEpoch starts replay the pack and wait for it. `MAX_COMMIT_RUN_AHEAD_ROUNDS = 1_000` in
   `crates/types/src/primary/mod.rs`. While held, wait on `recent_blocks` changes or shutdown, log one warn line and count
   it. On shutdown, return `Ok(())` at once: falling through to the commit-accounting check with a partial batch would
   report a false violation. If the gate holds for long, `committed_round` freezes and `behind_consensus` demotes the node
   40 rounds later, so "execution more than 1,000 rounds behind" becomes the new demotion rule.
2. Move the fork check into the subscriber (`crates/consensus/executor/src/subscriber.rs`). In `run`, when a sub-DAG is
   received and numbered (`:470-479`), carry a running `wait_floor = max(wait_floor, leader.latest_execution_block().number)`
   into its future. The future first waits until local execution reaches `wait_floor`, then calls
   `wait_for_execution(leader block)`, which returns at once and does the ring/canonical hash check. Both happen before
   anything else, including the empty-payload early return in `fetch_batches` (`:549-552`). On failure it returns
   `ExecutionFork {number, base_block, base_hash}`. `run` logs an error, sets `CvvInactive`, counts the transition, notifies
   shutdown and returns `Ok(())`, as the consensus task does today. It must not return `Err` (that fails the critical task)
   and must not go through the shutdown drain, which would save later outputs. The running maximum keeps the futures
   finishing in order. Without it, outputs led by this node (its header carries its own stale tip) and by slower nodes
   pass at once, fetch their batches and sit complete behind a slower predecessor. That holds up to the whole run-ahead in
   memory, not the 100 + 64 + 8 channel slots.
3. Guard the restart. The certificate store prunes at the newest written round − 64
   (`crates/storage/src/stores/certificate_store.rs:157-190`), while the rebuild reads rounds above the pack's committed
   round − 50 (`state.rs:153`). With step 1 the pack can lag the frontier by hundreds of rounds, so a lagging node that
   restarts would rebuild a DAG with no certificates just above its committed round. Bullshark then skips the missing
   parents (`crates/consensus/primary/src/consensus/utils.rs:71`) and can sequence a node-local sub-DAG. In
   `Consensus::spawn`: if `last_committed_round > 0` and the restored DAG's lowest round is above
   `last_committed_round + 1`, set `CvvInactive`, notify shutdown and do not start the task. Healthy restarts and promotions
   from catch-up keep a floor below the committed round and are unaffected.
4. Update the docs of `gc_activity_window` (`types/src/primary/mod.rs:54-74`) and the comments in `behind_consensus`: the
   window now measures commit lag, not execution lag.

Bound. Commits run ahead of execution by at most 1,000 rounds plus `exec_floor − last_consensus_round` at spawn, which
is at most 500 sub-DAGs of headers in `sequence` and the subscriber's queue (about 10-12 MB). Materialised outputs stay
at about the leaders' own execution lag plus the channel slots, as today. The pack's lead over execution is unchanged,
because the save still follows the check, so restart replay is unchanged. At the loaded 1.2 rounds a second, 1,000
rounds is about 14 minutes. Bench 4's worst drift (6 s a minute) would need more than two hours of load to reach it.

Unchanged: outputs stay ordered and gap-free (numbers assigned on receipt, `FuturesOrdered` order, the save rejects a
non-advancing number); a forked node never saves the output whose check failed (the save is reachable only through that
output's `Ok`); the voter's own check; the 64-round store against the 40-round window.

Not addressed here: a lagging validator still cannot vote while its execution trails the header's block (#1782). At an
epoch boundary a node must execute its backlog before it can start the next epoch, because the closing block sets the
committee. If the committee is more than 40 rounds into the new epoch by then (30-60 s under load), the node is demoted
with `epoch_behind`. #1518's shallow gap (16 to 65 rounds between frontier and pack) is left to its own fix.

Rejected:
- A consensus-only round for `behind_consensus`. With Bullshark blocked on the wait, `committed_round`, the certificate
  validator's gc round and too-new ceiling, and the voter's too-new ceiling all freeze, and the DAG grows unpurged. It
  hides the stall rather than removing it.
- A demotion grace or hysteresis. Under saturating load the drift is monotonic, so this only delays the same demotion.
- A larger `gc_depth`. It is capped by `MAX_GC_DEPTH` (50) and the pack's batch bound, and buys minutes.
- Moving the wait to the save, after the batch fetch, or a fork monitor with no gate. Every pending output would fetch at
  once and stay in memory up to the run-ahead, and the second loses "never saved before checked".

## Test plan

- `consensus_tests.rs` `commits_advance_without_execution`: leave `recent_blocks` empty (today's wait never returns on an
  empty ring), feed certificates for rounds 1-7, expect sub-DAGs on `sequence` and `committed_round() > 0`. Fails on main.
- Inline tests of `commit_run_ahead_ok`: execution round 0 with leader round 1,000 passes and 1,001 holds; the floor
  raises the base; no overflow at the extremes. `gate_returns_on_shutdown_without_commit_accounting`.
- Subscriber: `fetch_batches_reports_execution_fork` (the ring holds block 1 with hash A, the leader references block 1
  with hash B, no canonical reader: `ExecutionFork`, nothing saved); `fetch_batches_checks_empty_subdag`;
  `wait_floor_is_monotone` (targets 5 then 1: the second output does not finish before the first);
  `run_returns_ok_after_execution_fork`.
- `spawn_demotes_on_restored_dag_gap`: certificates written for rounds 200-260 and a pack committed at round 20 give
  `CvvInactive` and no consensus task.
- `network_tests.rs` `frozen_commit_is_behind` (committed 360, certificate 403: demote) pins the path a held gate takes.
  The companion "execution lag inside the window is not behind" already holds on main
  (`test_behind_consensus_committed_round_prevents_false_positive`); keep it only as a pin.
- e2e `test_slow_execution_stays_active`: four validators under load, node 2 started with a test-only execution delay
  (1.5 s per output, an env hook that is off without `test-utils`), `gc_depth` 25 (window 15). For 60 s node 2 stays
  `CvvActive` on every 2-s poll, its exec lag exceeds 15 rounds at least once, the others keep advancing.

## The bench-5 field that proves it

- `tn_node_mode_transitions_total{to="cvv_inactive",reason="outside_gc_window"}` = 0 on every validator outside the chaos
  plan, and no `we are behind` line with `reason=outside_gc_window` there.
- `tn_primary_consensus_exec_lag_rounds` above 40 at some point on the slow-persist validator(s): the fix carried a node
  that today would have been demoted. `tn_primary_commit_lag_rounds` p99 ≤ 6 outside the chaos window;
  `commit_run_ahead_blocked_total` = 0; `tn_executor_execution_wait_seconds` p50 and p99 per node.
- No `-32603 validator is inactive` on any generator before the first loaded epoch boundary.
- Watch: `reason="epoch_behind"` at the first loaded boundary on the slowest validator (expected if its backlog then
  exceeds about 40 rounds); the voting set at the kill (Ok vote responses per voter per minute and
  `vote_timeouts_total{stage="exec_wait"}`), which this change does not raise; RSS on the slow validator; `seen_ms` of the
  slow validator's generator, which now reads that node's execution lag instead of a refusal.

Related:
- #1781: the loaded round is paced by the voters' execution wait, which is what hides the far-validator starvation of
  #1781 under load; this change leaves that pacing as it is, but a faster loaded round from other fixes may expose it.
- #1782: the voter's execution wait is the other half of the same lag. With this change a lagging validator stays active
  but still cannot vote, so a bounded wait with a quick refusal matters more, not less.
- #1518: the store prunes from the frontier while the rebuild needs rounds above the pack's committed round − 50. This
  change lets the pack trail the frontier much further on a lagging node, so step 3 closes the deep gap. The shallow gap
  stays with #1518 (and PR 1529).
