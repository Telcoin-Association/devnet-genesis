# Draft PR (telcoin-network) — topic `f1-commit-lag` — not yet opened; evidence section filled from the bench-5 analysis (Wave D)

Opened as #1817 (2026-11-10): head `fix/1799-f1-commit-lag` → base `staging/benchmark-obs-2026-11` (PR 6 of 10, stacked). Final body: tasks/pr-bodies/bench5-05-f1-commit-lag.md.

Cherry-pick onto main: `git -C $TN fetch origin main && git switch -c fix/f1-commit-lag origin/main && git cherry-pick -x $(git log --reverse --format=%h --grep='^Topic: f1-commit-lag$' origin/main..bench/main-fixes-2026-11)`
Commits on bench/main-fixes-2026-11 (integration shas): 557c9b737 a3a00525e d33ecb797
Depends on: see tasks/bench5-cherrypick-ledger.md (depends-on column). Related: Refs #1781, #1782, #1518; tasks/issues/bench5-f1-commit-lag-demotion.md.
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head fix/f1-commit-lag --title "<title>" --body-file <this file's body>

## Title
fix(primary): commit without waiting for execution; expose the lag; e2e for a slowed validator

## Body (per-commit summary)
- 557c9b737 `fix(primary): commit without waiting for execution; fork check moves to the subscriber`
  The consensus task waited for local execution to reach each leader's execution block before it sequenced the
    sub-dag, so a validator a few per cent slower to execute let its committed round drift behind the certificate
    frontier and was demoted while still proposing: in bench 4 (r20261105-0803) two healthy validators with slower
    MDBX fsync went inactive for 24 and 31 minutes under load, leaving the committee at exactly quorum for the
    planned kill (a 17.2 s commit pause). Consensus now commits without that wait, held only while a leader runs
    more than MAX_COMMIT_RUN_AHEAD_ROUNDS (1,000) ahead of the executed round. The subscriber makes the fork check
    instead: each output first waits for execution to reach the running maximum of the leaders' execution blocks,
    then checks its leader's block (empty sub-dags included); a failure goes inactive and ends the epoch without
    saving. A restart whose restored DAG has a hole ordering could step over — a restored certificate above its author's
    committed round and two or more rounds above the gc round with a parent missing — goes inactive (reason restart_gap)
    instead of ordering over it; a store left stale by a follower catch-up (nothing stored for the caught-up rounds) is not
    a gap, so a promotion after catch-up stays active. Kept: ordered, gap-free outputs and numbering; execution lags consensus; the pack
    save still follows a passed fork check, so restart replay is unchanged; the committed round is re-primed from
    the pack at restart; the 64-round certificate prune vs the 40-round window; the voter's own execution wait.
    #1518's deep gap is closed by the restart guard, its shallow gap is unchanged.
- a3a00525e `feat(primary): expose execution and commit lag in behind-consensus logs and gauges`
  In bench 4 (r20261105-0803) the `we are behind` line on bench-validator-08 read exec_round 352, committed_round
    362, round 403, and nothing on it or on the dashboards said how much of that gap was an execution backlog and
    how much a commit lag. With commits no longer waiting for execution the two separate, so the line now ends
    with newest_header_number (the newest consensus header the node knows, from its watch; never a pack read),
    backlog_outputs, exec_lag_rounds and commit_lag_rounds, and the bus metrics mirror sets
    tn_primary.consensus_exec_lag_rounds and tn_primary.commit_lag_rounds from the current round and recent-blocks
    watch values on every change.
- d33ecb797 `test(e2e): a validator with slowed execution stays active under load`
  On bench 4 the slow-fsync validators were demoted outside_gc_window because Bullshark waited for their execution
    before each commit, so their committed round froze with it. A new test hook, TN_TEST_EXECUTION_DELAY_MS
    (tn_types::test_hooks::execution_delay, inert without tn-types/test-utils), makes the engine sleep before it
    executes each output with batches. test_slow_execution_stays_active slows node 2 by 1.5 s an output under
    load: its execution falls 190-226 rounds behind its commits against a 15-round activity window, yet it stays
    CvvActive for 60 s with no demotion and no "we are behind", its committed round keeps pace with the other
    three, and its execution catches up once the load stops (120-176 s measured).
