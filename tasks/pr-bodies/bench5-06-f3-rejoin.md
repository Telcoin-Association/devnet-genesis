## Summary

Makes a mid-epoch rejoin hold on the first attempt. Peers keep the certificate rounds a rejoiner rebuilds from, the
proposer starts at the network head, a promotion gets a short demotion grace and at most two attempts per epoch, an
inactive node refuses vote requests, and a voter's wait for execution is capped at 1 s. An inactive member can also
rejoin on a stalled head, so a committee halted below quorum resumes without an operator restart. Three e2e tests cover
the lagged restart and the halted committee.

PR {{K}} of 10 into `staging/benchmark-obs-2026-11`. Merge order: {{ORDER}}. Stacked on {{PR:prev}}: this head contains its commits, so the Files tab shows the whole stack until it merges; this topic alone is https://github.com/Telcoin-Association/telcoin-network/compare/{{PREV_HEAD_SHA}}...{{HEAD_SHA}} ({{N}} commits). Please merge with 'Create a merge commit' so the next PR's diff collapses; staging goes to main as one squash PR, which must repeat the `Closes` lines for F1, F2 and F3.

## Problem

A validator demoted mid-epoch never rejoined for good before the next epoch. In bench 4 (r20261105-0803) validator-05
was promoted at 10:00:59Z with handled round 730 and the head at 750, restored `num_certs=0`, hit 11 certificate fetch
failures for missing parents, committed nothing and was demoted at round 771 = 730 + 41, the first certificate past the
40-round activity window. It had proposed round 5 with `primary_round` at 4 although it had executed round 730, and it
re-sent that stored header on eleven later promotions. No mid-epoch promotion stayed active, and each round trip of the
loop left the committee with a member that proposed without committing until the activity window demoted it again.

Voters made each attempt costlier. A `CvvInactive` node, or a voter behind on execution, held each vote request in
`wait_for_execution` until the 5-s `vote_timeout`. `request_vote` re-asks up to six times 250 ms apart, so one call cost
the requester about 36 s per header (#1782).

{{ISSUE:f3-rejoin-loop}} has the bench-4 evidence with log cites and the mechanism.

## Fix

- {{SHA:746ac3272}} `fix(storage): keep the certificate rounds a rejoining validator rebuilds from`: peers prune
  certificates below their newest written round H minus `ROUNDS_TO_KEEP`, and a validator restarting consensus at its
  handled leader round C needs every round above C − gc_depth for the certificate manager's parent check and
  Bullshark's `check_parents`. With 64 rounds kept at gc_depth 50 that fails once H − C reaches 16, inside the 20-round
  rejoin window. 128 rounds hold up to H − C = 79 (the constant moves to tn-types, re-exported by tn-storage); startup
  refuses gc_depth + activity window + 10 > 128, that is gc_depth above 64. Cost: about twice the certificate store's
  live footprint; the pruning cadence is unchanged.
- {{SHA:0c41872ba}} `fix(state-sync): rejoin proposes at the network head`: `prime_consensus` now seeds `primary_round`,
  never `committed_round`, from the newest same-epoch header. `Proposer::new` starts at or above it, so replayed store
  rounds cannot move it back; a proposer above round 0 waits for parents of its own round; and the max-delay tick
  re-sends `LastProposed` only at or above its round (the record stays stored). The pieces are unsafe apart: the seed
  alone proposes on round-0 parents, and without the re-send filter the stale header is re-sent at the head on every
  tick.
- {{SHA:bf34ec488}} `fix(primary): refuse vote requests while inactive`: a `CvvInactive` node has no live DAG to check
  parents against. `vote_request` now refuses with `HeaderError::NotActiveCvv` (also for an observer) after the author
  check and the recast of a stored vote, before the per-author lock and the execution wait; `vote_inner` checks again
  before it signs, so a node demoted mid-request signs nothing. The refusal is recoverable (the call ends in 1.5 s and
  the requester votes after the rejoin), has no penalty and is counted in `tn_primary.votes_refused_inactive_total`.
  Superseded by #1531 if that lands first.
- {{SHA:cae41a400}} `fix(primary): bound the voter's wait for execution`: the wait is capped at `VOTE_EXECUTION_WAIT` =
  1 s (`vote_timeout` must exceed it). On expiry the voter answers the recoverable, unpenalized
  `HeaderError::ExecutionBehind { header_block, local_block }`, counted in `votes_refused_execution_behind_total`, with
  outcome `behind` (as for `NotActiveCvv`). `exec_wait` still records the wait, and the fork check is unchanged. At n = 10
  a quorum is the proposer plus 2f = 6 others, so pacing holds while 6 others keep up; with 7 voters a laggard is on the
  critical path and each refusal adds up to 250 ms plus one RTT (about 0.5 s for a far validator).
- {{SHA:f2f9437f7}} `fix(primary): hold demotion for a grace period after a rejoin`: a promotion now goes through the
  subscriber's `promote()`, which stamps a node-lifetime, epoch-keyed rejoin state on the bus (epoch, attempts,
  promoted_at) before the mode flips. For `REJOIN_DEMOTION_GRACE` (30 s: the parent fetches and first commits) and within
  `ROUNDS_TO_KEEP` − gc_depth rounds of the committed round, a demotion for the activity window is held, counted in
  `tn_primary.rejoin_grace_holds_total` and logged at most once a second. An epoch-behind demotion is not held.
