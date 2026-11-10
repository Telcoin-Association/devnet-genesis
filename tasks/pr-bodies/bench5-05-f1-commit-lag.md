## Summary

Consensus commits without waiting for local execution. The fork check moves to the subscriber, a run-ahead bound holds
commits more than 1,000 rounds ahead of execution, and a restart guard refuses to order over a restored DAG with a
reachable hole. The behind-consensus line and two gauges separate execution lag from commit lag, the execution check
matches number and hash, and an e2e test pins a slowed validator that stays active under load.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. Stacked on {{PR:prev}}: this head contains its commits, so the Files tab shows the whole stack until it merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/{{PREV_HEAD_SHA}}...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

The consensus task waited for local execution to reach each leader's execution block before it sequenced the sub-DAG.
A validator a few per cent slower to execute therefore let its committed round drift behind the certificate frontier
and was demoted while still proposing. In bench 4 (r20261105-0803) two healthy validators with slower MDBX fsync went
inactive for 24 and 31 minutes under load, which left the committee at exactly quorum for the planned kill (a 17.2-s
commit pause).

The demotion line could not show this. On bench-validator-08 `we are behind` read exec_round 352, committed_round 362,
round 403, and nothing on it or on the dashboards said how much of that gap was an execution backlog and how much a
commit lag.

{{ISSUE:f1-commit-lag-demotion}} has the bench-4 evidence with log cites, the mechanism and the rejected alternatives.

## Fix

- {{SHA:557c9b737}} `fix(primary): commit without waiting for execution; fork check moves to the subscriber`: consensus
  commits without the wait, held only while a leader runs more than `MAX_COMMIT_RUN_AHEAD_ROUNDS` (1,000) ahead of the
  executed round. The subscriber makes the fork check instead: each output first waits for execution to reach the running
  maximum of the leaders' execution blocks, then checks its leader's block (empty sub-DAGs included); a failure goes
  inactive and ends the epoch without saving. A restart whose restored DAG has a hole that ordering could step over (a
  restored certificate above its author's committed round and two or more rounds above the gc round, with a parent
  missing) goes inactive with reason `restart_gap` instead of ordering over it. A store left stale by a follower catch-up
  (nothing stored for the caught-up rounds) is not a gap, so a promotion after catch-up stays active. Kept: ordered,
  gap-free outputs and numbering; execution lags consensus; the pack save still follows a passed fork check, so restart
  replay is unchanged; the committed round is re-primed from the pack at restart; the 64-round certificate prune against
  the 40-round window; the voter's own execution wait. The restart guard closes #1518's deep gap; its shallow gap is
  unchanged.
- {{SHA:a3a00525e}} `feat(primary): expose execution and commit lag in behind-consensus logs and gauges`: with commits no
  longer waiting for execution the two lags separate. The `we are behind` line now ends with `newest_header_number` (the
  newest consensus header the node knows, from its watch; never a pack read), `backlog_outputs`, `exec_lag_rounds` and
  `commit_lag_rounds`, and the bus metrics mirror sets `tn_primary.consensus_exec_lag_rounds` and
  `tn_primary.commit_lag_rounds` from the current round and recent-blocks watch values on every change.
- {{SHA:d33ecb797}} `test(e2e): a validator with slowed execution stays active under load`: a new test hook,
  `TN_TEST_EXECUTION_DELAY_MS` (`tn_types::test_hooks::execution_delay`, inert without `tn-types/test-utils`), makes the
  engine sleep before it executes each output with batches. `test_slow_execution_stays_active` slows node 2 under load
  and checks that it stays `CvvActive` with no demotion and no `we are behind`, that its committed round keeps pace with
  the other three, and that its execution catches up once the load stops.
- {{SHA:9bad6966d}} `fix(primary): check the execution block by number and hash`: the execution check of voters, the
  subscriber and state-sync catch-up matched a header's `latest_execution_block` by hash anywhere in the recent-blocks
  ring, so a leader naming block n with the hash of an older block k was certified by voters still holding k. The ring
  now matches number and hash. Below-floor heights and read errors are not forks: a restored voter refuses with the
  final, unpenalized `BelowRestoreFloor`, the subscriber and catch-up log the floor and go on, and a failing read is
  retried, counted and logged. `ExecutionFork` names its leader. The restart guard this commit tightened (every round
  from C − gc_depth + 1 to C present) is replaced by 8651e5abd below.
