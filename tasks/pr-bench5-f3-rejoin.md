# Draft PR (telcoin-network) — topic `f3-rejoin` — not yet opened; evidence section to be filled from the bench-5 analysis (Wave D)

Cherry-pick onto main: `git -C $TN fetch origin main && git switch -c fix/f3-rejoin origin/main && git cherry-pick -x $(git log --reverse --format=%h --grep='^Topic: f3-rejoin$' origin/main..bench/main-fixes-2026-11)`
Commits on bench/main-fixes-2026-11 (integration shas): 746ac3272 0c41872ba bf34ec488 cae41a400 f2f9437f7 73d3163db ae68877dc
Depends on: see tasks/bench5-cherrypick-ledger.md (depends-on column). Related: Refs #1518, #1513, #1517, #1782; overlaps PR 1531 (F3-5); tasks/issues/bench5-f3-rejoin-loop.md.
Open as DRAFT with: gh -R Telcoin-Association/telcoin-network pr create --draft --base main --head fix/f3-rejoin --title "<title>" --body-file <this file's body>

## Title
fix: one rejoin per episode — certificate retention, propose at the head, grace, attempt cap, inactive and execution-behind vote refusals, e2e

## Body (per-commit summary)
- 746ac3272 `fix(storage): keep the certificate rounds a rejoining validator rebuilds from`
  Peers prune certificates below their newest written round H minus ROUNDS_TO_KEEP, and a validator restarting
    consensus at its handled leader round C needs every round above C - gc_depth for the certificate manager's
    parent check and Bullshark's check_parents. With 64 kept at gc_depth 50 that fails once H - C reaches 16,
    inside the 20-round rejoin window: in r20261105-0803 validator-05 rejoined at 10:00:59Z (handled 730, newest
    750), restored num_certs=0, hit 11 fetch failures for missing parents and was demoted at round 771. 128 rounds
    hold up to H - C = 79 (moved to tn-types, re-exported by tn-storage); startup refuses gc_depth + activity
    window + 10 > 128, i.e. above 64. Cost: about twice the certificate store's live footprint; the pruning
    cadence is unchanged.
- 0c41872ba `fix(state-sync): rejoin proposes at the network head`
  A validator promoted back mid-epoch (r20261105-0803, validator-05) proposed round 5 with primary_round at 4
    although it had executed round 730, then re-sent that stored header on eleven later promotions.
    prime_consensus now seeds primary_round, never committed_round, from the newest same-epoch header;
    Proposer::new starts at or above it so replayed store rounds cannot move it back; a proposer above round 0
    waits for parents of its own round; the max-delay tick re-sends LastProposed only at or above its round (the
    record stays stored). The pieces are unsafe apart: the seed alone proposes on round-0 parents, and without the
    re-send filter the stale header is re-sent at the head on every tick.
- bf34ec488 `fix(primary): refuse vote requests while inactive`
  A CvvInactive node has no live DAG to check parents against, yet it holds each vote request in
    wait_for_execution until the 5-s vote_timeout; request_vote re-asks up to six times 250 ms apart, so one call
    costs the requester about 36 s. vote_request now refuses with HeaderError::NotActiveCvv (also for an observer)
    after the author check and the recast of a stored vote, before the per-author lock and the execution wait;
    vote_inner checks again before it signs, so a node demoted mid-request signs nothing. The refusal is
    recoverable (the call ends in 1.5 s; the requester votes after the rejoin), has no penalty and is counted in
    tn_primary.votes_refused_inactive_total. Superseded by PR 1531 if it lands first.
- cae41a400 `fix(primary): bound the voter's wait for execution`
  A voter behind on execution held each vote request in wait_for_execution until the 5-s vote_timeout, so one
    request_vote call (seven attempts) cost the requester about 36 s per header. The wait is now capped at
    VOTE_EXECUTION_WAIT = 1 s (vote_timeout must exceed it); on expiry the voter answers the recoverable,
    unpenalized HeaderError::ExecutionBehind { header_block, local_block }, counted in
    votes_refused_execution_behind_total, with outcome "behind" (as for NotActiveCvv). exec_wait still records the
    wait; the fork check is unchanged. At n=10 a quorum is the proposer plus 2f = 6 others, so pacing holds while
    6 others keep up; with 7 voters a laggard is on the critical path and each refusal adds up to 250 ms plus one
    RTT (~0.5 s for a far validator).
- f2f9437f7 `fix(primary): hold demotion for a grace period after a rejoin`
  In bench 4 (r20261105-0803) bench-validator-05 was promoted with handled round 730 and the head at 750,
    committed nothing while its DAG refilled from peers, and was demoted at round 771 = 730 + 41, the first
    certificate past the 40-round activity window. A promotion now goes through the subscriber's promote(), which
    stamps a node-lifetime, epoch-keyed rejoin state on the bus (epoch, attempts, promoted_at) before the mode
    flips. For REJOIN_DEMOTION_GRACE (30 s: the parent fetches and first commits) and within ROUNDS_TO_KEEP -
    gc_depth rounds of the committed round, a demotion for the activity window is held, counted in
    tn_primary.rejoin_grace_holds_total and logged at most once a second; an epoch behind is not held.
- 73d3163db `fix(executor): stay inactive after two rejoins in an epoch`
  In bench 4 (r20261105-0803) no mid-epoch promotion stayed active, and each round trip of the promotion/demotion
    loop left the committee with a member that proposed without committing until the activity window demoted it
    again. A catching-up CVV now rejoins at most MAX_REJOIN_ATTEMPTS_PER_EPOCH (2) times per epoch, every
    promotion counting: past that, rejoin_ready refuses and the not ready line and
    tn_executor_rejoin_blocked_total carry the new attempts_exhausted reason, after a closed epoch and ahead of
    the head conditions. The epoch key resets the count at the next epoch (the sticky inactive entry too); a
    demotion keeps it.
- ae68877dc `test(e2e): one rejoin and a populated DAG for a lagged restart under load`
  On bench 4 a promoted validator restored an empty DAG, failed its certificate fetches on missing parents and was
    demoted again 41 rounds later. test_restarts_lagged_under_load now holds the lagged validator 35 s past its
    rejoin (the 30-s rejoin grace plus 5 s) under the same load and asserts one rejoin, still CvvActive, no
    demotion after the promotion, own headers certified, no fetch failing on missing parents and no header re-
    proposed more than gc_depth rounds below the newest. The restored DAG is recorded without an expectation,
    since it refills from peers: 0 certs, 143-165 own certificates and 0 grace holds measured; a one-off run at
    gc_depth 50 passed the same way (0 certs, 158 own certificates, primed at the head), so neither depth
    reproduces the failure.

## Why (measured motivation)
See the issue text tasks/issues/bench5-f3-rejoin-loop.md — bench 4 (r20261105-0803) evidence with `<inst>:<ts>` cites.

## Evidence (bench 5, run <R>)
(to be filled in Wave E from benchmark/private/bench5-<run>/{A1,A3,A4n,A6}: the fields named in tasks/checkpoint-bench5-design.md for this topic, with file cites; verdict confirmed / inconclusive / regressed)

## Follow-ups
(from the tn-review of this topic — tasks/checkpoint-bench5-review-*.md — items deferred to upstream, and the bench-6 items of the design)