- {{SHA:73d3163db}} `fix(executor): stay inactive after two rejoins in an epoch`: a catching-up CVV rejoins at most
  `MAX_REJOIN_ATTEMPTS_PER_EPOCH` (2) times per epoch. Past that, `rejoin_ready` refuses, and the `rejoin not ready` line
  and `tn_executor_rejoin_blocked_total` carry the new `attempts_exhausted` reason, checked after a closed epoch and
  ahead of the head conditions. The epoch key resets the count at the next epoch (the sticky inactive entry too); a
  demotion keeps it.
- {{SHA:ae68877dc}} `test(e2e): one rejoin and a populated DAG for a lagged restart under load`:
  `test_restarts_lagged_under_load` now holds the lagged validator 35 s past its rejoin (the 30-s grace plus 5 s) under
  the same load and asserts one rejoin, still `CvvActive`, no demotion after the promotion, own headers certified, no
  fetch failing on missing parents, and no header re-proposed more than gc_depth rounds below the newest. The restored DAG
  is recorded without an expectation, since it refills from peers.
- {{SHA:9840759a2}} `fix(executor): rejoin on a stalled consensus head and count only failed rejoin attempts`: an
  inactive CVV checked rejoin readiness only on a new output with a head under 5 s old, so a demotion that left the
  committee below quorum halted it until an operator restart. The catch-up loop now also checks every 5 s and rejoins
  once it has watched its newest header stay unchanged for `REJOIN_STALLED_HEAD_AFTER` (20 s, doubled per failed stalled
  rejoin up to 8×), no peer advertises a newer number, and it has replayed that header. The cap no longer counts every
  promotion: only a demotion inside the grace, or the one the grace held, fails a promotion, and stalled-head promotions
  stay out of the cap. The tracker fetches the held frontier when it starts and on each stalled check, keeps gossip the
  walk cap skipped until a walk ends, drops held gossip once active, never re-requests into a future epoch, and logs
  refused stall checks.
- {{SHA:74a4e984e}} `test(e2e): a halted committee resumes when an inactive member rejoins on a stalled head`:
  `test_restarts_halt_recovers_on_stalled_head`. Four validators, quorum three: node 3 is frozen past its activity
  window, resumed until it demotes itself and frozen again; node 4 is killed and the head of nodes 1-2 stays put for
  21 s; node 3 resumes with no restart.
- {{SHA:685b8505b}} `fix(executor): re-request the outputs behind a frontier when the replay stalls`: a failed promotion
  leaves the outputs the previous stream instance took from the state-sync cache queued, and the next subscriber discards
  them. Later gossip walks start above them and the stream re-asks for a bottom gap only after 60 s, so the inactive node
  logged `stalled head not ready … replayed_number=9` while the head climbed to 75. The stalled-head timer now also
  re-requests [replayed + 1, gossiped] when the replayed output has not moved for a check interval, attempts exhausted or
  not, re-sending the same range with a doubling wait (capped at 60 s) while the floor stays put. The fetch task still
  defers to walks that cover the range.