- {{SHA:6f9703662}} `test(e2e): size the slow-execution window below the run-ahead bound`: at a 1.5-s per-output delay
  the slowed node's backlog reached `MAX_COMMIT_RUN_AHEAD_ROUNDS` and the held commit demoted it by design; at 0.5 s the
  lag peaks well below the bound. Each drain poll now requires `CvvActive` and
  `tn_primary_commit_run_ahead_blocked_total` = 0.
- {{SHA:8651e5abd}} `fix(primary): judge a restored dag by the certificates ordering can reach`: the window check demoted
  every promotion after a follower catch-up, because the follower path stores no certificates and the window up to the
  pack's committed round is never complete; `restarts::test_restartstt` failed and the attempts cap kept the node
  inactive. A gap is now a restored certificate above its author's committed round, two or more rounds above the gc
  round, with a parent missing from the DAG. That is the only place ordering can skip a parent: `order_dag` never expands
  a committed certificate's parents, and `linked` walks only rounds above the committed round. The shapes the window
  check targeted (a pruned bottom under an uncommitted certificate, a detached DAG, a hole in the middle) still demote.
  The log line keeps its text and adds `hole_round`.

{{CARRY_NOTE}}

## Testing

{{TESTING:05}}

- `test_slow_execution_stays_active` (e2e, four validators under load): at a 1.5-s delay per output, node 2's execution
  fell 190-226 rounds behind its commits against a 15-round activity window, yet it stayed `CvvActive` for 60 s with no
  demotion, and it caught up 120-176 s after the load stopped. At the final 0.5-s delay, three runs under load reached a
  lag of 146 / 152 / 130 rounds with 0 run-ahead holds.
- `restarts::test_restartstt` passes with the reachability guard; it failed with the window check of 9bad6966d.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` (`bench/main-fixes-2026-11` at 067639def), ten
validators and one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), with the bench-4 fleet, parameters and
chaos plan. A light-load arm (8 and 16 senders × window 16, then 600 × window 4) ran before the 600 × 16 chaos blast.
Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- No healthy validator was demoted: `tn_node_mode_transitions_total{to="cvv_inactive",reason="outside_gc_window"}` = 0
  on all nine non-chaos validators and the observer (bench 4: two mid-epoch demotions). The only transitions in the run
  are the chaos node's `epoch_behind` and `rejoin`.
- The fix was exercised: `consensus_exec_lag_rounds` reached 62 (v01), 54 (v03) and 58 (v09), above the 40-round
  activity window for about 23 min on v01, with no demotion. `commit_lag_rounds` p99 stayed at 5 or less under load (6.12
  in the chaos window), `commit_run_ahead_blocked_total` = 0 everywhere, and no healthy node logged `we are behind`.
- Committee size was 10 at every sample until the 17:54:44Z kill, and no generator received `-32603 validator is
  inactive` before the kill (bench 4: two generators lost their node for 23-30 min).
- The subscriber-side fork check never fired (`BogusSubdag` transitions 0). The restored-DAG guard produced no
  `restart_gap` on the restarted node (store top − pack = 30 rounds, all reachable).
- Side effect to fix next ({{ISSUE:execution-behind-vote-starvation}}): with commit decoupled from execution, executed
  tips spread 1-6 outputs across the fleet. A proposer names its own newest block, a header lives one round, and the
  slower voters' fork canary could not reach that block in time, so the three fastest validators certified about 0 % of
  their own headers under load (their users landed nothing for 8-14 min). The proposed fix is proposer-only: name the
  (2f+1)-th highest block among the own tip and the parents, never above the own tip and at most 8 outputs below it. A
  companion voter change waits for execution before taking the per-author lock.
- Side effect to know ({{ISSUE:loaded-epoch-boundary-drain}}): a loaded epoch close now waits for every node to execute
  to the closing output. The epoch-7 close had a 22.6-s commit gap; the two slowest executors entered the next epoch
  26-51 s late and did not vote the epoch-7 and epoch-8 records, which formed at exactly 7 of 10.

Closes {{ISSUE:f1-commit-lag-demotion}}
Refs #1781
Refs #1782
Refs #1518
Refs {{ISSUE:execution-behind-vote-starvation}}
Refs {{ISSUE:loaded-epoch-boundary-drain}}
