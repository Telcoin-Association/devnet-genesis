# Draft PR (telcoin-network) — topic `f1-commit-lag` — not yet opened; evidence section to be filled from the bench-5 analysis (Wave D)

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
    saving. A restart whose restored DAG starts above the committed round + 1 goes inactive (reason restart_gap)
    instead of ordering from it. Kept: ordered, gap-free outputs and numbering; execution lags consensus; the pack
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

## Why (measured motivation)
See the issue text tasks/issues/bench5-f1-commit-lag-demotion.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run <R>)
(to be filled in Wave E from benchmark/private/bench5-<run>/{A1,A3,A4n,A6}: the fields named in tasks/checkpoint-bench5-design.md for this topic, with file cites; verdict confirmed / inconclusive / regressed)

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