- {{SHA:067639def}} `test(e2e): restart the halted committee's inactive member so its first demotion is deterministic`:
  the freeze/resume first phase raced. After SIGCONT, node 3 drained the gossip buffered during the freeze oldest-first,
  and a 303-certificate fetch lifted its committed round from 38 to 110 within 15 ms, so no certificate was ever outside
  its window (1 of 3 runs). Node 3 is now killed and restarted for the first demotion (its first gossip certificate is at
  the frontier) and frozen once inactive, and the test waits for one more commit before killing node 4 so the frozen node
  has a head to read. The second resume is still SIGCONT to the same process, so the stalled-head claim is unchanged.

## Testing

{{TESTING:06}}

- `test_restarts_lagged_under_load` (e2e): one rejoin; the restored DAG held 0 certificates, then 143-165 own
  certificates and 0 grace holds. A one-off run at gc_depth 50 passed the same way (0 certificates restored, 158 own
  certificates, primed at the head), so neither depth reproduces the bench failure.
- `test_restarts_halt_recovers_on_stalled_head` (e2e): node 3 promoted on heads 50-60 s old and node 1 committed again
  42-53 s after the resume, with one stalled-head rejoin, no ordinary rejoin and `stale_head` refusals each time. 5 of 5
  runs pass after 067639def.

## Evidence (bench 5, run r20261107-1504)

Run r20261107-1504 (2026-11-07): image `adiri:bench-main-fixes-20261107` (`bench/main-fixes-2026-11` at 067639def), ten
validators and one observer in ten regions (c3-highcpu-8, hyperdisk-balanced), with the bench-4 fleet, parameters and
chaos plan. A light-load arm (8 and 16 senders × window 16, then 600 × window 4) ran before the 600 × 16 chaos blast.
Report: https://benchmark.telcoin.network/runs/r20261107-1504/report.html.

- The killed and restarted validator (v05) rejoined once (bench 4: 13 promotions, 12 fell back): `attempting to rejoin …
  round_gap=20` at 18:22:49.65Z, `CvvActive` at 18:22:49.98Z, still active at the end. `rejoin_grace_holds_total` 0,
  `attempts_exhausted` 0.
- The promotion was clean: `primed consensus rounds exec_round=256 newest_round=524 primary_round=524` (all 133 primed
  lines fleet-wide satisfy primary ≥ newest); first header round 529 with 7 parents (no genesis parents, no
  re-proposal); first own certificate committed 1.85 s after the promotion; no `Fetch task failed … missing parents`.
- While inactive it refused 31,561 vote requests (`votes_refused_inactive_total`; 0 on every other node). The stalled-head
  timer re-requested outputs 8 times and the replay kept moving (43 `stalled head not ready` lines, all `head_age`, with
  `replayed_number` rising between every pair). No halted-committee stall: the longest commit gap was 15.1 s, and the
  kill paused commits for 12.7 s against 17.2 s in bench 4.
- Kill to `CvvActive` took 28 min. Under saturation the follower executed 0.49 outputs/s against 0.437/s committed (net
  +0.1/s), so it rejoined 1-2 min after the load ended. The rejoin rules did their job; catch-up speed is a matter of
  execution throughput.
- F3-6 (cae41a400): `votes_refused_execution_behind_total` ran from 14,802 (v01) to 588 (v08) over the run and was 0 at
  idle and light load; `vote_timeouts_total{stage="exec_wait"}` was 0 everywhere, so the #1782 symptom is gone. Under load
  the seven slower voters refused every header of the three fastest executors (Tokyo 0.2 %, Hong Kong 0.0 %, Mumbai
  16.3 % of own headers certified; their users landed nothing for 787 / 817 / 487 s with no RPC error).
  {{ISSUE:execution-behind-vote-starvation}} shows this is not F3-6's doing. A header lives one round (about 0.86 s)
  before the certifier cancels it, and the middle tier reached the fast proposers' named block 3-4 s after the proposal,
  so the old 5-s wait would also have voted too late. The cause is the execution spread that the commit-lag change
  permits, and the fix is proposer-side (name the (2f+1)-th highest block among the own tip and the parents). Keep F3-6.

Closes {{ISSUE:f3-rejoin-loop}}
Refs #1518
Refs #1513
Refs #1517
Refs #1782
Refs #1531
Refs {{ISSUE:execution-behind-vote-starvation}}