- 9bad6966d `fix(primary): check the execution block by number and hash`
  The execution check of voters, the subscriber and state-sync catch-up matched a header's latest_execution_block by
    hash anywhere in the recent-blocks ring, so a leader naming block n with the hash of an older block k was certified
    by voters still holding k. The ring now matches number and hash; below-floor heights and read errors are not forks
    (a restored voter refuses with the final, unpenalized BelowRestoreFloor; the subscriber and catch-up log the floor
    and go on; a failing read is retried, counted and logged). ExecutionFork names its leader. The restart guard it
    tightened (every round from C − gc_depth + 1 to C present) is replaced by the guard commit below.
- 6f9703662 `test(e2e): size the slow-execution window below the run-ahead bound`
  At a 1.5 s per-output delay the slowed node's backlog reached MAX_COMMIT_RUN_AHEAD_ROUNDS and the held commit demoted
    it by design; at 0.5 s the lag peaks well below the bound. Each drain poll now requires CvvActive and
    tn_primary_commit_run_ahead_blocked_total = 0; three runs at load: lag 146/152/130 rounds, 0 holds.
- 8651e5abd `fix(primary): judge a restored dag by the certificates ordering can reach`
  The window check demoted every promotion after a follower catch-up (the follower path stores no certificates, so the
    window up to the pack's committed round is never complete); `restarts::test_restartstt` failed and the attempts cap
    kept the node inactive. A gap is now a restored certificate above its author's committed round, two or more rounds
    above the gc round, with a parent missing from the DAG — the only place ordering can skip a parent (order_dag never
    expands a committed certificate's parents; linked walks only rounds above the committed round). The SEC-3 shapes
    (pruned bottom under an uncommitted certificate, detached DAG, middle hole) still demote. The log line keeps its
    text and adds hole_round.

## Why (measured motivation)
See the issue text tasks/issues/bench5-f1-commit-lag-demotion.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` = bench/main-fixes-2026-11 @ 067639def, ten validators + one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), the bench-4 fleet, parameters and chaos plan; a light-load arm (8 and 16 senders × window 16, then 600 × window 4) before the 600 × 16 chaos blast. Analysis: benchmark/private/bench5-r20261107-1504/ (A1 KPIs, A2 certification, A3 recovery, A4n census/F2, A6 land path), summarised in tasks/bench5-report-r20261107-1504.md.

- No healthy validator was demoted: `tn_node_mode_transitions_total{to="cvv_inactive",reason="outside_gc_window"}` = 0 on all nine non-chaos validators and the observer (bench 4: two mid-epoch demotions). The only transitions in the run are the chaos node's `epoch_behind` and `rejoin`.
- The fix was exercised: `consensus_exec_lag_rounds` reached 62 (v01), 54 (v03), 58 (v09) — above the 40-round activity window for about 23 min on v01 — with no demotion; `commit_lag_rounds` p99 stayed ≤ 5 under load (6.12 in the chaos window); `commit_run_ahead_blocked_total` = 0 everywhere; no `we are behind` on a healthy node.
- Committee size 10 at every sample until the 17:54:44Z kill; `-32603 validator is inactive` responses before the kill = 0 across all ten generators (bench 4: two generators lost their node for 23-30 min).
- The subscriber-side fork check never fired (`BogusSubdag` transitions 0); the restored-DAG guard produced no `restart_gap` on the restarted node (store top − pack = 30 rounds, all reachable).
- Side effect to fix next (tasks/issues/bench5-execution-behind-vote-starvation.md): with commit decoupled from execution, executed tips spread 1-6 outputs across the fleet; a proposer names its own newest block, a header lives one round, and the slower voters' fork canary could not reach that block in time — the three fastest validators certified ≈ 0 % of their own headers under load (their users landed nothing for 8-14 min). Proposer-only fix for bench 6: name the (2f+1)-th highest block among own tip and parents, never above own tip, ≤ 8 outputs below; companion voter change: wait for execution before taking the per-author lock.
- Side effect to know: a loaded epoch close now waits for every node to execute to the closing output (22.6 s commit gap at the epoch-7 close; the two slowest executors entered the next epoch 26-51 s late and did not vote the epoch-7/8 records, which formed at exactly 7 of 10).

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
